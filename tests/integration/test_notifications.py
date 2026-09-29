"""Telling users about their transactions: summaries at fixed local times (by
default once a day at 9pm), or each one as it happens."""

from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import notifications as notify_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.categories import list_categories
from nexus.application.transactions import NewTransaction, create_transaction
from nexus.domain.email import EmailStatus, InboundEmail
from nexus.domain.ledger import Direction, Source, User
from nexus.domain.money import Money
from nexus.domain.notifications import Frequency
from nexus.infra.db.tables import jobs
from tests.fakes import FakeMailbox, FakeRates
from tests.integration.conftest import UowFactory
from tests.integration.test_email import connect, person

pytestmark = pytest.mark.integration

SG = ZoneInfo("Asia/Singapore")
REVIEW = "https://nexus.test/email"


def sg(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=SG)


async def log(
    uow: UowFactory,
    user: User,
    amount: str,
    at: datetime,
    *,
    currency: str = "SGD",
    direction: Direction = Direction.OUT,
    counterparty: str | None = None,
    category: str | None = None,
    source: Source = Source.MANUAL,
) -> None:
    category_id = None
    if category:
        category_id = next(
            c.id for c in await list_categories(uow(), user.id) if c.name == category
        )
    async with uow() as tx:
        await create_transaction(
            tx.ledger,
            user.id,
            NewTransaction(
                direction,
                Money.of(amount, currency),
                at,
                counterparty=counterparty,
                category_id=category_id,
                source=source,
            ),
            now=at,
        )
        await tx.commit()


async def check(uow: UowFactory, user: User, at: datetime, rates: FakeRates | None = None) -> bool:
    return await notify_cases.notify(uow, rates or FakeRates(), user, now=at, review_url=REVIEW)


