"""Pay schedule, payday check-in, and the usual salary changing only on confirmation."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import income as income_cases
from nexus.application import salary as salary_cases
from nexus.application import transactions as tx_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.income import IncomeKind
from nexus.application.users import RegisterUser, register_user
from nexus.domain.errors import DuplicateSource, InvalidInput, NotFound
from nexus.domain.ledger import Direction, Source, User
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
    assert payload["text"].startswith("It's payday! 🎉 Has your salary of 5,000.00 SGD come in?")
    labels = [b["label"] for b in payload["buttons"][0]]
    assert labels == ["Log 5,000.00 SGD", "Not yet"]
    assert payload["buttons"][0][0]["data"] == "salary:log:2026-10-23"
    assert (payload["kind"], payload["level"]) == ("payday", "now")


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


async def test_payer_is_kept_cleaned_and_cleared(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    with pytest.raises(InvalidInput, match="when you're paid"):
        await salary_cases.set_payer(uow(), user, "Acme Pte Ltd", now=NOW)
    await salary_cases.set_schedule(
        uow(), user, PayRule.MONTHLY_DAY, day=25, payer="  Acme Pte Ltd  ", now=NOW
    )

    async def payer() -> str | None:
        view = await salary_cases.view(uow(), user, now=NOW)
        assert view is not None
        return view.schedule.payer

    assert await payer() == "Acme Pte Ltd"
    # Changing when they're paid keeps the name unless a new one (or None) is given.
    await salary_cases.set_schedule(uow(), user, PayRule.LAST_WEEKDAY, now=NOW)
    assert await payer() == "Acme Pte Ltd"
    await salary_cases.set_payer(uow(), user, "Globex Ltd", now=NOW)
    assert await payer() == "Globex Ltd"
    with pytest.raises(InvalidInput, match="longer than 80"):
        await salary_cases.set_payer(uow(), user, "x" * 81, now=NOW)
    await salary_cases.set_schedule(uow(), user, PayRule.LAST_WEEKDAY, payer="   ", now=NOW)
    assert await payer() is None


async def _ledger_names(engine: AsyncEngine) -> list[str | None]:
    async with engine.connect() as db:
        rows = await db.execute(select(transactions.c.counterparty).order_by(transactions.c.amount))
        return [r.counterparty for r in rows]


async def test_payday_salary_and_income_take_the_payer_without_overwriting_a_name(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await sgt_user(uow)
    await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=25, now=NOW)
    await salary_cases.set_baseline(uow(), user, Money.of("5000", SGD), now=NOW)
    # No payer yet: no name.
    await income_cases.record_income(
        uow, user, kind=IncomeKind.SALARY, amount=Money.of("100", SGD), occurred_at=NOW
    )
    await salary_cases.set_payer(uow(), user, "Acme Pte Ltd", now=NOW)

    tx = await salary_cases.log_payday_salary(uow, user, date(2026, 10, 23), now=NOW)
    assert tx.counterparty == "Acme Pte Ltd"
    recorded = await income_cases.record_income(
        uow, user, kind=IncomeKind.SALARY, amount=Money.of("200", SGD), occurred_at=NOW
    )
    assert recorded.text.startswith("Recorded 200.00 SGD salary from Acme Pte Ltd.")
    await income_cases.record_income(
        uow,
        user,
        kind=IncomeKind.SALARY,
        amount=Money.of("300", SGD),
        occurred_at=NOW,
        counterparty="Globex Ltd",
    )
    # Other income never takes the salary's payer.
    await income_cases.record_income(
        uow, user, kind=IncomeKind.OTHER, amount=Money.of("400", SGD), occurred_at=NOW
    )
    assert await _ledger_names(engine) == [
        None,
        "Acme Pte Ltd",
        "Globex Ltd",
        None,
        "Acme Pte Ltd",
    ]


async def test_naming_earlier_salaries_touches_only_the_users_unnamed_salaries(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await sgt_user(uow)
    other = await sgt_user(uow, telegram_id=4343)
    for who in (user, other):
        await salary_cases.set_schedule(uow(), who, PayRule.MONTHLY_DAY, day=25, now=NOW)
        await salary_cases.set_baseline(uow(), who, Money.of("5000", SGD), now=NOW)
    await salary_cases.log_payday_salary(uow, user, date(2026, 9, 25), now=NOW)  # by external id
    await salary_cases.log_payday_salary(uow, other, date(2026, 9, 25), now=NOW)
    await income_cases.record_income(  # noted "Salary"
        uow, user, kind=IncomeKind.SALARY, amount=Money.of("100", SGD), occurred_at=NOW
    )
    await income_cases.record_income(  # named already
        uow,
        user,
        kind=IncomeKind.SALARY,
        amount=Money.of("200", SGD),
        occurred_at=NOW,
        counterparty="Globex Ltd",
    )
    await income_cases.record_income(  # not a salary
        uow, user, kind=IncomeKind.OTHER, amount=Money.of("300", SGD), occurred_at=NOW
    )
    await tx_cases.log_transaction(  # money out noted "Salary"
        uow(),
        user.id,
        tx_cases.NewTransaction(
            direction=Direction.OUT,
            amount=Money.of("400", SGD),
            occurred_at=NOW,
            notes="Salary",
            source=Source.MANUAL,
        ),
    )

    assert await salary_cases.count_unnamed(uow(), user) == 2
    with pytest.raises(InvalidInput, match="who pays your salary"):
        await salary_cases.name_unnamed(uow(), user, now=NOW)
    await salary_cases.set_payer(uow(), user, "Acme Pte Ltd", now=NOW)
    assert await _ledger_names(engine) == [None, "Globex Ltd", None, None, None, None]

    assert await salary_cases.name_unnamed(uow(), user, now=NOW) == 2
    # 100 and 5000 (the user's) are named; the other user's 5000, 300 and 400 are not.
    names = await _ledger_names(engine)
    assert sorted(n or "" for n in names) == [
        "",
        "",
        "",
        "Acme Pte Ltd",
        "Acme Pte Ltd",
        "Globex Ltd",
    ]
    assert await salary_cases.count_unnamed(uow(), user) == 0
    assert await salary_cases.count_unnamed(uow(), other) == 1
    assert await salary_cases.name_unnamed(uow(), user, now=NOW) == 0


def test_baseline_question() -> None:
    assert salary_cases.baseline_question(None, Money.of("5000", SGD)) is None
