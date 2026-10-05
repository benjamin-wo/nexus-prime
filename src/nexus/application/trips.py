"""Trips (Travel department): making them, what's been spent on them, money set
aside for them and who still owes what afterwards.

Spending on a trip is found, not filed: money out in the trip's currency on one of
its days counts, as does anything added to it by hand, less anything taken off by
hand. The user's own share counts (a bill less the shares of it others owe), in the
home currency at the rate for the day it was spent.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application import cashflow, fx
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.bookings import Booking
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, User, UserId, same_person
from nexus.domain.money import Money
from nexus.domain.planning import paydays
from nexus.domain.trips import (
    MAX_TRIPS,
    Owed,
    SetAside,
    Trip,
    TripItem,
    TripSpending,
    TripStatus,
    check_dates,
    clean_companions,
    clean_currency,
    clean_destination,
    clean_planned,
    describe_trip,
    home_amount,
    set_aside,
    spending,
)

type UowFactory = Callable[[], UnitOfWork]

MAX_EXPENSES = 1000
# A finished trip still worth a settle-up reminder on Home.
SETTLE_DAYS = 45


@dataclass(frozen=True, slots=True)
class TripDraft:
    destination: str
    start: date
    end: date
    currency: str
    budget: Money | None = None
    companions: list[str] = field(default_factory=list)
    set_aside: Money | None = None
    planned: dict[str, Money] = field(default_factory=dict)


def local_today(user: User, now: datetime) -> date:
    return now.astimezone(ZoneInfo(user.timezone)).date()


def _build(user: User, draft: TripDraft, trip_id: UUID, created: datetime, now: datetime) -> Trip:
    check_dates(draft.start, draft.end)
    home = user.home_currency
    return Trip(
        id=trip_id,
        user_id=user.id,
        destination=clean_destination(draft.destination),
        start=draft.start,
        end=draft.end,
        currency=clean_currency(draft.currency),
        budget=home_amount(draft.budget, home, what="budget"),
        companions=clean_companions(draft.companions),
        set_aside=home_amount(draft.set_aside, home, what="amount to set aside"),
        planned=clean_planned(draft.planned, home),
        created_at=created,
        updated_at=now,
    )


async def create_trip(uow: UnitOfWork, user: User, draft: TripDraft, *, now: datetime) -> Trip:
    trip = _build(user, draft, uuid4(), now, now)
    async with uow:
        if len(await uow.trips.list_trips(user.id)) >= MAX_TRIPS:
            raise InvalidInput(f"keep at most {MAX_TRIPS} trips; delete an old one first")
        await uow.trips.insert_trip(trip, user.home_currency)
        await uow.commit()
    return trip


async def update_trip(
    uow: UnitOfWork, user: User, trip_id: UUID, draft: TripDraft, *, now: datetime
) -> Trip:
    async with uow:
        current = await uow.trips.get_trip(user.id, trip_id)
        if current is None:
            raise NotFound("no trip with that id")
        trip = _build(user, draft, trip_id, current.created_at, now)
        await uow.trips.update_trip(trip, user.home_currency)
        await uow.commit()
    return trip


def draft_of(trip: Trip) -> TripDraft:
    return TripDraft(
        trip.destination,
        trip.start,
        trip.end,
        trip.currency,
        trip.budget,
        list(trip.companions),
        trip.set_aside,
        dict(trip.planned),
    )


async def delete_trip(uow: UnitOfWork, user_id: UserId, trip_id: UUID) -> None:
    async with uow:
        if not await uow.trips.delete_trip(user_id, trip_id):
            raise NotFound("no trip with that id")
        await uow.commit()


async def list_trips(uow: UnitOfWork, user_id: UserId) -> list[Trip]:
    async with uow:
        return await uow.trips.list_trips(user_id)


async def get_trip(uow: UnitOfWork, user_id: UserId, trip_id: UUID) -> Trip:
    async with uow:
        trip = await uow.trips.get_trip(user_id, trip_id)
    if trip is None:
        raise NotFound("no trip with that id")
    return trip


def current_or_next(trips: list[Trip], today: date) -> Trip | None:
    """The trip that's on, else the next one, else the one that ended last."""
    ongoing = [t for t in trips if t.status(today) is TripStatus.ONGOING]
    if ongoing:
        return min(ongoing, key=lambda t: t.start)
    upcoming = [t for t in trips if t.status(today) is TripStatus.UPCOMING]
    if upcoming:
        return min(upcoming, key=lambda t: t.start)
    return max(trips, key=lambda t: t.end) if trips else None


