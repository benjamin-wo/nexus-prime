"""Pay schedule, payday check-in, and the usual salary changing only on confirmation."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import salary as salary_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.users import RegisterUser, register_user
from nexus.domain.errors import DuplicateSource, InvalidInput, NotFound
from nexus.domain.ledger import User
from nexus.domain.money import Money
from nexus.domain.planning import PayRule
from nexus.infra.db.tables import jobs, transactions
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

SGD = "SGD"
NOW = datetime(2026, 10, 1, 4, tzinfo=UTC)


async def sgt_user(uow: UowFactory, telegram_id: int = 4242) -> User:
    registration = await register_user(
        uow(),
        RegisterUser(
            telegram_user_id=telegram_id,
            telegram_chat_id=telegram_id,
            home_currency=SGD,
            timezone="Asia/Singapore",
        ),
    )
    return registration.user


async def checkins(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as db:
        rows = await db.execute(select(jobs).where(jobs.c.kind == TELEGRAM_SEND))
        return [r.payload for r in rows]


async def test_payday_checkin_once_after_nine(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await sgt_user(uow)
    await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=25, now=NOW)
    await salary_cases.set_baseline(uow(), user, Money.of("5000", SGD), now=NOW)

    async def checkin(at: datetime) -> int:
        return await salary_cases.payday_checkin(uow, user, now=at)

    # 25 Oct 2026 is a Sunday, so payday is Friday the 23rd.
    assert await checkin(datetime(2026, 10, 22, 2, tzinfo=UTC)) == 0  # Thursday
    assert await checkin(datetime(2026, 10, 23, 0, 30, tzinfo=UTC)) == 0  # 08:30 SGT
    assert await checkin(datetime(2026, 10, 23, 1, 30, tzinfo=UTC)) == 1  # 09:30 SGT
    assert await checkin(datetime(2026, 10, 23, 5, tzinfo=UTC)) == 0  # once only
    assert await checkin(datetime(2026, 10, 25, 2, tzinfo=UTC)) == 0  # the nominal Sunday
    (payload,) = await checkins(engine)
    assert payload["text"].startswith("It's payday! 🎉 Has your salary of 5000.00 SGD come in?")
    labels = [b["label"] for b in payload["buttons"][0]]
    assert labels == ["Log 5000.00 SGD", "Not yet"]
    assert payload["buttons"][0][0]["data"] == "salary:log:2026-10-23"


async def test_checkin_without_a_usual_salary_asks_for_the_amount(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await sgt_user(uow)
    await salary_cases.set_schedule(uow(), user, PayRule.LAST_WEEKDAY, now=NOW)
    assert (
        await salary_cases.payday_checkin(uow, user, now=datetime(2026, 10, 30, 2, tzinfo=UTC)) == 1
    )
    (payload,) = await checkins(engine)
    assert "tell me the amount" in payload["text"] and payload["buttons"] == []


async def test_logging_payday_salary_once(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await sgt_user(uow)
    await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=25, now=NOW)
    with pytest.raises(InvalidInput, match="no usual salary"):
        await salary_cases.log_payday_salary(uow, user, date(2026, 10, 23), now=NOW)
    await salary_cases.set_baseline(uow(), user, Money.of("5000", SGD), now=NOW)
    tx = await salary_cases.log_payday_salary(uow, user, date(2026, 10, 23), now=NOW)
    assert tx.amount == Money.of("5000", SGD) and tx.notes == "Salary"
    with pytest.raises(DuplicateSource):
        await salary_cases.log_payday_salary(uow, user, date(2026, 10, 23), now=NOW)
    async with engine.connect() as db:
        assert len((await db.execute(select(transactions))).all()) == 1


async def test_schedule_changes_keep_the_usual_salary(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    with pytest.raises(InvalidInput, match="when you're paid"):
        await salary_cases.set_baseline(uow(), user, Money.of("5000", SGD), now=NOW)
    await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=25, now=NOW)
    await salary_cases.set_baseline(uow(), user, Money.of("5000", SGD), now=NOW)
    await salary_cases.set_schedule(
        uow(), user, PayRule.BIWEEKLY, anchor=date(2026, 10, 9), now=NOW
    )
    view = await salary_cases.view(uow(), user, now=NOW)
    assert view is not None
    assert view.schedule.baseline == Money.of("5000", SGD)
    assert view.next_payday == date(2026, 10, 9)
    with pytest.raises(InvalidInput):
        await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, now=NOW)  # no day
    await salary_cases.remove_schedule(uow(), user.id)
    assert await salary_cases.view(uow(), user, now=NOW) is None
    with pytest.raises(NotFound):
        await salary_cases.remove_schedule(uow(), user.id)


def test_baseline_question() -> None:
    assert salary_cases.baseline_question(None, Money.of("5000", SGD)) is None
