"""The Travel department's API: trips, what's been spent on them, money set aside
and settling up. Nothing here books or buys anything."""

import base64
import binascii
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import bookings as booking_cases
from nexus.application import places as place_cases
from nexus.application import travel_research as research_cases
from nexus.application import trips as trip_cases
from nexus.application.places import Places, PlacesError
from nexus.channels.web.api import MoneyOut, money
from nexus.channels.web.investments_api import MAX_IMAGE_CHARS
from nexus.channels.web.security import Auth, Runtime, WebRuntime, limit
from nexus.domain.bookings import Booking
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User
from nexus.domain.money import Money
from nexus.domain.places import Place
from nexus.domain.trips import MAX_COMPANIONS, MAX_DAY_LABEL, MAX_NOTES, MAX_PLANNED, Trip

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
    notes: str | None
    day_labels: dict[date, str]  # a label per day, such as the city


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
        notes=trip.notes,
        day_labels=dict(sorted(trip.day_labels.items())),
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
    kind: str  # flight, hotel, rail, activity (a plan)
    title: str
    provider: str | None
    starts: date
    ends: date | None
    segments: list[SegmentOut]
    hotel: str | None
    address: str | None
    check_in: date | None
    check_out: date | None
    name: str | None  # a plan's
    day: date | None
    at: str | None  # HH:MM
    note: str | None
    reference: str | None  # the booking or confirmation number: the user's own
    booked_via: str | None  # the airline, Agoda, Klook
    category: str | None  # a plan's kind: Food, Sight
    place_id: str | None  # its Google Maps place, for a plan or hotel
    scheduled: bool  # on a day; false for a place to visit without one yet
    cost: MoneyOut | None
    logged: bool  # its cost is in the ledger
    manual: bool  # added by hand, not read from email


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
        name=d.name,
        day=d.day,
        at=d.at.isoformat(timespec="minutes") if d.at else None,
        note=d.note,
        reference=d.reference,
        booked_via=d.booked_via,
        category=d.category,
        place_id=d.place_id,
        scheduled=b.scheduled,
        cost=_m(b.cost),
        logged=b.transaction_id is not None,
        manual=b.email_id is None,
    )


class ReadyOut(Model):
    """What the trip still needs, checked in code."""

    nights_without_stay: list[date]
    has_transport: bool
    has_budget: bool
    done: int
    total: int


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
    ready: ReadyOut
    places: bool = False  # Google Maps places are set up


def _detail(view: trip_cases.TripView, web: WebRuntime | None = None) -> TripDetailOut:
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
        ready=ReadyOut(
            nights_without_stay=view.ready.nights_without_stay,
            has_transport=view.ready.has_transport,
            has_budget=view.ready.has_budget,
            done=view.ready.done,
            total=view.ready.TOTAL,
        ),
        places=web is not None and web.places is not None,
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
    notes: str | None = Field(None, max_length=MAX_NOTES)


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
        notes=body.notes,
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
    return _detail(view, web) if view else None


@router.get("/trips/{trip_id}")
async def get_trip(trip_id: str, auth: Auth, web: Runtime) -> TripDetailOut:
    view = await trip_cases.trip_view(
        web.uow, web.rates, auth.user, _uuid(trip_id), now=web.clock()
    )
    return _detail(view, web)


@router.put("/trips/{trip_id}")
async def update_trip(trip_id: str, body: TripIn, auth: Auth, web: Runtime) -> TripOut:
    trip = await trip_cases.update_trip(
        web.uow(), auth.user, _uuid(trip_id), _draft(auth.user, body), now=web.clock()
    )
    return _trip(trip, _today(auth, web))


class DayLabelIn(Model):
    label: str | None = Field(None, max_length=MAX_DAY_LABEL)