async def find_trip(uow: UnitOfWork, user: User, name: str | None, *, now: datetime) -> Trip:
    """A trip by its destination ("Japan" finds "Tokyo, Japan"); with no name, the
    one that's on or next."""
    trips = await list_trips(uow, user.id)
    if not trips:
        raise NotFound("no trips yet")
    today = local_today(user, now)
    if not name or not name.strip():
        found = current_or_next(trips, today)
        if found is None:
            raise NotFound("no trips yet")
        return found
    wanted = name.strip().casefold()
    matches = [
        t for t in trips if wanted in t.destination.casefold() or same_person(t.destination, name)
    ]
    if not matches:
        raise NotFound(
            f"no trip to {name.strip()}; trips: " + ", ".join(t.destination for t in trips)
        )
    return current_or_next(matches, today) or matches[0]


async def _expense(uow: UnitOfWork, user_id: UserId, trip_id: UUID, transaction_id: UUID) -> None:
    if await uow.trips.get_trip(user_id, trip_id) is None:
        raise NotFound("no trip with that id")
    tx = await uow.ledger.get_transaction(user_id, transaction_id)
    if tx is None:
        raise NotFound("no transaction with that id")
    if tx.direction is not Direction.OUT:
        raise InvalidInput("only money out can be trip spending")


async def add_expense(
    uow: UnitOfWork, user_id: UserId, trip_id: UUID, transaction_id: UUID, *, now: datetime
) -> None:
    async with uow:
        await _expense(uow, user_id, trip_id, transaction_id)
        await uow.trips.set_link(user_id, trip_id, transaction_id, included=True, at=now)
        await uow.commit()


async def remove_expense(
    uow: UnitOfWork, user_id: UserId, trip_id: UUID, transaction_id: UUID, *, now: datetime
) -> None:
    """Takes it off the trip, and keeps it off even if its date and currency match."""
    async with uow:
        await _expense(uow, user_id, trip_id, transaction_id)
        await uow.trips.set_link(user_id, trip_id, transaction_id, included=False, at=now)
        await uow.commit()


# --- the trip page ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TripView:
    trip: Trip
    today: date
    status: TripStatus
    items: list[TripItem]
    spending: TripSpending
    saving: SetAside
    paid: bool  # whether the user has a pay schedule, which set-aside needs
    owed: list[Owed]
    # Bookings on the trip (its itinerary), and their cost in the home currency.
    bookings: list[Booking] = field(default_factory=list)
    booked: Money | None = None
    # Booked but not logged yet, so not in what's spent.
    booked_unlogged: Money | None = None
    # The budget less what's spent and what's booked but not logged.
    to_spend: Money | None = None

    @property
    def days_until(self) -> int:
        return (self.trip.start - self.today).days


async def _items(
    uow: UowFactory, rates: RateSource, user: User, trip: Trip
) -> tuple[list[TripItem], set[UUID]]:
    async with uow() as tx:
        expenses = await tx.trips.trip_expenses(user.id, trip, user.timezone, limit=MAX_EXPENSES)
    home = user.home_currency
    own = [(e, e.transaction.amount - e.others) for e in expenses]
    found = await fx.rates_for(rates, home, ((m.currency, e.day) for e, m in own))
    items = [
        TripItem(
            transaction_id=e.transaction.id,
            day=e.day,
            counterparty=e.transaction.counterparty,
            category=e.category,
            amount=amount,
            home=fx.convert(amount, e.day, home, found).home,
            linked=e.linked,
        )
        for e, amount in own
        if amount.is_positive
    ]
    return items, {e.transaction.id for e in expenses}


