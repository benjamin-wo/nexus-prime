"""Bills: remember due dates, remind 7/3/1 days before, snooze and mark paid.

Nothing here pays anything or writes to the ledger: marking a bill paid only
records that the user says it's paid.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.budgets import TELEGRAM_SEND, UowFactory
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User, UserId, clean_name
from nexus.domain.money import Money
from nexus.domain.planning import (
    OVERDUE_GRACE,
    Bill,
    BillOccurrence,
    Cadence,
    due_dates,
    reminder_offset,
)

# Far enough ahead to find the next due date of any cadence.
_LOOKAHEAD = timedelta(days=400)
SNOOZE = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class BillView:
    """A bill with its current due date: the earliest unpaid one, counting dates up
    to a week overdue."""

    bill: Bill
    due: date
    occurrence: BillOccurrence | None  # stored state for that date, if any
    today: date

    @property
    def days_until(self) -> int:
        return (self.due - self.today).days

    def snoozed(self, now: datetime) -> bool:
        until = self.occurrence.snoozed_until if self.occurrence else None
        return until is not None and until > now


def _today(user: User, now: datetime) -> date:
    return now.astimezone(ZoneInfo(user.timezone)).date()


async def _view(tx: UnitOfWork, bill: Bill, today: date) -> BillView | None:
    since = today - OVERDUE_GRACE
    stored = {o.due: o for o in await tx.planning.occurrences(bill.user_id, bill.id, since)}
    for day in due_dates(bill.anchor, bill.cadence, since, today + _LOOKAHEAD):
        occurrence = stored.get(day)
        if occurrence is None or occurrence.paid_at is None:
            return BillView(bill, day, occurrence, today)
    return None  # a one-off bill that's paid or long past


def describe_due(view: BillView) -> str:
    when = view.due.strftime("%a %-d %b")
    match view.days_until:
        case 0:
            return f"due today ({when})"
        case 1:
            return f"due tomorrow ({when})"
        case n if n < 0:
            return f"overdue since {when}"
        case n:
            return f"due in {n} days ({when})"


def _label(bill: Bill) -> str:
    return f"{bill.name} ({bill.amount})" if bill.amount else bill.name


async def add_bill(
    uow: UnitOfWork,
    user: User,
    name: str,
    due: date,
    cadence: Cadence,
    amount: Money | None,
    *,
    now: datetime,
) -> Bill:
    if amount is not None and not amount.is_positive:
        raise InvalidInput("a bill's amount must be more than zero")
    if due < _today(user, now) - OVERDUE_GRACE and cadence is Cadence.ONCE:
        raise InvalidInput("that due date has already passed")
    bill = Bill(
        uuid4(), user.id, clean_name(name, field_name="bill name"), amount, cadence, due, now
    )
    async with uow:
        await uow.planning.insert_bill(bill)
        await uow.commit()
    return bill


async def list_bills(uow: UowFactory, user: User, *, now: datetime) -> list[BillView]:
    """Active bills by their current due date."""
    today = _today(user, now)
    async with uow() as tx:
        views = [await _view(tx, b, today) for b in await tx.planning.list_bills(user.id)]
    return sorted((v for v in views if v is not None), key=lambda v: (v.due, v.bill.name))


async def _bill(tx: UnitOfWork, actor: UserId, bill_id: UUID) -> Bill:
    bill = await tx.planning.get_bill(actor, bill_id)
    if bill is None or bill.archived_at is not None:
        raise NotFound("bill not found")
    return bill


async def mark_paid(uow: UowFactory, user: User, bill_id: UUID, *, now: datetime) -> BillView:
    """Mark the current due date paid. Returns the view that was paid."""
    async with uow() as tx:
        view = await _view(tx, await _bill(tx, user.id, bill_id), _today(user, now))
        if view is None:
            raise InvalidInput("that bill has nothing left to pay")
        current = view.occurrence or BillOccurrence(uuid4(), user.id, bill_id, view.due)
        await tx.planning.save_occurrence(replace(current, paid_at=now, snoozed_until=None))
        await tx.commit()
    return view


async def snooze(uow: UowFactory, user: User, bill_id: UUID, *, now: datetime) -> BillView:
    """Hold reminders for a day; then the current one is sent again."""
    async with uow() as tx:
        view = await _view(tx, await _bill(tx, user.id, bill_id), _today(user, now))
        if view is None:
            raise InvalidInput("that bill has nothing left to pay")
        current = view.occurrence or BillOccurrence(uuid4(), user.id, bill_id, view.due)
        await tx.planning.save_occurrence(
            replace(current, snoozed_until=now + SNOOZE, reminded_offset=None)
        )
        await tx.commit()
    return view


async def occurrence_bill(uow: UnitOfWork, actor: UserId, occurrence_id: UUID) -> UUID | None:
    """The bill a reminder's button refers to, if it's still this user's to act on."""
    async with uow:
        occurrence = await uow.planning.get_occurrence(actor, occurrence_id)
        if occurrence is None or occurrence.paid_at is not None:
            return None
        return occurrence.bill_id


async def remove_bill(uow: UnitOfWork, actor: UserId, bill_id: UUID, *, now: datetime) -> None:
    async with uow:
        if not await uow.planning.archive_bill(actor, bill_id, now):
            raise NotFound("bill not found")
        await uow.commit()


def reminder_text(view: BillView) -> str:
    return f"Reminder: {_label(view.bill)} is {describe_due(view)}."


async def send_reminders(uow: UowFactory, user: User, *, now: datetime) -> int:
    """Queue the reminder due for each bill: the most urgent of 7/3/1 days reached,
    once each, none while snoozed. Returns how many were queued."""
    queued = 0
    for view in await list_bills(uow, user, now=now):
        offset = reminder_offset(view.days_until)
        if offset is None or view.snoozed(now):
            continue
        sent = view.occurrence.reminded_offset if view.occurrence else None
        if sent is not None and offset >= sent:
            continue
        async with uow() as tx:
            current = view.occurrence or BillOccurrence(uuid4(), user.id, view.bill.id, view.due)
            stored = await tx.planning.save_occurrence(replace(current, reminded_offset=offset))
            # A snooze resets the reminder, so it's part of the key.
            round_ = stored.snoozed_until.isoformat() if stored.snoozed_until else "0"
            queued += await tx.jobs.enqueue(
                TELEGRAM_SEND,
                {
                    "user_id": str(user.id),
                    "text": reminder_text(view),
                    "buttons": [
                        [
                            {"label": "Mark paid", "data": f"bill:paid:{stored.id}"},
                            {"label": "Snooze 1 day", "data": f"bill:snooze:{stored.id}"},
                        ]
                    ],
                },
                dedupe_key=f"bill-reminder:{stored.id}:{offset}:{round_}",
                run_at=now,
            )
            await tx.commit()
    return queued
