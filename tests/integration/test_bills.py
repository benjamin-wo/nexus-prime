"""Bills: reminders at 7/3/1 days, snooze, mark paid, and the next occurrence."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import bills as bill_cases
from nexus.application import transactions as tx_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.transactions import NewTransaction
from nexus.application.users import RegisterUser, register_user
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, User
from nexus.domain.money import Money
from nexus.domain.planning import Cadence
from nexus.infra.db.tables import jobs, transactions
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

SGT = ZoneInfo("Asia/Singapore")
SGT_9AM = 1  # 01:00 UTC is 09:00 in Singapore


def at(day: date) -> datetime:
    """09:00 Singapore time on ``day``."""
    return datetime(day.year, day.month, day.day, SGT_9AM, tzinfo=UTC)


async def sgt_user(uow: UowFactory, telegram_id: int = 4242) -> User:
    registration = await register_user(
        uow(),
        RegisterUser(
            telegram_user_id=telegram_id,
            telegram_chat_id=telegram_id,
            home_currency="SGD",
            timezone="Asia/Singapore",
        ),
    )
    return registration.user


async def reminders(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as db:
        rows = await db.execute(
            select(jobs).where(jobs.c.kind == TELEGRAM_SEND).order_by(jobs.c.id)
        )
        return [r.payload for r in rows]


async def test_reminders_at_7_3_1_days_once_each(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await sgt_user(uow)
    due = date(2026, 10, 15)
    rent = await bill_cases.add_bill(
        uow(),
        user,
        "Rent",
        due,
        Cadence.MONTHLY,
        Money.of("1800", "SGD"),
        now=at(date(2026, 10, 1)),
    )

    async def sweep(day: date) -> int:
        return await bill_cases.send_reminders(uow, user, now=at(day))

    assert await sweep(date(2026, 10, 7)) == 0  # 8 days out
    assert await sweep(date(2026, 10, 8)) == 1  # 7 days
    assert await sweep(date(2026, 10, 8)) == 0  # not twice
    assert await sweep(date(2026, 10, 10)) == 0  # 5 days: the 7-day one was sent
    assert await sweep(date(2026, 10, 12)) == 1  # 3 days
    assert await sweep(date(2026, 10, 14)) == 1  # 1 day
    assert await sweep(date(2026, 10, 15)) == 0  # due today: 1-day reminder already sent
    texts = [p["text"] for p in await reminders(engine)]
    assert texts == [
        "Reminder: Rent (1800.00 SGD) is due in 7 days (Thu 15 Oct).",
        "Reminder: Rent (1800.00 SGD) is due in 3 days (Thu 15 Oct).",
        "Reminder: Rent (1800.00 SGD) is due tomorrow (Thu 15 Oct).",
    ]
    buttons = (await reminders(engine))[0]["buttons"][0]
    assert [b["label"] for b in buttons] == ["Mark paid", "Snooze 1 day"]
    assert buttons[0]["data"].startswith("bill:paid:")

    # Paid: the next month's due date takes over, with its own reminders.
    paid = await bill_cases.mark_paid(uow, user, rent.id, now=at(date(2026, 10, 15)))
    assert paid.view.due == due
    (view,) = await bill_cases.list_bills(uow, user, now=at(date(2026, 10, 15)))
    assert view.due == date(2026, 11, 15)
    assert await sweep(date(2026, 11, 8)) == 1
    # Marking it paid logged the rent once, as this month's expense; reminders never did.
    async with engine.connect() as db:
        rows = (await db.execute(select(transactions))).all()
    assert len(rows) == 1


async def test_marking_paid_logs_the_bill_in_the_months_spending(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await sgt_user(uow)
    rent = await bill_cases.add_bill(
        uow(),
        user,
        "Rent",
        date(2026, 10, 1),
        Cadence.MONTHLY,
        Money.of("1800", "SGD"),
        now=at(date(2026, 9, 25)),
    )
    paid = await bill_cases.mark_paid(uow, user, rent.id, now=at(date(2026, 10, 1)))
    assert paid.logged is not None and paid.already is None
    assert paid.logged.amount == Money.of("1800", "SGD")
    assert paid.logged.counterparty == "Rent"
    assert paid.message(SGT) == (
        "Marked Rent (1 Oct) as paid and logged 1800.00 SGD in this month's spending."
    )
    async with uow() as tx:
        categories = {
            c.id: c.name for c in await tx.ledger.list_categories(user.id, include_inactive=False)
        }
    assert paid.logged.category_id is not None
    assert categories[paid.logged.category_id] == bill_cases.BILLS_CATEGORY


async def test_a_bill_already_in_the_ledger_isnt_logged_twice(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await sgt_user(uow)
    phone = await bill_cases.add_bill(
        uow(),
        user,
        "Phone",
        date(2026, 10, 5),
        Cadence.MONTHLY,
        Money.of("45", "SGD"),
        now=at(date(2026, 9, 25)),
    )
    # The bank's email already logged it the day before.
    await tx_cases.log_transaction(
        uow(),
        user.id,
        NewTransaction(
            direction=Direction.OUT,
            amount=Money.of("45", "SGD"),
            occurred_at=at(date(2026, 10, 4)),
            counterparty="Phone",
        ),
    )
    paid = await bill_cases.mark_paid(uow, user, phone.id, now=at(date(2026, 10, 5)))
    assert paid.logged is None and paid.already is not None
    assert "already in your spending: 45.00 SGD on 4 Oct" in paid.message(SGT)
    async with engine.connect() as db:
        assert len((await db.execute(select(transactions))).all()) == 1


async def test_a_bill_with_no_amount_is_logged_only_with_one(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    power = await bill_cases.add_bill(
        uow(),
        user,
        "Electricity",
        date(2026, 10, 8),
        Cadence.MONTHLY,
        None,
        now=at(date(2026, 9, 25)),
    )
    water = await bill_cases.add_bill(
        uow(),
        user,
        "Water",
        date(2026, 10, 8),
        Cadence.MONTHLY,
        None,
        now=at(date(2026, 9, 25)),
    )
    unknown = await bill_cases.mark_paid(uow, user, power.id, now=at(date(2026, 10, 8)))
    assert unknown.logged is None and unknown.amount is None
    assert "no set amount" in unknown.message(SGT)
    given = await bill_cases.mark_paid(
        uow, user, water.id, now=at(date(2026, 10, 8)), amount=Money.of("38.20", "SGD")
    )
    assert given.logged is not None and given.logged.amount == Money.of("38.20", "SGD")
    with pytest.raises(InvalidInput, match="more than zero"):
        await bill_cases.mark_paid(
            uow, user, water.id, now=at(date(2026, 10, 9)), amount=Money.of("0", "SGD")
        )


async def test_a_late_bill_gets_the_most_urgent_reminder_only(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await sgt_user(uow)
    today = date(2026, 10, 13)
    await bill_cases.add_bill(
        uow(), user, "Water", date(2026, 10, 15), Cadence.ONCE, None, now=at(today)
    )
    assert await bill_cases.send_reminders(uow, user, now=at(today)) == 1
    assert [p["text"] for p in await reminders(engine)] == [
        "Reminder: Water is due in 2 days (Thu 15 Oct)."
    ]


async def test_snooze_holds_then_reminds_again(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await sgt_user(uow)
    bill = await bill_cases.add_bill(
        uow(), user, "Phone", date(2026, 10, 20), Cadence.MONTHLY, None, now=at(date(2026, 10, 1))
    )
    assert await bill_cases.send_reminders(uow, user, now=at(date(2026, 10, 17))) == 1
    await bill_cases.snooze(uow, user, bill.id, now=at(date(2026, 10, 17)))
    later_that_day = at(date(2026, 10, 17)) + timedelta(hours=6)
    assert await bill_cases.send_reminders(uow, user, now=later_that_day) == 0
    (view,) = await bill_cases.list_bills(uow, user, now=later_that_day)
    assert view.snoozed(later_that_day)
    assert (
        await bill_cases.send_reminders(uow, user, now=at(date(2026, 10, 18)) + timedelta(hours=1))
        == 1
    )
    assert len(await reminders(engine)) == 2


async def test_overdue_bills_roll_on_after_a_week(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    await bill_cases.add_bill(
        uow(), user, "Gym", date(2026, 10, 5), Cadence.MONTHLY, None, now=at(date(2026, 10, 1))
    )
    (view,) = await bill_cases.list_bills(uow, user, now=at(date(2026, 10, 9)))
    assert view.due == date(2026, 10, 5) and view.days_until == -4
    assert bill_cases.describe_due(view) == "overdue since Mon 5 Oct"
    (view,) = await bill_cases.list_bills(uow, user, now=at(date(2026, 10, 13)))
    assert view.due == date(2026, 11, 5)


async def test_one_off_bill_disappears_once_paid(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    bill = await bill_cases.add_bill(
        uow(), user, "Passport", date(2026, 10, 20), Cadence.ONCE, None, now=at(date(2026, 10, 1))
    )
    await bill_cases.mark_paid(uow, user, bill.id, now=at(date(2026, 10, 2)))
    assert await bill_cases.list_bills(uow, user, now=at(date(2026, 10, 2))) == []
    with pytest.raises(InvalidInput, match="nothing left"):
        await bill_cases.mark_paid(uow, user, bill.id, now=at(date(2026, 10, 3)))


async def test_bills_are_private(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    other = await sgt_user(uow, 5151)
    bill = await bill_cases.add_bill(
        uow(), user, "Rent", date(2026, 10, 20), Cadence.MONTHLY, None, now=at(date(2026, 10, 1))
    )
    for act in (bill_cases.mark_paid, bill_cases.snooze):
        with pytest.raises(NotFound):
            await act(uow, other, bill.id, now=at(date(2026, 10, 2)))
    with pytest.raises(NotFound):
        await bill_cases.remove_bill(uow(), other.id, bill.id, now=at(date(2026, 10, 2)))
    assert await bill_cases.list_bills(uow, other, now=at(date(2026, 10, 2))) == []
    await bill_cases.remove_bill(uow(), user.id, bill.id, now=at(date(2026, 10, 2)))
    assert await bill_cases.list_bills(uow, user, now=at(date(2026, 10, 2))) == []


async def test_bill_validation(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    now = at(date(2026, 10, 1))
    with pytest.raises(InvalidInput, match="already passed"):
        await bill_cases.add_bill(uow(), user, "Old", date(2026, 9, 1), Cadence.ONCE, None, now=now)
    with pytest.raises(InvalidInput, match="name"):
        await bill_cases.add_bill(uow(), user, "  ", date(2026, 10, 9), Cadence.ONCE, None, now=now)
