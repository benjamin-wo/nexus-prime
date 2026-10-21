"""The front desk's "needs you" list: what each department is waiting on the user
for, most pressing first. Read-only; each item links to the page that settles it.

Order (``needs_you``): urgent items, then items about today, then the rest; within each
group by department (accounting, investment, travel), and as found within a department.
Each item's ``when`` says which group it is in.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import bills as bill_cases
from nexus.application import bookings as booking_cases
from nexus.application import budgets as budget_cases
from nexus.application import duplicates as duplicate_cases
from nexus.application import email as email_cases
from nexus.application import trips as trip_cases
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.alerts import AlertKind, MarketAlert, moved_in
from nexus.domain.bookings import Booking, BookingKind
from nexus.domain.email import EmailStatus
from nexus.domain.ledger import User
from nexus.domain.market import US_MARKET
from nexus.domain.plans import SavedPlan
from nexus.domain.trips import Trip, TripStatus

type UowFactory = Callable[[], UnitOfWork]

# Bills due within this many days are worth a mention.
BILL_DAYS = 7
# Budgets this far used are worth a mention.
BUDGET_PERCENT = 80
DUPLICATE_DAYS = 30
# A trip starting within this many days with things left to do is worth a mention.
PREP_DAYS = 7

# How soon an item needs the user (``FeedItem.when``), most pressing first.
WHEN_ORDER = {"now": 0, "today": 1, "soon": 2}
DEPARTMENT_ORDER = {"accounting": 0, "investment": 1, "travel": 2}


@dataclass(frozen=True, slots=True)
class FeedAction:
    """A button on an item: one request to the web API that settles (part of) it."""

    key: str  # stable, e.g. "went_through"
    label: str
    method: str  # "POST"
    path: str  # relative to /api, query string included


@dataclass(frozen=True, slots=True)
class FeedItem:
    department: str
    # "email", "duplicates", "budget", "bill", "missed_move", "plan_hit", "big_move",
    # "earnings", "trip_budget", "booking", "booking_soon", "prep", "settle_up"
    kind: str
    text: str
    link: str  # the web app page that deals with it
    urgent: bool = False
    actions: tuple[FeedAction, ...] = ()  # buttons that settle it without leaving the page
    today: bool = False  # it is about something today (not already urgent)

    @property
    def when(self) -> str:
        """ "now" if urgent, else "today" if it is about today, else "soon"."""
        return "now" if self.urgent else "today" if self.today else "soon"


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
    asked: set[tuple[UUID, date]] = set()
    for missed in await bill_cases.missed_moves(uow, user, now=now):
        asked.add((missed.bill.id, missed.due))
        query = f"?due={missed.due.isoformat()}"
        items.append(
            FeedItem(
                "accounting",
                "missed_move",
                missed.text(),
                "/accounting/plan",
                urgent=False,
                actions=(
                    FeedAction(
                        "went_through",
                        "It went through",
                        "POST",
                        f"/bills/{missed.bill.id}/paid{query}",
                    ),
                    FeedAction(
                        "skip", "Skip this month", "POST", f"/bills/{missed.bill.id}/skip{query}"
                    ),
                ),
            )
        )
    for view in await bill_cases.list_bills(uow, user, now=now):
        if (view.bill.id, view.due) in asked:
            continue  # already asked about, with buttons
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
    items += await _investment_items(uow, user, now)
    items += await _travel_items(uow, user, now)
    # sorted() is stable: within a group, department by department, items stay as found.
    return sorted(items, key=lambda i: (WHEN_ORDER[i.when], DEPARTMENT_ORDER[i.department]))


# --- investment ------------------------------------------------------------------------


def _price(value: Decimal) -> str:
    return f"{value:,.2f}"


def _plan_level(plan: SavedPlan, kind: AlertKind) -> str | None:
    """The price a plan alert of this kind is about: the buy zone, the stop or the first
    target, as it reads in the text."""
    if kind is AlertKind.PLAN_STOP:
        return _price(plan.stop) if plan.stop is not None else None
    if kind is AlertKind.PLAN_TARGET:
        target = plan.first_target
        return _price(target) if target is not None else None
    if plan.entry_high is None:
        return None
    if plan.entry_low is not None and plan.entry_low != plan.entry_high:
        return f"{_price(plan.entry_low)} to {_price(plan.entry_high)}"
    return _price(plan.entry_high)


PLAN_WORDS = {
    AlertKind.PLAN_ENTRY: "its buy zone",
    AlertKind.PLAN_STOP: "its stop",
    AlertKind.PLAN_TARGET: "its first target",
}


def _plan_hit(alert: MarketAlert, plans: list[SavedPlan]) -> FeedItem:
    """A plan's price reached today. The alert row doesn't name its plan, so it is the
    user's one plan for the stock that was running that day and has the price in question;
    with none or several, the item links to the stock and leaves the price out."""
    found = [
        p
        for p in plans
        if p.symbol == alert.symbol
        and p.as_of <= alert.day <= p.valid_until
        and _plan_level(p, alert.kind) is not None
    ]
    plan = found[0] if len(found) == 1 else None
    level = _plan_level(plan, alert.kind) if plan else None
    text = f"{alert.symbol} reached {PLAN_WORDS[alert.kind]}" + (f" ({level})" if level else "")
    link = f"/investment/plans/{plan.id}" if plan else f"/investment/stocks/{alert.symbol}"
    return FeedItem("investment", "plan_hit", text, link, urgent=alert.urgent, today=True)


async def _investment_items(uow: UowFactory, user: User, now: datetime) -> list[FeedItem]:
    """Plan prices reached, big moves and earnings. "Today" is the New York trading day,
    which is how ``market_alerts`` keys an alert; earnings dates are New York dates too."""
    day = now.astimezone(US_MARKET).date()
    async with uow() as tx:
        alerts = await tx.investments.alerts_on(user.id, day)
        plans = (
            await tx.investments.list_plans(user.id)
            if any(a.kind is not AlertKind.BIG_MOVE for a in alerts)
            else []
        )
        followed = {h.position.symbol for h in await tx.investments.list_holdings(user.id)}
        followed |= set(await tx.investments.list_watch(user.id))
        reporting = await tx.investments.upcoming_earnings(sorted(followed), day)
    items: list[FeedItem] = []
    for alert in alerts:
        if alert.kind is not AlertKind.BIG_MOVE:
            items.append(_plan_hit(alert, plans))
            continue
        change = moved_in(alert.text)
        text = f"{alert.symbol} {change} today" if change else f"{alert.symbol} moved a lot today"
        items.append(
            FeedItem(
                "investment",
                "big_move",
                text,
                f"/investment/stocks/{alert.symbol}",
                today=True,
            )
        )
    for symbol, earnings in sorted(reporting.items()):
        if earnings.day <= day + timedelta(days=1):
            reports_today = earnings.day == day
            items.append(
                FeedItem(
                    "investment",
                    "earnings",
                    f"{symbol} reports earnings {'today' if reports_today else 'tomorrow'}",
                    f"/investment/stocks/{symbol}",
                    today=reports_today,
                )
            )
    return items


# --- travel ----------------------------------------------------------------------------

KIND_WORDS = {BookingKind.FLIGHT: "Flight", BookingKind.RAIL: "Train"}


def _soon_bookings(
    bookings: list[Booking], trip_ids: set[UUID], local: datetime
) -> list[tuple[datetime, FeedItem]]:
    """Departures and check-ins today or tomorrow on the user's trips, each with when it
    happens (to put them in order). Times are the booking's own local times, compared
    with the user's local ``local`` (no timezone), as for the reminders. A departure
    that has already left today is not listed."""
    today = local.date()
    tomorrow = today + timedelta(days=1)
    found: list[tuple[datetime, FeedItem]] = []
    for booking in bookings:
        d = booking.draft
        if booking.trip_id not in trip_ids:
            continue
        link = f"/travel/trips/{booking.trip_id}"
        check_in = d.check_in
        if d.kind is BookingKind.HOTEL and check_in is not None and check_in in (today, tomorrow):
            when = "today" if check_in == today else "tomorrow"
            where = d.hotel or d.provider or "your hotel"
            found.append(
                (
                    datetime.combine(check_in, time()),
                    FeedItem(
                        "travel",
                        "booking_soon",
                        f"Check in at {where} {when}",
                        link,
                        urgent=check_in == today,
                    ),
                )
            )
        elif d.kind in KIND_WORDS:
            for segment in d.segments:
                departs = segment.departs
                if departs is None or departs.date() not in (today, tomorrow):
                    continue
                if departs.date() == today and departs < local:
                    continue
                parts = [KIND_WORDS[d.kind], segment.number]
                if segment.destination:
                    parts.append(f"to {segment.destination}")
                when = "today" if departs.date() == today else "tomorrow"
                parts += [when, f"{departs:%H:%M}"]
                found.append(
                    (
                        departs,
                        FeedItem(
                            "travel",
                            "booking_soon",
                            " ".join(p for p in parts if p),
                            link,
                            urgent=departs.date() == today,
                        ),
                    )
                )
    return sorted(found, key=lambda pair: pair[0])


def _prep(trips: list[Trip], today: date) -> list[FeedItem]:
    """Trips starting within a week with things still to do on their Prep tab."""
    items: list[FeedItem] = []
    for trip in sorted(trips, key=lambda t: t.start):
        left = sum(1 for todo in trip.todos if not todo.done)
        if left and 0 <= (trip.start - today).days <= PREP_DAYS:
            items.append(
                FeedItem(
                    "travel",
                    "prep",
                    f"{_plural(left, 'thing', 'things')} to sort before {trip.destination}",
                    f"/travel/trips/{trip.id}?tab=prep",
                )
            )
    return items


async def _travel_items(uow: UowFactory, user: User, now: datetime) -> list[FeedItem]:
    """Bookings about to happen and trips about to start, on the user's own trips: shared
    trips are left out here as they are from ``next_trip`` and ``list_trips``."""
    local = now.astimezone(ZoneInfo(user.timezone)).replace(tzinfo=None)
    async with uow() as tx:
        trips = await tx.trips.list_trips(user.id)
        bookings = await tx.trips.upcoming_bookings(user.id, local.date())
    soon = _soon_bookings(bookings, {t.id for t in trips}, local)
    return [item for _, item in soon] + _prep(trips, local.date())
