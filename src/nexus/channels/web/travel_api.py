"""The Travel department's API: trips, what's been spent on them, money set aside
and settling up. Nothing here books or buys anything."""

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import bookings as booking_cases
from nexus.application import travel_research as research_cases
from nexus.application import trips as trip_cases
from nexus.channels.web.api import MoneyOut, money
from nexus.channels.web.security import Auth, Runtime
from nexus.domain.bookings import Booking
from nexus.domain.errors import NotFound
from nexus.domain.ledger import User
from nexus.domain.money import Money
from nexus.domain.trips import MAX_COMPANIONS, MAX_PLANNED, Trip

router = APIRouter(prefix="/api/travel")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _uuid(value: str, what: str = "trip") -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise NotFound(f"no {what} with that id") from exc


def _m(value: Money | None) -> MoneyOut | None:
    return money(value) if value is not None else None


class TripOut(Model):
    id: UUID
    destination: str
    start: date
    end: date
    days: int
    currency: str
    budget: MoneyOut | None
    companions: list[str]
    set_aside: MoneyOut | None
    planned: dict[str, MoneyOut]
    status: str  # upcoming, ongoing, finished
    days_until: int  # below zero once it has started
    day_number: int | None  # day 3 of 10, while it's on


def _trip(trip: Trip, today: date) -> TripOut:
    return TripOut(
        id=trip.id,
        destination=trip.destination,
        start=trip.start,
        end=trip.end,
        days=trip.days,
        currency=trip.currency,
        budget=_m(trip.budget),
        companions=list(trip.companions),
        set_aside=_m(trip.set_aside),
        planned={k: money(v) for k, v in trip.planned.items()},
        status=trip.status(today).value,
        days_until=(trip.start - today).days,
        day_number=trip.day_number(today),
    )


class CategoryOut(Model):
    name: str
    planned: MoneyOut | None
    spent: MoneyOut


class SpendingOut(Model):
    spent: MoneyOut
    left: MoneyOut | None
    percent: int | None
    before: MoneyOut
    today: MoneyOut | None
    per_day: MoneyOut | None
    per_day_left: MoneyOut | None
    categories: list[CategoryOut]
    unconverted: int


class SavingOut(Model):
    per_payday: MoneyOut | None
    paydays_done: int
    paydays_left: int
    saved: MoneyOut | None
    by_start: MoneyOut | None
    covers_budget: bool | None
    suggested: MoneyOut | None
    fits: bool | None
    next_payday: date | None
    pay_schedule: bool


class OwedOut(Model):
    name: str
    amounts: list[MoneyOut]
    home: MoneyOut | None


class ItemOut(Model):
    transaction_id: UUID
    day: date
    counterparty: str | None
    category: str | None
    amount: MoneyOut  # the user's own share
    home: MoneyOut | None
    linked: bool


class SegmentOut(Model):
    number: str | None
    origin: str | None
    destination: str | None
    departs: str | None  # local time as booked, YYYY-MM-DDTHH:MM
    arrives: str | None


class BookingOut(Model):
    id: UUID
    trip_id: UUID | None
    kind: str  # flight, hotel, rail
    title: str
    provider: str | None
    starts: date
    ends: date | None
    segments: list[SegmentOut]
    hotel: str | None
    address: str | None
    check_in: date | None
    check_out: date | None
    cost: MoneyOut | None
    logged: bool  # its cost is in the ledger


def _booking(b: Booking) -> BookingOut:
    d = b.draft
    return BookingOut(
        id=b.id,
        trip_id=b.trip_id,
        kind=d.kind.value,
        title=d.title,
        provider=d.provider,
        starts=b.starts,
        ends=d.ends,
        segments=[
            SegmentOut(
                number=s.number,
                origin=s.origin,
                destination=s.destination,
                departs=s.departs.isoformat(timespec="minutes") if s.departs else None,
                arrives=s.arrives.isoformat(timespec="minutes") if s.arrives else None,
            )
            for s in d.segments
        ],
        hotel=d.hotel,
        address=d.address,
        check_in=d.check_in,
        check_out=d.check_out,
        cost=_m(b.cost),
        logged=b.transaction_id is not None,
    )


class TripDetailOut(Model):
    trip: TripOut
    spending: SpendingOut
    saving: SavingOut
    owed: list[OwedOut]
    items: list[ItemOut]
    bookings: list[BookingOut]
    booked: MoneyOut | None
    booked_unlogged: MoneyOut | None
    to_spend: MoneyOut | None


def _detail(view: trip_cases.TripView) -> TripDetailOut:
    s, a = view.spending, view.saving
    return TripDetailOut(
        trip=_trip(view.trip, view.today),
        spending=SpendingOut(
            spent=money(s.spent),
            left=_m(s.left),
            percent=s.percent,
            before=money(s.before),
            today=_m(s.today),
            per_day=_m(s.per_day),
            per_day_left=_m(s.per_day_left),
            categories=[
                CategoryOut(name=c.name, planned=_m(c.planned), spent=money(c.spent))
                for c in s.categories
            ],
            unconverted=s.unconverted,
        ),
        saving=SavingOut(
            per_payday=_m(a.per_payday),
            paydays_done=a.paydays_done,
            paydays_left=a.paydays_left,
            saved=_m(a.saved),
            by_start=_m(a.by_start),
            covers_budget=a.covers_budget,
            suggested=_m(a.suggested),
            fits=a.fits,
            next_payday=a.next_payday,
            pay_schedule=view.paid,
        ),
        owed=[
            OwedOut(name=o.name, amounts=[money(m) for m in o.amounts], home=_m(o.home))
            for o in view.owed
        ],
        items=[
            ItemOut(
                transaction_id=i.transaction_id,
                day=i.day,
                counterparty=i.counterparty,
                category=i.category,
                amount=money(i.amount),
                home=_m(i.home),
                linked=i.linked,
            )
            for i in reversed(view.items)  # newest first
        ],
        bookings=[_booking(b) for b in view.bookings],
        booked=_m(view.booked),
        booked_unlogged=_m(view.booked_unlogged),
        to_spend=_m(view.to_spend),
    )