async def _owed(
    uow: UowFactory, rates: RateSource, user: User, ids: set[UUID], today: date
) -> list[Owed]:
    async with uow() as tx:
        ious = [i for i in await tx.ledger.open_ious(user.id) if i.split.transaction_id in ids]
    home = user.home_currency
    people: dict[str, dict[str, Money]] = {}
    for iou in ious:
        mine = people.setdefault(iou.split.participant_name, {})
        c = iou.outstanding.currency
        mine[c] = mine[c] + iou.outstanding if c in mine else iou.outstanding
    found = await fx.rates_for(rates, home, ((c, today) for m in people.values() for c in m))
    owed: list[Owed] = []
    for name, amounts in sorted(people.items()):
        total: Money | None = Money.zero(home)
        for amount in amounts.values():
            converted = fx.convert(amount, today, home, found).home
            total = total + converted if total is not None and converted is not None else None
        owed.append(Owed(name, sorted(amounts.values(), key=lambda m: m.currency), total))
    return owed


async def _fits(uow: UowFactory, rates: RateSource, user: User, trip: Trip, now: datetime) -> bool:
    """Whether what's expected in, less what's expected out (the set-aside included),
    stays at or above zero from today to the day before the trip."""
    today = local_today(user, now)
    end = min(trip.start - timedelta(days=1), today + timedelta(days=cashflow.MAX_DAYS - 1))
    flow = await cashflow.cash_flow(uow, rates, user, today, end, now=now)
    return flow.expected_in >= flow.expected_out


async def trip_view(
    uow: UowFactory, rates: RateSource, user: User, trip_id: UUID, *, now: datetime
) -> TripView:
    trip = await get_trip(uow(), user.id, trip_id)
    return await _view(uow, rates, user, trip, now=now)


async def _view(
    uow: UowFactory, rates: RateSource, user: User, trip: Trip, *, now: datetime
) -> TripView:
    today = local_today(user, now)
    home = user.home_currency
    items, ids = await _items(uow, rates, user, trip)
    async with uow() as tx:
        schedule = await tx.planning.get_salary_schedule(user.id)
    done: list[date] = []
    ahead: list[date] = []
    if schedule is not None:
        made = trip.created_at.astimezone(ZoneInfo(user.timezone)).date()
        done = paydays(schedule, made, min(today, trip.start - timedelta(days=1)))
        if today + timedelta(days=1) <= trip.start - timedelta(days=1):
            ahead = paydays(schedule, today + timedelta(days=1), trip.start - timedelta(days=1))
    saving = set_aside(trip, done, ahead, home)
    if schedule is not None and trip.set_aside is not None and ahead:
        saving = SetAside(
            saving.per_payday,
            saving.paydays_done,
            saving.paydays_left,
            saving.saved,
            saving.by_start,
            saving.covers_budget,
            saving.suggested,
            await _fits(uow, rates, user, trip, now),
            saving.next_payday,
        )
    async with uow() as tx:
        bookings = await tx.trips.list_bookings(user.id, trip_id=trip.id)
    tz = ZoneInfo(user.timezone)
    costed = [(b, b.cost, b.created_at.astimezone(tz).date()) for b in bookings if b.cost]
    found = await fx.rates_for(rates, home, ((c.currency, d) for _, c, d in costed))
    booked = unlogged = Money.zero(home)
    for b, cost, day in costed:
        converted = fx.convert(cost, day, home, found).home
        if converted is None:
            continue
        booked = booked + converted
        if b.transaction_id is None or b.transaction_id not in ids:
            unlogged = unlogged + converted
    spent = spending(trip, items, today, home)
    to_spend = trip.budget - spent.spent - unlogged if trip.budget else None
    return TripView(
        trip=trip,
        today=today,
        status=trip.status(today),
        items=items,
        spending=spent,
        saving=saving,
        paid=schedule is not None,
        owed=await _owed(uow, rates, user, ids, today),
        bookings=bookings,
        booked=booked if costed else None,
        booked_unlogged=unlogged if costed else None,
        to_spend=to_spend,
    )