async def sent(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as db:
        rows = await db.execute(
            select(jobs.c.payload).where(jobs.c.kind == TELEGRAM_SEND).order_by(jobs.c.id)
        )
        return [r[0] for r in rows]


async def test_everyone_gets_an_end_of_day_summary_by_default(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    assert not await check(uow, user, sg(28, 8))  # the first check only starts counting
    await log(uow, user, "12.40", sg(28, 9), counterparty="Grab", category="Transport")
    await log(uow, user, "20.00", sg(28, 12), counterparty="Toast Box", category="Food & Drink")
    await log(uow, user, "5.60", sg(28, 13), counterparty="Kopi", category="Food & Drink")
    await log(uow, user, "10", sg(28, 14), currency="USD", counterparty="OpenRouter")
    await log(uow, user, "4200", sg(28, 15), direction=Direction.IN, counterparty="Employer")
    await log(uow, user, "999", sg(28, 16), source=Source.IMPORT)  # old data, not news

    assert not await check(uow, user, sg(28, 20, 59))  # not 9pm yet
    rates = FakeRates({("USD", "SGD"): {sg(1, 0).date(): "1.30"}})
    assert await check(uow, user, sg(28, 21, 2), rates)
    [summary] = await sent(engine)
    assert summary["text"] == (
        "🧾 Today\n"
        "You spent 51.00 SGD (4 transactions).\n"
        "Food & Drink 25.60 SGD · Uncategorised 13.00 SGD · Transport 12.40 SGD\n"
        "You received 4200.00 SGD (1 transaction).\n"
        "To change how often I send these, just tell me."
    )
    assert "buttons" not in summary

    # Once per day, and nothing at all on a day nothing happened.
    assert not await check(uow, user, sg(28, 21, 30))
    assert not await check(uow, user, sg(29, 21, 1))
    assert len(await sent(engine)) == 1


async def test_receipts_waiting_in_email_are_in_the_summary(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    await check(uow, user, sg(28, 8))
    connection = await connect(uow, user, FakeMailbox())
    async with uow() as tx:
        for n, status in enumerate((EmailStatus.PENDING, EmailStatus.PENDING, EmailStatus.SKIPPED)):
            await tx.email.insert_inbound(
                InboundEmail(
                    id=uuid4(),
                    user_id=user.id,
                    connection_id=connection.id,
                    provider_message_id=f"m{n}",
                    received_at=sg(28, 10),
                    sender="alerts@bank.test",
                    subject="Card alert",
                    status=status,
                    reason=None,
                    draft=None,
                    transaction_id=None,
                    created_at=sg(28, 10 + n),
                )
            )
        await tx.commit()
    assert await check(uow, user, sg(28, 21))
    [summary] = await sent(engine)
    assert summary["text"].splitlines()[1] == "📧 2 receipts from your email are waiting for you."
    assert summary["buttons"] == [[{"label": "Review them", "data": f"url:{REVIEW}"}]]


async def test_three_times_a_day(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    await notify_cases.set_frequency(uow(), user.id, Frequency.THRICE_DAILY, now=sg(28, 8))
    assert not await check(uow, user, sg(28, 9))  # the 9am one: nothing happened yet
    await log(uow, user, "4.50", sg(28, 10), counterparty="Kopi")
    assert not await check(uow, user, sg(28, 13, 55))
    assert await check(uow, user, sg(28, 14))
    await log(uow, user, "8.00", sg(28, 16), counterparty="Bus")
    assert await check(uow, user, sg(28, 20, 1))
    first, second = await sent(engine)
    assert first["text"].startswith("🧾 Since 9am\nYou spent 4.50 SGD (1 transaction).")
    assert second["text"].startswith("🧾 Since 2pm\nYou spent 8.00 SGD (1 transaction).")
    assert "just tell me" not in second["text"]


async def test_instant_tells_what_the_chat_didnt(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    await notify_cases.set_frequency(uow(), user.id, Frequency.INSTANT, now=sg(28, 9))
    # Logged in the chat: the reply there already said so.
    await log(uow, user, "3.20", sg(28, 9, 1), source=Source.TEXT)
    assert not await check(uow, user, sg(28, 9, 5))
    # Logged elsewhere (the web app, a payday check-in): told as it happens.
    await log(uow, user, "4200", sg(28, 9, 6), direction=Direction.IN, counterparty="Salary")
    await log(uow, user, "12.40", sg(28, 9, 7), counterparty="Grab", category="Transport")
    assert await check(uow, user, sg(28, 9, 10))
    [message] = await sent(engine)
    assert message["text"] == (
        "🧾 2 new in your ledger:\n"
        "Received 4200.00 SGD at Salary\n"
        "Spent 12.40 SGD at Grab · Transport"
    )
    await log(uow, user, "6.00", sg(28, 9, 12), counterparty="Kopi")
    assert await check(uow, user, sg(28, 9, 15))
    assert (await sent(engine))[-1]["text"] == "🧾 Spent 6.00 SGD at Kopi."


async def test_off_sends_nothing_and_turning_on_doesnt_replay(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    await check(uow, user, sg(28, 8))
    await notify_cases.set_frequency(uow(), user.id, Frequency.OFF, now=sg(28, 9))
    await log(uow, user, "12.40", sg(28, 10))
    assert not await check(uow, user, sg(28, 21, 1))
    await notify_cases.set_frequency(uow(), user.id, Frequency.DAILY, now=sg(29, 9))
    await log(uow, user, "3.00", sg(29, 10))
    assert await check(uow, user, sg(29, 21, 1))
    [summary] = await sent(engine)
    assert "You spent 3.00 SGD (1 transaction)." in summary["text"]
    current = await notify_cases.get_settings(uow(), user.id)
    assert current.frequency is Frequency.DAILY
    assert notify_cases.describe(current.frequency) == (
        "You get a summary of your transactions once a day at 9pm."
    )


async def test_one_users_summary_never_includes_anothers(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    ann, ben = await person(uow, 1), await person(uow, 2)
    for user in (ann, ben):
        await check(uow, user, sg(28, 8))
    await log(uow, ben, "99.00", sg(28, 10))
    assert not await check(uow, ann, sg(28, 21, 1))
    assert await check(uow, ben, sg(28, 21, 1))
    [summary] = await sent(engine)
    assert summary["user_id"] == str(ben.id)
