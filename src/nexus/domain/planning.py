"""Budgets, bills and notification timing. Pure rules, no I/O."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID

from nexus.domain.ledger import UserId
from nexus.domain.money import Money

# Alert when monthly spending reaches these percentages of a budget.
THRESHOLDS = (50, 80, 100)

# No notifications between 22:00 and 08:00 in the user's timezone.
QUIET_START = time(22)
QUIET_END = time(8)


@dataclass(frozen=True, slots=True)
class Budget:
    """A monthly spending limit, overall (no category) or for one category.

    The same limit applies every month; nothing rolls over.
    """

    id: UUID
    user_id: UserId
    category_id: UUID | None
    limit: Money
    created_at: datetime
    updated_at: datetime

    @property
    def is_overall(self) -> bool:
        return self.category_id is None


def reached(spent: Money, limit: Money) -> list[int]:
    """Thresholds reached, exactly: 50% of 100.00 is reached at 50.00, not 49.99."""
    if spent.currency != limit.currency:
        raise ValueError("spent and limit must be in the same currency")
    return [t for t in THRESHOLDS if spent.amount * 100 >= limit.amount * t]


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month_start(day: date) -> date:
    first = month_start(day)
    return (first + timedelta(days=32)).replace(day=1)


def quiet_until(local: datetime) -> datetime | None:
    """When a notification due at ``local`` may be sent, or None if it may go now.

    ``local`` must be timezone-aware, in the user's timezone.
    """
    if local.tzinfo is None:
        raise ValueError("local time must be timezone-aware")
    now = local.timetz().replace(tzinfo=None)
    if QUIET_END <= now < QUIET_START:
        return None
    day = local.date() if now < QUIET_END else local.date() + timedelta(days=1)
    return datetime.combine(day, QUIET_END, tzinfo=local.tzinfo)


# --- bills --------------------------------------------------------------------------

# Remind this many days before a bill is due.
REMINDER_OFFSETS = (7, 3, 1)
# An unpaid bill stays "overdue" this long before it rolls on to the next due date.
OVERDUE_GRACE = timedelta(days=7)


class Cadence(StrEnum):
    ONCE = "once"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


@dataclass(frozen=True, slots=True)
class Bill:
    """A bill to remember. Never paid by the app, and never written to the ledger."""

    id: UUID
    user_id: UserId
    name: str
    amount: Money | None  # optional: many bills vary
    cadence: Cadence
    anchor: date  # the first due date; later ones follow the cadence from here
    created_at: datetime
    archived_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BillOccurrence:
    """One due date of a bill, stored once something happens to it (a reminder,
    a snooze or a payment)."""

    id: UUID
    user_id: UserId
    bill_id: UUID
    due: date
    paid_at: datetime | None = None
    snoozed_until: datetime | None = None
    reminded_offset: int | None = None  # the most urgent reminder sent (7, 3 or 1)


def _add_months(anchor: date, months: int) -> date:
    """The anchor's day ``months`` later, clamped to the end of shorter months
    (31 Jan -> 28/29 Feb -> 31 Mar)."""
    index = anchor.month - 1 + months
    year, month = anchor.year + index // 12, index % 12 + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(anchor.day, last))


def due_date(anchor: date, cadence: Cadence, n: int) -> date:
    """The n-th due date (n = 0 is the anchor). Always computed from the anchor, so a
    bill on the 31st comes back to the 31st after a short month."""
    match cadence:
        case Cadence.ONCE:
            if n:
                raise ValueError("a one-off bill has a single due date")
            return anchor
        case Cadence.WEEKLY:
            return anchor + timedelta(weeks=n)
        case Cadence.MONTHLY:
            return _add_months(anchor, n)
        case Cadence.YEARLY:
            return _add_months(anchor, 12 * n)


def due_dates(anchor: date, cadence: Cadence, start: date, end: date) -> list[date]:
    """Due dates in [start, end]."""
    found: list[date] = []
    n = 0
    while True:
        try:
            day = due_date(anchor, cadence, n)
        except ValueError:
            return found
        if day > end:
            return found
        if day >= start:
            found.append(day)
        n += 1


def reminder_offset(days_until: int) -> int | None:
    """Which reminder applies ``days_until`` days before a due date: the most urgent
    of 7/3/1 that has been reached (5 days before is the 7-day reminder, sent late)."""
    if days_until < 0:
        return None
    reached = [k for k in REMINDER_OFFSETS if days_until <= k]
    return min(reached) if reached else None
