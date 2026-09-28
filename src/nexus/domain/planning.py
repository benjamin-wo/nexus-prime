"""Budgets and notification timing. Pure rules, no I/O."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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