async def next_trip(
    uow: UowFactory, rates: RateSource, user: User, *, now: datetime
) -> TripView | None:
    """The trip that's on or coming up, for Home."""
    today = local_today(user, now)
    trips = [
        t for t in await list_trips(uow(), user.id) if t.status(today) is not TripStatus.FINISHED
    ]
    trip = current_or_next(trips, today)
    return await _view(uow, rates, user, trip, now=now) if trip else None


async def to_settle(
    uow: UowFactory, rates: RateSource, user: User, *, now: datetime
) -> list[tuple[Trip, list[Owed]]]:
    """Recently finished trips that people still owe the user for."""
    today = local_today(user, now)
    found: list[tuple[Trip, list[Owed]]] = []
    for trip in await list_trips(uow(), user.id):
        if trip.status(today) is TripStatus.FINISHED and (today - trip.end).days <= SETTLE_DAYS:
            _, ids = await _items(uow, rates, user, trip)
            owed = await _owed(uow, rates, user, ids, today)
            if owed:
                found.append((trip, owed))
    return found


def describe_view(view: TripView) -> list[str]:
    """For chat: every figure worked out in code."""
    trip, s, home = view.trip, view.spending, view.spending.spent.currency
    lines = [describe_trip(trip, view.today) + "."]
    spent = f"Spent so far: {s.spent} (the user's own share, in {home})"
    if s.before.is_positive:
        spent += f", of which {s.before} before the trip"
    lines.append(spent + ".")
    if trip.budget and s.left is not None:
        if s.left.is_positive or s.left.is_zero:
            lines.append(f"Left in the budget: {s.left} ({s.percent}% used).")
        else:
            lines.append(f"Over budget by {-s.left} ({s.percent}% used).")
    if s.today is not None:
        lines.append(f"Today: {s.today}.")
    if s.per_day is not None:
        lines.append(f"Average per day so far: {s.per_day}.")
    if s.per_day_left is not None:
        lines.append(f"To stay on budget: about {s.per_day_left} a day for the rest.")
    if s.categories:
        lines.append(
            "By category: "
            + "; ".join(
                f"{c.name} {c.spent}" + (f" (planned {c.planned})" if c.planned else "")
                for c in s.categories
            )
        )
    if s.unconverted:
        lines.append(f"{s.unconverted} expenses have no exchange rate yet and aren't counted.")
    if not view.items:
        lines.append(
            f"No spending found yet: expenses in {trip.currency} between its dates count, "
            "and others can be added to the trip by hand."
        )
    a = view.saving
    if view.status is TripStatus.UPCOMING:
        if a.per_payday and not view.paid:
            lines.append("Setting money aside needs a pay schedule; none is set.")
        elif a.per_payday:
            line = (
                f"Setting aside {a.per_payday} each payday: about {a.saved} so far, "
                f"{a.by_start} by the trip ({a.paydays_left} paydays left)"
            )
            if a.covers_budget is False and a.suggested:
                line += f"; that's short of the budget, {a.suggested} each payday would cover it"
            if a.fits is False:
                line += "; the cash-flow forecast to the trip goes below zero with it"
            lines.append(line + ".")
        elif a.suggested:
            lines.append(
                f"To cover the budget by the trip, set aside about {a.suggested} on each of "
                f"the {a.paydays_left} paydays before it."
            )
    if view.bookings:
        lines.append("Bookings: " + "; ".join(b.draft.describe() for b in view.bookings) + ".")
    if view.booked is not None:
        line = f"Booked: {view.booked}"
        if view.booked_unlogged and view.booked_unlogged.is_positive:
            line += f", of which {view.booked_unlogged} isn't logged as an expense yet"
        lines.append(line + ".")
    if view.to_spend is not None and view.booked is not None:
        lines.append(f"Still to spend in the budget after bookings: {view.to_spend}.")
    if view.owed:
        lines.append(
            "Still owed for this trip: "
            + "; ".join(f"{o.name} {', '.join(str(m) for m in o.amounts)}" for o in view.owed)
        )
    return lines