class TripIn(Model):
    destination: str = Field(min_length=1, max_length=80)
    start: date
    end: date
    currency: str = Field(pattern="^[A-Za-z]{3}$")
    budget: str | None = Field(None, max_length=32)
    companions: list[str] = Field(default_factory=list, max_length=MAX_COMPANIONS)
    set_aside: str | None = Field(None, max_length=32)
    planned: dict[str, str] = Field(default_factory=dict, max_length=MAX_PLANNED)


def _home(user: User, amount: str | None) -> Money | None:
    if amount is None or not amount.strip():
        return None
    return Money.of(amount.replace(",", ""), user.home_currency)


def _draft(user: User, body: TripIn) -> trip_cases.TripDraft:
    planned: dict[str, Money] = {}
    for name, amount in body.planned.items():
        value = _home(user, amount)
        if value is not None:
            planned[name] = value
    return trip_cases.TripDraft(
        destination=body.destination,
        start=body.start,
        end=body.end,
        currency=body.currency,
        budget=_home(user, body.budget),
        companions=body.companions,
        set_aside=_home(user, body.set_aside),
        planned=planned,
    )


def _today(auth: Auth, web: Runtime) -> date:
    return trip_cases.local_today(auth.user, web.clock())


@router.get("/trips")
async def list_trips(auth: Auth, web: Runtime) -> list[TripOut]:
    today = _today(auth, web)
    return [_trip(t, today) for t in await trip_cases.list_trips(web.uow(), auth.user.id)]


@router.post("/trips", status_code=201)
async def create_trip(body: TripIn, auth: Auth, web: Runtime) -> TripOut:
    trip = await trip_cases.create_trip(
        web.uow(), auth.user, _draft(auth.user, body), now=web.clock()
    )
    return _trip(trip, _today(auth, web))


@router.get("/next")
async def next_trip(auth: Auth, web: Runtime) -> TripDetailOut | None:
    """The trip that's on or coming up, for Home."""
    view = await trip_cases.next_trip(web.uow, web.rates, auth.user, now=web.clock())
    return _detail(view) if view else None


@router.get("/trips/{trip_id}")
async def get_trip(trip_id: str, auth: Auth, web: Runtime) -> TripDetailOut:
    view = await trip_cases.trip_view(
        web.uow, web.rates, auth.user, _uuid(trip_id), now=web.clock()
    )
    return _detail(view)


@router.put("/trips/{trip_id}")
async def update_trip(trip_id: str, body: TripIn, auth: Auth, web: Runtime) -> TripOut:
    trip = await trip_cases.update_trip(
        web.uow(), auth.user, _uuid(trip_id), _draft(auth.user, body), now=web.clock()
    )
    return _trip(trip, _today(auth, web))


@router.delete("/trips/{trip_id}", status_code=204)
async def delete_trip(trip_id: str, auth: Auth, web: Runtime) -> None:
    await trip_cases.delete_trip(web.uow(), auth.user.id, _uuid(trip_id))


@router.post("/trips/{trip_id}/expenses/{transaction_id}", status_code=204)
async def add_expense(trip_id: str, transaction_id: str, auth: Auth, web: Runtime) -> None:
    await trip_cases.add_expense(
        web.uow(),
        auth.user.id,
        _uuid(trip_id),
        _uuid(transaction_id, "transaction"),
        now=web.clock(),
    )


@router.delete("/trips/{trip_id}/expenses/{transaction_id}", status_code=204)
async def remove_expense(trip_id: str, transaction_id: str, auth: Auth, web: Runtime) -> None:
    await trip_cases.remove_expense(
        web.uow(),
        auth.user.id,
        _uuid(trip_id),
        _uuid(transaction_id, "transaction"),
        now=web.clock(),
    )


@router.get("/bookings")
async def loose_bookings(auth: Auth, web: Runtime) -> list[BookingOut]:
    """Bookings from email that aren't on a trip."""
    return [_booking(b) for b in await booking_cases.unattached(web.uow(), auth.user.id)]


class BookingTripIn(Model):
    trip_id: UUID | None


@router.put("/bookings/{booking_id}/trip", status_code=204)
async def set_booking_trip(booking_id: str, body: BookingTripIn, auth: Auth, web: Runtime) -> None:
    await booking_cases.attach(
        web.uow(), auth.user.id, _uuid(booking_id, "booking"), body.trip_id, now=web.clock()
    )


@router.delete("/bookings/{booking_id}", status_code=204)
async def delete_booking(booking_id: str, auth: Auth, web: Runtime) -> None:
    await booking_cases.delete_booking(web.uow(), auth.user.id, _uuid(booking_id, "booking"))


# --- research ---------------------------------------------------------------------------


@router.get("/research/{run_id}")
async def get_research(run_id: str, auth: Auth, web: Runtime) -> dict[str, Any]:
    """A finished trip research: when to go, costs with sources, areas, the budget."""
    found = await research_cases.research_result(web.uow(), auth.user, _uuid(run_id, "research"))
    return found.model_dump(mode="json")


@router.post("/research/{run_id}/trip", status_code=201)
async def research_to_trip(run_id: str, auth: Auth, web: Runtime) -> TripOut:
    trip = await research_cases.make_trip(
        web.uow, auth.user, _uuid(run_id, "research"), now=web.clock()
    )
    return _trip(trip, _today(auth, web))
