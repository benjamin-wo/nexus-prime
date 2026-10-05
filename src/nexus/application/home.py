"""The front desk's "needs you" list: what each department is waiting on the user
for, newest worry first. Read-only; each item links to the page that settles it."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from nexus.application import bills as bill_cases
from nexus.application import bookings as booking_cases
from nexus.application import budgets as budget_cases
from nexus.application import duplicates as duplicate_cases
from nexus.application import email as email_cases
from nexus.application import trips as trip_cases
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.email import EmailStatus
from nexus.domain.ledger import User
from nexus.domain.trips import TripStatus

type UowFactory = Callable[[], UnitOfWork]

# Bills due within this many days are worth a mention.
BILL_DAYS = 7
# Budgets this far used are worth a mention.
BUDGET_PERCENT = 80
DUPLICATE_DAYS = 30


@dataclass(frozen=True, slots=True)
class FeedItem:
    department: str
    kind: str  # "email", "duplicates", "budget", "bill", "trip_budget", "booking", "settle_up"
    text: str
    link: str  # the web app page that deals with it
    urgent: bool = False


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


async def needs_you(
    uow: UowFactory, rates: RateSource, user: User, *, now: datetime
) -> list[FeedItem]:
    items: list[FeedItem] = []
    emails = await email_cases.overview(uow(), user.id, now=now)
    waiting = [e for e in emails.emails if e.status is EmailStatus.PENDING]
    if waiting:
        items.append(
            FeedItem(
                "accounting",
                "email",
                f"{_plural(len(waiting), 'receipt', 'receipts')} from email waiting for you",
                "/accounting/email",
            )
        )
    pairs = await duplicate_cases.find_pairs(
        uow, user, now - timedelta(days=DUPLICATE_DAYS), now + timedelta(days=1)
    )
    if pairs:
        items.append(
            FeedItem(
                "accounting",
                "duplicates",
                f"{_plural(len(pairs), 'possible duplicate', 'possible duplicates')} to check",
                "/accounting/ledger",
            )
        )
    for status in await budget_cases.budget_statuses(uow, rates, user, now=now):
        if status.percent >= BUDGET_PERCENT:
            over = status.percent >= 100
            items.append(
                FeedItem(
                    "accounting",
                    "budget",
                    f"{status.name} budget {'is over' if over else 'is at'} {status.percent}%"
                    f" ({status.spent} of {status.budget.limit})",
                    "/accounting/plan",
                    urgent=over,
                )
            )
    for view in await bill_cases.list_bills(uow, user, now=now):
        if view.days_until <= BILL_DAYS and not view.snoozed(now):
            days = view.days_until
            when = (
                "overdue"
                if days < 0
                else "due today"
                if days == 0
                else "due tomorrow"
                if days == 1
                else f"due in {days} days"
            )
            amount = f" ({view.bill.amount})" if view.bill.amount else ""
            items.append(
                FeedItem(
                    "accounting",
                    "bill",
                    f"{view.bill.name}{amount} {when}",
                    "/accounting/plan",
                    urgent=days <= 0,
                )
            )
    trip = await trip_cases.next_trip(uow, rates, user, now=now)
    percent = trip.spending.percent if trip else None
    if trip and trip.status is TripStatus.ONGOING and percent is not None:
        s = trip.spending
        if percent >= BUDGET_PERCENT:
            over = percent >= 100
            items.append(
                FeedItem(
                    "travel",
                    "trip_budget",
                    f"{trip.trip.destination} budget {'is over' if over else 'is at'} "
                    f"{percent}% ({s.spent} of {trip.trip.budget})",
                    f"/travel/trips/{trip.trip.id}",
                    urgent=over,
                )
            )
    loose = await booking_cases.unattached(uow(), user.id)
    today = now.astimezone(ZoneInfo(user.timezone)).date()
    loose = [b for b in loose if (b.draft.ends or b.starts) >= today]
    if loose:
        items.append(
            FeedItem(
                "travel",
                "booking",
                f"{_plural(len(loose), 'booking', 'bookings')} from email not on a trip",
                "/travel",
            )
        )
    for done, owed in await trip_cases.to_settle(uow, rates, user, now=now):
        items.append(
            FeedItem(
                "travel",
                "settle_up",
                f"Settle up for {done.destination}: "
                f"{_plural(len(owed), 'person still owes', 'people still owe')} you",
                f"/travel/trips/{done.id}",
            )
        )
    return items