@router.put("/trips/{trip_id}/days/{day}")
async def label_day(trip_id: str, day: date, body: DayLabelIn, auth: Auth, web: Runtime) -> TripOut:
    """Names a day of the trip, such as the city ("Busan"); blank clears it."""
    trip = await trip_cases.set_day_label(
        web.uow(), auth.user, _uuid(trip_id), day, body.label, now=web.clock()
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


class SegmentIn(Model):
    number: str | None = Field(None, max_length=20)
    origin: str | None = Field(None, max_length=80)
    destination: str | None = Field(None, max_length=80)
    departs: str | None = Field(None, max_length=20)  # YYYY-MM-DDTHH:MM, local
    arrives: str | None = Field(None, max_length=20)


class BookingIn(Model):
    """An itinerary entry by hand: a flight or train (its legs), a hotel stay, or a
    plan (a name, a day and maybe a time and place). Cost in any currency."""

    kind: str = Field(pattern="^(flight|hotel|rail|activity)$")
    provider: str | None = Field(None, max_length=80)
    segments: list[SegmentIn] = Field(default_factory=list, max_length=6)
    hotel: str | None = Field(None, max_length=120)
    address: str | None = Field(None, max_length=200)
    check_in: str | None = Field(None, max_length=10)
    check_out: str | None = Field(None, max_length=10)
    name: str | None = Field(None, max_length=120)
    day: str | None = Field(None, max_length=10)
    at: str | None = Field(None, max_length=5)
    note: str | None = Field(None, max_length=300)
    reference: str | None = Field(None, max_length=40)
    booked_via: str | None = Field(None, max_length=80)
    category: str | None = Field(None, max_length=30)
    cost: str | None = Field(None, max_length=32)
    currency: str | None = Field(None, pattern="^[A-Za-z]{3}$")
    # A Google Maps place id; left out of an edit, the entry keeps its place.
    place_id: str | None = Field(None, max_length=512)


def _details(body: BookingIn) -> dict[str, object]:
    found = _fields(body)
    if "place_id" in body.model_fields_set:
        found["place_id"] = body.place_id
    return found


def _fields(body: BookingIn) -> dict[str, object]:
    return {
        "kind": body.kind,
        "provider": body.provider,
        "segments": [
            {
                "number": s.number,
                "from": s.origin,
                "to": s.destination,
                "departs": s.departs,
                "arrives": s.arrives,
            }
            for s in body.segments
        ],
        "hotel": body.hotel,
        "address": body.address,
        "check_in": body.check_in,
        "check_out": body.check_out,
        "name": body.name,
        "day": body.day,
        "at": body.at,
        "note": body.note,
        "reference": body.reference,
        "booked_via": body.booked_via,
        "category": body.category,
    }


def _cost(user: User, body: BookingIn) -> Money | None:
    if body.cost is None or not body.cost.strip():
        return None
    return Money.of(body.cost.replace(",", ""), (body.currency or user.home_currency).upper())


@router.post("/trips/{trip_id}/bookings", status_code=201)
async def add_booking(trip_id: str, body: BookingIn, auth: Auth, web: Runtime) -> BookingOut:
    booking = await booking_cases.add_manual(
        web.uow(), auth.user.id, _uuid(trip_id), _details(body), _cost(auth.user, body),
        now=web.clock(),
    )  # fmt: skip
    return _booking(booking)


@router.put("/bookings/{booking_id}")
async def edit_booking(booking_id: str, body: BookingIn, auth: Auth, web: Runtime) -> BookingOut:
    booking = await booking_cases.edit_booking(
        web.uow(), auth.user.id, _uuid(booking_id, "booking"), _details(body),
        _cost(auth.user, body),
    )  # fmt: skip
    return _booking(booking)


class ScreenshotIn(Model):
    image: str = Field(min_length=1, max_length=MAX_IMAGE_CHARS)  # base64
    mime_type: str = Field(pattern="^image/(png|jpeg|webp)$")
    caption: str | None = Field(None, max_length=300)


class ScreenshotOut(Model):
    added: list[BookingOut]
    repeated: int  # already on the itinerary, not added again
    message: str


@router.post("/trips/{trip_id}/screenshot")
async def read_screenshot(
    trip_id: str, body: ScreenshotIn, auth: Auth, web: Runtime
) -> ScreenshotOut:
    """A screenshot of bookings or plans read onto this trip's itinerary. The image is
    only held for this request."""
    limit(web, auth, "import")
    try:
        image = base64.b64decode(body.image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidInput("that image didn't arrive whole; try again") from exc
    result = await web.service.read_trip_screenshot(
        auth.user.id, image, body.mime_type, body.caption, trip_id=_uuid(trip_id)
    )
    if result is None:  # pragma: no cover - asked, so never None
        raise InvalidInput("I couldn't find any bookings or plans in that screenshot")
    return ScreenshotOut(
        added=[_booking(s.booking) for s in result.saved],
        repeated=result.repeated,
        message=booking_cases.describe_screenshot(result),
    )


# --- Google Maps places ------------------------------------------------------------------


class ReviewOut(Model):
    rating: int | None
    text: str
    author: str | None
    author_url: str | None
    when: str | None


class PlaceOut(Model):
    """A place as Google Maps shows it. Fetched when shown, never stored (but its id)."""

    id: str
    name: str
    address: str | None
    kind: str | None
    rating: Decimal | None
    ratings: int | None
    price: str | None  # Inexpensive, Moderate…
    maps_url: str | None
    website: str | None
    phone: str | None
    summary: str | None
    status: str | None
    hours: list[str]  # the regular week, as Google words it
    reviews: list[ReviewOut]


def _place(p: Place) -> PlaceOut:
    return PlaceOut(
        id=p.id,
        name=p.name,
        address=p.address,
        kind=p.kind,
        rating=p.rating,
        ratings=p.ratings,
        price=p.price,
        maps_url=p.maps_url,
        website=p.website,
        phone=p.phone,
        summary=p.summary,
        status=p.status,
        hours=list(p.hours),
        reviews=[
            ReviewOut(
                rating=r.rating, text=r.text, author=r.author, author_url=r.author_url, when=r.when
            )
            for r in p.reviews
        ],
    )


def _places(web: WebRuntime) -> Places:
    if web.places is None:
        raise NotFound("Google Maps places aren't set up")
    return web.places


_SILENT = "Google Maps isn't answering right now; try again in a bit."


@router.get("/places/search")
async def search_places(
    auth: Auth,
    web: Runtime,
    q: str = Query(min_length=1, max_length=120),
    trip_id: str | None = None,
) -> list[PlaceOut]:
    """Places on Google Maps, narrowed to the trip's destination when one is given."""
    places = _places(web)
    destination = None
    if trip_id:
        trip = await trip_cases.get_trip(web.uow(), auth.user.id, _uuid(trip_id))
        destination = trip.destination
    try:
        found = await places.search(auth.user.id, place_cases.query_for(q, destination))
    except PlacesError as exc:
        raise HTTPException(status_code=502, detail=_SILENT) from exc
    return [_place(p) for p in found]


@router.get("/places/{place_id}")
async def get_place(place_id: str, auth: Auth, web: Runtime) -> PlaceOut:
    """One place with its regular hours and a few reviews."""
    try:
        return _place(await _places(web).details(auth.user.id, place_id))
    except PlacesError as exc:
        raise HTTPException(status_code=502, detail=_SILENT) from exc


class LinkedPlaceOut(Model):
    booking_id: UUID
    place: PlaceOut
    warning: str | None  # usually closed that day, or not open at the planned time


@router.get("/trips/{trip_id}/places")
async def trip_places(trip_id: str, auth: Auth, web: Runtime) -> list[LinkedPlaceOut]:
    """Google Maps details for the itinerary entries linked to a place."""
    found = await place_cases.trip_places(web.uow(), _places(web), auth.user.id, _uuid(trip_id))
    return [
        LinkedPlaceOut(booking_id=f.booking_id, place=_place(f.place), warning=f.warning)
        for f in found
    ]


class PlaceLinkIn(Model):
    place_id: str | None = Field(None, max_length=512)  # None unlinks


@router.put("/bookings/{booking_id}/place")
async def link_place(booking_id: str, body: PlaceLinkIn, auth: Auth, web: Runtime) -> BookingOut:
    booking = await place_cases.link_place(
        web.uow(), auth.user.id, _uuid(booking_id, "booking"), body.place_id
    )
    return _booking(booking)
