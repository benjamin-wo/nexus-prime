"""The Travel department's API: trips, what's been spent on them, money set aside
and settling up. Nothing here books or buys anything."""

import base64
import binascii
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import bookings as booking_cases
from nexus.application import destination_photos as photo_cases
from nexus.application import places as place_cases
from nexus.application import routes as route_cases
from nexus.application import travel_research as research_cases
from nexus.application import trip_split as split_cases
from nexus.application import trips as trip_cases
from nexus.application.places import Places, PlacesError
from nexus.application.routes import Routes
from nexus.application.weather import WeatherError
from nexus.channels.web.api import MoneyOut, money
from nexus.channels.web.investments_api import MAX_IMAGE_CHARS
from nexus.channels.web.security import Auth, Runtime, WebRuntime, limit
from nexus.domain import itinerary
from nexus.domain.bookings import Booking
from nexus.domain.currencies import currency_of
from nexus.domain.destination_photos import DestinationPhoto
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.itinerary import NoteKind
from nexus.domain.ledger import User
from nexus.domain.money import Money
from nexus.domain.packing import MAX_ITEM, MAX_ITEMS, PackItem
from nexus.domain.places import Place
from nexus.domain.routes import Mode
from nexus.domain.settle import Debt as SettleDebt
from nexus.domain.settle import PaidByOther, PersonBalance
from nexus.domain.trips import (
    MAX_COMPANIONS,
    MAX_DAY_LABEL,
    MAX_NOTES,
    MAX_PLANNED,
    MAX_STOP_NAME,
    MAX_STOPS,
    GettingAround,
    Stop,
    Trip,
)
from nexus.domain.weather import YEARS, TripWeather, describe
from nexus.settings import Settings

log = logging.getLogger(__name__)

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


class PhotoOut(Model):
    url: str  # served by this API: the page's rules allow no other image host
    credit: str  # "Photo: <author>, <licence>, via Wikimedia Commons"
    page: str | None  # the photo's page on Commons
    licence_url: str | None
    spot: str | None  # what it shows ("Kiyomizu-dera")


def _photo(photo: DestinationPhoto | None) -> PhotoOut | None:
    if photo is None or photo.credit is None:
        return None
    return PhotoOut(
        url=f"/api/travel/photos/{photo.id}",
        credit=photo.credit,
        page=photo.page,
        licence_url=photo.licence_url,
        spot=photo.spot,
    )


class PackItemOut(Model):
    text: str
    done: bool


class StopOut(Model):
    name: str
    start: date  # the stop's first day
    end: date  # and last; the next stop may start the same day (the travel day)


def _stops(stops: tuple[Stop, ...]) -> list[StopOut]:
    return [StopOut(name=s.name, start=s.start, end=s.end) for s in stops]


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
    photo: PhotoOut | None = None  # a famous view of where it goes, once found
    photo_off: bool = False  # the user chose to show no photo
    packing: list[PackItemOut] = Field(default_factory=list)
    getting_around: GettingAround = GettingAround.TRANSIT  # public transport or a hire car
    stops: list[StopOut] = Field(default_factory=list)  # as set by the user; empty: suggested
    # Whether its costs are split evenly with the travellers (offered once there are any).
    split_evenly: bool = True


def _trip(trip: Trip, today: date, photos: dict[UUID, DestinationPhoto] | None = None) -> TripOut:
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
        photo=(
            _photo((photos or {}).get(trip.photo_id))
            if trip.photo_id and not trip.photo_off
            else None
        ),
        photo_off=trip.photo_off,
        packing=[PackItemOut(text=i.text, done=i.done) for i in trip.packing],
        getting_around=trip.getting_around,
        stops=_stops(trip.stops),
        split_evenly=trip.split_evenly,
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
    ends_at: str | None = None  # a plan's end, HH:MM
    link: str | None = None  # a booking page or menu (public https)
    list_name: str | None = None  # a place to visit's list: "Eat", "Rainy day"
    order: int | None = None  # a plan's place in its day; None until the day is rearranged
    scheduled: bool  # on a day; false for a place to visit without one yet
    cost: MoneyOut | None
    lat: float | None = None  # the user's own pin, on a plan with no Google Maps place
    lng: float | None = None
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
        ends_at=d.ends_at.isoformat(timespec="minutes") if d.ends_at else None,
        link=d.link,
        list_name=d.list_name,
        order=d.order,
        lat=d.lat,
        lng=d.lng,
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


class DayNoteOut(Model):
    kind: NoteKind  # clash, order or free
    text: str
    ids: list[UUID]  # the entries it's about
    start: str | None = None  # free time: from, HH:MM
    end: str | None = None


class DayPlanOut(Model):
    """A day of the itinerary: its entries in order, and what to watch out for."""

    day: date
    order: list[UUID]
    notes: list[DayNoteOut]


def _days(bookings: list[Booking], trip: Trip) -> list[DayPlanOut]:
    out = []
    for day in itinerary.days_of(bookings):
        arranged = itinerary.on_day(bookings, day)
        notes = [
            DayNoteOut(
                kind=n.kind,
                text=n.text,
                ids=list(n.ids),
                start=n.start.isoformat(timespec="minutes") if n.start else None,
                end=n.end.isoformat(timespec="minutes") if n.end else None,
            )
            for n in itinerary.day_notes(arranged, day, in_trip=trip.start <= day <= trip.end)
        ]
        out.append(DayPlanOut(day=day, order=[b.id for b in arranged], notes=notes))
    return out


class ToSplitOut(Model):
    """A cost on the trip that nobody owes a share of yet."""

    transaction_id: UUID
    day: date
    counterparty: str | None
    category: str | None
    amount: MoneyOut  # the whole bill
    home: MoneyOut | None


class PaidByOtherOut(Model):
    id: UUID
    person: str  # who paid
    amount: MoneyOut  # the whole bill
    note: str | None
    paid_on: date
    split_with: list[str]  # the other travellers sharing it, besides the payer and the user
    my_share: MoneyOut  # the user's equal part, in the currency it was paid in
    settled: bool
    settled_at: datetime | None


def _paid(p: PaidByOther) -> PaidByOtherOut:
    return PaidByOtherOut(
        id=p.id,
        person=p.person,
        amount=money(p.amount),
        note=p.note,
        paid_on=p.paid_on,
        split_with=list(p.split_with),
        my_share=money(p.my_share),
        settled=p.settled,
        settled_at=p.settled_at,
    )


class DebtOut(Model):
    kind: str  # "iou": their share of a bill the user paid; "payment": the user's share of theirs
    id: UUID  # the split (iou) or the payment
    label: str | None  # what it was for
    amount: MoneyOut
    home: MoneyOut | None
    on: date


class BalanceOut(Model):
    person: str
    # "owes_you", "you_owe" or "even"; None when a missing exchange rate leaves the net
    # unknown and the currencies differ.
    direction: str | None
    net: MoneyOut | None  # home currency, positive when they owe the user; None: no rate
    net_by_currency: list[MoneyOut]  # the same, signed, per currency
    owes_you: list[DebtOut]
    you_owe: list[DebtOut]


def _debt(d: SettleDebt) -> DebtOut:
    return DebtOut(
        kind=d.kind.value,
        id=d.ref,
        label=d.label,
        amount=money(d.amount),
        home=_m(d.home),
        on=d.on,
    )


def _balance(b: PersonBalance) -> BalanceOut:
    return BalanceOut(
        person=b.name,
        direction=b.direction.value if b.direction else None,
        net=_m(b.net_home),
        net_by_currency=[money(m) for m in b.net_by_currency],
        owes_you=[_debt(d) for d in b.owes_you],
        you_owe=[_debt(d) for d in b.you_owe],
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
    ready: ReadyOut
    # Each day with entries, in itinerary order, with its clashes and free time.
    days: list[DayPlanOut] = Field(default_factory=list)
    # Places to visit (no day yet) in the user's order.
    places_order: list[UUID] = Field(default_factory=list)
    places: bool = False  # Google Maps places are set up
    routes: bool = False  # travel times between stops are set up
    # The browser key for Google's map; None = no map. Only for signed-in users, and
    # limited in Google Cloud to this site and the Maps JavaScript API.
    map_key: str | None = None
    ideas: bool = False  # quick ideas from the web are set up
    # The stops the hotels suggest (named by each hotel's area where Google Maps knows
    # it): what the page shows until the user sets their own.
    suggested_stops: list[StopOut] = Field(default_factory=list)
    # Costs not split yet while the trip splits evenly with other travellers (newest
    # first); empty when the setting is off or nobody else is going.
    to_split: list[ToSplitOut] = Field(default_factory=list)
    just_mine: list[UUID] = Field(default_factory=list)  # expenses marked "just mine"
    paid_by_others: list[PaidByOtherOut] = Field(default_factory=list)  # oldest first
    # Where the user stands with each person (open items only), A to Z.
    balances: list[BalanceOut] = Field(default_factory=list)


def map_key(settings: Settings) -> str | None:
    """The browser key for the trip map, or None. Never the server's Places key: the
    page shows the key to anyone using it, and the server's key can't be limited to
    this site (its calls don't come from a browser), so a copy would work anywhere."""
    browser, server = settings.google_maps_browser_key, settings.google_places_api_key
    if not browser or (server is not None and browser == server.get_secret_value()):
        return None
    return browser


def _detail(
    view: trip_cases.TripView,
    web: WebRuntime | None = None,
    photos: dict[UUID, DestinationPhoto] | None = None,
    suggested: tuple[Stop, ...] = (),
) -> TripDetailOut:
    s, a = view.spending, view.saving
    return TripDetailOut(
        trip=_trip(view.trip, view.today, photos),
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
        days=_days(view.bookings, view.trip),
        places_order=[b.id for b in itinerary.places_to_visit(view.bookings)],
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
        routes=web is not None and web.routes is not None and web.places is not None,
        map_key=map_key(web.settings) if web and web.places else None,
        ideas=web is not None and web.ideas is not None,
        suggested_stops=_stops(suggested),
        to_split=[
            ToSplitOut(
                transaction_id=i.transaction_id,
                day=i.day,
                counterparty=i.counterparty,
                category=i.category,
                amount=money(i.amount),
                home=_m(i.home),
            )
            for i in view.to_split
        ],
        just_mine=list(view.just_mine),
        paid_by_others=[_paid(p) for p in view.paid_by_others],
        balances=[_balance(b) for b in view.balances],
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
    trips = await trip_cases.list_trips(web.uow(), auth.user.id)
    photos = await photo_cases.photos_of(web.uow(), trips)
    return [_trip(t, today, photos) for t in trips]


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
    if view is None:
        return None
    return await _detailed(view, web)


async def _detailed(view: trip_cases.TripView, web: WebRuntime) -> TripDetailOut:
    suggested = await place_cases.suggested_stops(
        web.places, view.trip.user_id, view.trip, view.bookings
    )
    photos = await photo_cases.photos_of(web.uow(), [view.trip])
    return _detail(view, web, photos, suggested)


@router.get("/trips/{trip_id}")
async def get_trip(trip_id: str, auth: Auth, web: Runtime) -> TripDetailOut:
    view = await trip_cases.trip_view(
        web.uow, web.rates, auth.user, _uuid(trip_id), now=web.clock()
    )
    return await _detailed(view, web)


@router.get("/photos/{photo_id}")
async def photo(photo_id: str, auth: Auth, web: Runtime) -> Response:
    """A trip header photo. Photos are shared by every trip to a place and never
    change, so the browser keeps them."""
    found = await photo_cases.photo_file(web.uow(), _uuid(photo_id, "photo"))
    if found is None:
        raise NotFound("no photo with that id")
    data, mime = found
    return Response(
        data,
        media_type=mime,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


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


class StopIn(Model):
    name: str = Field(min_length=1, max_length=MAX_STOP_NAME)
    start: date
    end: date


class StopsIn(Model):
    stops: list[StopIn] = Field(max_length=MAX_STOPS)  # empty: back to the suggested ones


@router.put("/trips/{trip_id}/stops")
async def set_stops(trip_id: str, body: StopsIn, auth: Auth, web: Runtime) -> TripOut:
    """Sets the trip's stops (a city or area per stretch of days, in date order, inside
    the trip, only a travel day shared); none goes back to the ones the hotels suggest."""
    trip = await trip_cases.set_stops(
        web.uow(),
        auth.user,
        _uuid(trip_id),
        [Stop(s.name, s.start, s.end) for s in body.stops],
        now=web.clock(),
    )
    return _trip(trip, _today(auth, web))


class GettingAroundIn(Model):
    by: GettingAround  # transit or car


@router.put("/trips/{trip_id}/getting-around")
async def getting_around(trip_id: str, body: GettingAroundIn, auth: Auth, web: Runtime) -> TripOut:
    """Public transport or a hire car: how longer hops go unless one was picked."""
    trip = await trip_cases.set_getting_around(
        web.uow(), auth.user, _uuid(trip_id), body.by, now=web.clock()
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


# --- splitting costs, what others paid, and settling up -----------------------------------


class SplitEvenlyIn(Model):
    on: bool


@router.put("/trips/{trip_id}/split-evenly")
async def split_evenly(trip_id: str, body: SplitEvenlyIn, auth: Auth, web: Runtime) -> TripOut:
    """Whether the trip offers to split its costs evenly with the people going. Changes
    nothing in the ledger."""
    trip = await split_cases.set_split_evenly(web.uow(), auth.user, _uuid(trip_id), body.on)
    return _trip(trip, _today(auth, web))


class SplitIn(Model):
    # Exactly one of the two: these expenses, or every cost not split yet.
    transaction_ids: list[UUID] | None = Field(
        None, min_length=1, max_length=trip_cases.MAX_EXPENSES
    )
    all: bool = False


class SplitDoneOut(Model):
    transaction_id: UUID
    counterparty: str | None
    amount: MoneyOut
    own_share: MoneyOut  # the user's equal part of the bill


class SplitSkippedOut(Model):
    transaction_id: UUID
    reason: str


class SplitOut(Model):
    with_people: list[str]  # everyone else on the trip, who the costs were split with
    done: list[SplitDoneOut]
    skipped: list[SplitSkippedOut]  # split meanwhile, not on the trip, or can't be split


@router.post("/trips/{trip_id}/split")
async def split_costs(trip_id: str, body: SplitIn, auth: Auth, web: Runtime) -> SplitOut:
    """Splits the trip's costs evenly with everyone else on it (each person's IOU, the
    user's share included), as ``split_bill`` does. 422 without other travellers, or
    unless exactly one of ``transaction_ids`` and ``all: true`` is given. Expenses split
    meanwhile are skipped and listed, never changed."""
    if (body.transaction_ids is None) == (not body.all):
        raise InvalidInput("give transaction_ids, or all: true, but not both")
    outcome = await split_cases.split_trip_costs(
        web.uow,
        web.rates,
        auth.user,
        _uuid(trip_id),
        None if body.all else body.transaction_ids,
        now=web.clock(),
    )
    return SplitOut(
        with_people=outcome.with_people,
        done=[
            SplitDoneOut(
                transaction_id=d.transaction_id,
                counterparty=d.counterparty,
                amount=money(d.amount),
                own_share=money(d.own_share),
            )
            for d in outcome.done
        ],
        skipped=[
            SplitSkippedOut(transaction_id=k.transaction_id, reason=k.reason)
            for k in outcome.skipped
        ],
    )


class KeepMineIn(Model):
    transaction_ids: list[UUID] = Field(min_length=1, max_length=trip_cases.MAX_EXPENSES)
    keep: bool = True  # false offers them for splitting again


class KeepMineOut(Model):
    just_mine: list[UUID]


@router.post("/trips/{trip_id}/keep-mine")
async def keep_mine(trip_id: str, body: KeepMineIn, auth: Auth, web: Runtime) -> KeepMineOut:
    """Marks expenses on the trip "just mine", so they aren't offered for splitting
    again (``keep: false`` offers them again). 404 for one that isn't an expense on
    this trip."""
    trip = await split_cases.keep_mine(
        web.uow(), auth.user, _uuid(trip_id), body.transaction_ids, keep=body.keep
    )
    return KeepMineOut(just_mine=list(trip.not_split))


class PaidByOtherIn(Model):
    person: str = Field(min_length=1, max_length=100)  # a traveller on the trip
    amount: str = Field(max_length=32)  # the whole bill
    currency: str | None = Field(None, pattern="^[A-Za-z]{3}$")  # default: the home currency
    note: str | None = Field(None, max_length=100)  # what it was for
    paid_on: date | None = None  # default: today
    # The other travellers sharing it, besides the payer and the user; left out: everyone.
    split_with: list[str] | None = Field(None, max_length=MAX_COMPANIONS)


def _payment_args(auth: Auth, web: WebRuntime, body: PaidByOtherIn) -> dict[str, Any]:
    return {
        "person": body.person,
        "amount": Money.of(
            body.amount.replace(",", ""), (body.currency or auth.user.home_currency).upper()
        ),
        "note": body.note,
        "paid_on": body.paid_on or _today(auth, web),
        "split_with": body.split_with,
    }


@router.post("/trips/{trip_id}/paid-by-others", status_code=201)
async def add_paid_by_other(
    trip_id: str, body: PaidByOtherIn, auth: Auth, web: Runtime
) -> PaidByOtherOut:
    """Notes that a fellow traveller paid for something and the user shares it; the
    user's equal share is what they owe that person. Nothing goes in the ledger until
    they settle up. 422 for someone who isn't on the trip."""
    payment = await split_cases.add_paid_by_other(
        web.uow(), auth.user, _uuid(trip_id), now=web.clock(), **_payment_args(auth, web, body)
    )
    return _paid(payment)


@router.put("/trips/{trip_id}/paid-by-others/{payment_id}")
async def edit_paid_by_other(
    trip_id: str, payment_id: str, body: PaidByOtherIn, auth: Auth, web: Runtime
) -> PaidByOtherOut:
    """Changes a payment that isn't settled yet (409 once it is)."""
    payment = await split_cases.edit_paid_by_other(
        web.uow(),
        auth.user,
        _uuid(trip_id),
        _uuid(payment_id, "payment"),
        **_payment_args(auth, web, body),
    )
    return _paid(payment)


@router.delete("/trips/{trip_id}/paid-by-others/{payment_id}", status_code=204)
async def delete_paid_by_other(trip_id: str, payment_id: str, auth: Auth, web: Runtime) -> None:
    await split_cases.delete_paid_by_other(
        web.uow(), auth.user, _uuid(trip_id), _uuid(payment_id, "payment")
    )


class SettleIn(Model):
    person: str = Field(min_length=1, max_length=100)
    # Also record the user's share of what the person paid as an expense. What they owe
    # the user is always recorded as money in when it is marked paid back.
    log: bool = True


class SettleOut(Model):
    person: str
    ious_repaid: int
    payments_settled: int
    income: list[MoneyOut]  # money in recorded for the shares they paid back
    expenses: list[MoneyOut]  # money out recorded for the user's share of what they paid


@router.post("/trips/{trip_id}/settle")
async def settle_person(trip_id: str, body: SettleIn, auth: Auth, web: Runtime) -> SettleOut:
    """Records that the user and one person are square for this trip: their open IOUs on
    the trip are marked paid back (recording the money in) and what they paid for the
    trip is settled, with ``log`` the user's share of it recorded as an expense. Moves
    no money. 422 when nothing is open with that person; safe to repeat."""
    done = await split_cases.settle_person(
        web.uow,
        web.rates,
        auth.user,
        _uuid(trip_id),
        body.person,
        log=body.log,
        now=web.clock(),
    )
    return SettleOut(
        person=done.person,
        ious_repaid=done.ious_repaid,
        payments_settled=done.payments_settled,
        income=[money(t.amount) for t in done.income],
        expenses=[money(t.amount) for t in done.expenses],
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


class ResearchIdeasIn(Model):
    trip_id: UUID
    # Names of the research's areas ("Shinjuku"); each one's things to do become ideas.
    areas: list[str] = Field(min_length=1, max_length=research_cases.MAX_IDEA_AREAS)


class ResearchIdeasOut(Model):
    added: int  # ideas saved on the trip, each under a list named after its area
    skipped: int  # already on the trip
    stop_suggestion: str | None  # the research's place when it isn't any of the trip's stops


@router.post("/research/{run_id}/ideas")
async def research_ideas(
    run_id: str, body: ResearchIdeasIn, auth: Auth, web: Runtime
) -> ResearchIdeasOut:
    """Saves the chosen research areas' things to do as ideas (places to visit) on one
    of the user's upcoming or ongoing trips. 404 for a research or trip that isn't theirs,
    422 for a finished trip, an unknown area or a full trip. Safe to repeat: what's already
    there is skipped."""
    found = await research_cases.ideas_from_areas(
        web.uow,
        web.places,
        auth.user,
        _uuid(run_id, "research"),
        body.trip_id,
        body.areas,
        now=web.clock(),
    )
    return ResearchIdeasOut(
        added=found.added, skipped=found.skipped, stop_suggestion=found.stop_suggestion
    )


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
    # Each of these, left out of an edit, keeps what the entry had: a Google Maps place
    # id, a plan's end time (HH:MM), a link (a public https address) and a list name.
    place_id: str | None = Field(None, max_length=512)
    ends_at: str | None = Field(None, max_length=5)
    link: str | None = Field(None, max_length=500)
    list_name: str | None = Field(None, max_length=30)
    # The user's own pin on the map, for a plan with no Google Maps place (kept if left
    # out of an edit; dropped once a place is linked).
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)


_KEPT_IF_LEFT_OUT = ("place_id", "ends_at", "link", "list_name", "lat", "lng")


def _details(body: BookingIn) -> dict[str, object]:
    found = _fields(body)
    for key in _KEPT_IF_LEFT_OUT:
        if key in body.model_fields_set:
            found[key] = getattr(body, key)
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


class MoveIn(Model):
    day: date | None  # None: back to places to visit
    after: UUID | None = None  # the entry it goes right after there; None: first


@router.put("/bookings/{booking_id}/move")
async def move_booking(booking_id: str, body: MoveIn, auth: Auth, web: Runtime) -> BookingOut:
    """A plan or place to visit moved to a day (or back to places to visit), right
    after another entry there. Flights, trains and hotel nights stay put."""
    moved = await booking_cases.move_entry(
        web.uow(), auth.user.id, _uuid(booking_id, "booking"), body.day, body.after
    )
    return _booking(moved)


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
    photo_url: str | None = None  # a thumbnail served by this API
    photo_author: str | None = None  # who took it, credited where it's shown
    photo_author_url: str | None = None
    lat: float | None = None  # where it is, for the trip map (fetched, never stored)
    lng: float | None = None
    area: str | None = None  # its neighbourhood ("Gion"), fetched with it, never stored
    city: str | None = None  # its city ("Kyoto"), likewise


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
        photo_url=f"/api/travel/places/{p.id}/photo" if p.photo else None,
        photo_author=p.photo.author if p.photo else None,
        photo_author_url=p.photo.author_url if p.photo else None,
        lat=p.location.lat if p.location else None,
        lng=p.location.lng if p.location else None,
        area=p.area,
        city=p.city,
    )


def _places(web: WebRuntime) -> Places:
    if web.places is None:
        raise NotFound("Google Maps places aren't set up")
    return web.places


_SILENT = "Google Maps isn't answering right now; try again in a bit."


async def _scope(
    auth: Auth,
    web: WebRuntime,
    trip_id: str | None,
    stop: str | None,
    day: date | None,
) -> place_cases.SearchScope | None:
    """Where a search looks, for the trip it's about; None without a trip."""
    if not trip_id:
        if stop or day:
            raise InvalidInput("a stop or a day needs a trip_id")
        return None
    _, scope = await place_cases.search_scope(
        web.uow(), web.places, auth.user.id, _uuid(trip_id), stop=stop, day=day
    )
    return scope


@router.get("/places/search")
async def search_places(
    auth: Auth,
    web: Runtime,
    q: str = Query(min_length=1, max_length=120),
    trip_id: str | None = None,
    stop: str | None = Query(None, max_length=MAX_STOP_NAME),
    day: date | None = None,
) -> list[PlaceOut]:
    """Places on Google Maps, narrowed to the trip's destination when a trip is given.
    With ``stop`` (one of the trip's stops) the search is in that stop instead; with
    ``day`` (inside the trip) it also leans towards the places planned that day. Both
    need ``trip_id``: 422 without it, for a stop that isn't the trip's or a day outside
    it."""
    places = _places(web)
    scope = await _scope(auth, web, trip_id, stop, day)
    try:
        found = await places.search(
            auth.user.id,
            place_cases.query_for(q, scope.place if scope else None),
            scope.near if scope else None,
        )
    except PlacesError as exc:
        raise HTTPException(status_code=502, detail=_SILENT) from exc
    return [_place(p) for p in found]


class IdeaSourceOut(Model):
    url: str
    title: str


class IdeaOut(Model):
    name: str
    area: str | None
    kind: str | None  # Food, Sight, Shopping, Nature, Nightlife, Museum or Activity
    why: str  # from the source, in its words
    source: IdeaSourceOut
    place: PlaceOut | None  # its Google Maps match, when there is one


class IdeasOut(Model):
    query: str
    destination: str
    ideas: list[IdeaOut]


@router.get("/trips/{trip_id}/ideas")
async def trip_ideas(
    trip_id: str,
    auth: Auth,
    web: Runtime,
    q: str = Query(min_length=1, max_length=120),
    stop: str | None = Query(None, max_length=MAX_STOP_NAME),
    day: date | None = None,
) -> IdeasOut:
    """Ideas for the trip from travel guides and articles: named places, each with the
    page it came from and its Google Maps match. Nothing is saved. With ``stop`` or
    ``day`` they are for that stop (or the area of that day's plans, in its stop)
    instead of the whole trip; the same 422s as the place search."""
    if web.ideas is None:
        raise NotFound("quick ideas aren't set up")
    _, scope = await place_cases.search_scope(
        web.uow(), web.places, auth.user.id, _uuid(trip_id), stop=stop, day=day
    )
    found = await web.ideas.find(auth.user.id, scope.place, q)
    return IdeasOut(
        query=found.query,
        destination=found.destination,
        ideas=[
            IdeaOut(
                name=i.name,
                area=i.area,
                kind=i.kind,
                why=i.why,
                source=IdeaSourceOut(url=i.source.url, title=i.source.title),
                place=_place(i.place) if i.place else None,
            )
            for i in found.ideas
        ],
    )


@router.get("/places/{place_id}")
async def get_place(place_id: str, auth: Auth, web: Runtime) -> PlaceOut:
    """One place with its regular hours and a few reviews."""
    try:
        return _place(await _places(web).details(auth.user.id, place_id))
    except PlacesError as exc:
        raise HTTPException(status_code=502, detail=_SILENT) from exc


@router.get("/places/{place_id}/photo")
async def place_photo(place_id: str, auth: Auth, web: Runtime) -> Response:
    """A place's thumbnail from Google Maps, fetched for the page (never stored)."""
    try:
        data, mime, _ = await _places(web).photo(auth.user.id, place_id)
    except PlacesError as exc:
        raise HTTPException(status_code=502, detail=_SILENT) from exc
    return Response(
        data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=1800", "X-Content-Type-Options": "nosniff"},
    )


class StationStopOut(Model):
    day: date
    side: str  # "from": left from that day; "to": landed at that day


class LinkedPlaceOut(Model):
    booking_id: UUID
    place: PlaceOut
    warning: str | None  # usually closed that day, or not open at the planned time
    # For a flight's or train's airport or station: its name, and when it's used.
    station: str | None = None
    stops: list[StationStopOut] = Field(default_factory=list)


@router.get("/trips/{trip_id}/places")
async def trip_places(trip_id: str, auth: Auth, web: Runtime) -> list[LinkedPlaceOut]:
    """Google Maps details for the itinerary entries linked to a place."""
    found = await place_cases.trip_places(web.uow(), _places(web), auth.user.id, _uuid(trip_id))
    return [
        LinkedPlaceOut(
            booking_id=f.booking_id,
            place=_place(f.place),
            warning=f.warning,
            station=f.station,
            stops=[StationStopOut(day=d, side=side) for d, side in f.stops],
        )
        for f in found
    ]


class HopOut(Model):
    """Getting from one of a day's stops to the next."""

    start_id: UUID  # the itinerary entries at either end
    end_id: UUID
    start: str
    end: str
    mode: Mode  # walk, transit or drive
    minutes: int | None  # None: Google found no way to get there like that
    metres: int | None
    tight: bool  # takes longer than the time between the two plans
    directions: str  # Google Maps directions
    beside_airport: bool  # between an airport and a place right by it: not shown or timed


def _hop(h: route_cases.HopTime) -> HopOut:
    return HopOut(
        start_id=h.hop.start.booking_id,
        end_id=h.hop.end.booking_id,
        start=h.hop.start.title,
        end=h.hop.end.title,
        mode=h.mode,
        minutes=h.minutes,
        metres=h.metres,
        tight=h.tight,
        directions=h.directions,
        beside_airport=h.beside_airport,
    )


def _routes(web: WebRuntime) -> tuple[Places, Routes]:
    if web.places is None or web.routes is None:
        raise NotFound("travel times aren't set up")
    return web.places, web.routes


@router.get("/trips/{trip_id}/days/{day}/hops")
async def day_hops(trip_id: str, day: date, auth: Auth, web: Runtime) -> list[HopOut]:
    """How long it takes between each of the day's stops: the way picked for a hop,
    else the usual way for the distance (walking when it's short, else public
    transport or the trip's hire car). Airports and stations are looked up once."""
    places, routes = _routes(web)
    found = await route_cases.hop_times(web.uow, places, routes, auth.user.id, _uuid(trip_id), day)
    return [_hop(h) for h in found]


@router.get("/trips/{trip_id}/days/{day}/hops/{start_id}/{end_id}")
async def day_hop(
    trip_id: str, day: date, start_id: str, end_id: str, mode: Mode, auth: Auth, web: Runtime
) -> HopOut:
    """One hop of the day, the way the user picked; kept for next time."""
    _, routes = _routes(web)
    try:
        found = await route_cases.hop_time(
            web.uow,
            routes,
            auth.user.id,
            _uuid(trip_id),
            day,
            _uuid(start_id, "booking"),
            _uuid(end_id, "booking"),
            mode,
        )
    except route_cases.RoutesError as exc:
        raise HTTPException(status_code=502, detail=_SILENT) from exc
    return _hop(found)


class PlaceLinkIn(Model):
    place_id: str | None = Field(None, max_length=512)  # None unlinks


@router.put("/bookings/{booking_id}/place")
async def link_place(booking_id: str, body: PlaceLinkIn, auth: Auth, web: Runtime) -> BookingOut:
    booking = await place_cases.link_place(
        web.uow(), auth.user.id, _uuid(booking_id, "booking"), body.place_id
    )
    return _booking(booking)


# --- cover photo, packing list and weather ------------------------------------------------


async def _with_photo(web: WebRuntime, trip: Trip, today: date) -> TripOut:
    return _trip(trip, today, await photo_cases.photos_of(web.uow(), [trip]))


class PhotoChoiceIn(Model):
    choice: trip_cases.PhotoChoice


@router.post("/trips/{trip_id}/photo")
async def choose_photo(trip_id: str, body: PhotoChoiceIn, auth: Auth, web: Runtime) -> TripOut:
    """Another photo of the place, no photo, or photos again."""
    trip = await trip_cases.choose_photo(
        web.uow(), auth.user, _uuid(trip_id), body.choice, now=web.clock()
    )
    return await _with_photo(web, trip, _today(auth, web))


class PackItemIn(Model):
    text: str = Field(max_length=MAX_ITEM)
    done: bool = False


class PackingIn(Model):
    items: list[PackItemIn] = Field(max_length=MAX_ITEMS)


@router.put("/trips/{trip_id}/packing")
async def set_packing(trip_id: str, body: PackingIn, auth: Auth, web: Runtime) -> TripOut:
    """The whole packing list, ticks included."""
    trip = await trip_cases.set_packing(
        web.uow(),
        auth.user,
        _uuid(trip_id),
        [PackItem(i.text, i.done) for i in body.items],
        now=web.clock(),
    )
    return await _with_photo(web, trip, _today(auth, web))


async def _weather(web: WebRuntime, trip: Trip, today: date) -> TripWeather | None:
    if web.weather is None:
        return None
    try:
        return await web.weather.for_trip(trip, today)
    except WeatherError:
        log.info("weather unavailable", exc_info=True)
        return None


class CurrencyOut(Model):
    currency: str | None
    country: str | None


@router.get("/currency")
async def currency_for(auth: Auth, web: Runtime, place: str = "") -> CurrencyOut:
    """The currency spent where a trip goes ("Tokyo" is JPY), so a new trip needn't ask.
    Both null when the place isn't found, or its country isn't one Nexus knows."""
    del auth  # signed in only; nothing of the user's is read
    if web.weather is None or not place.strip():
        return CurrencyOut(currency=None, country=None)
    try:
        spot = await web.weather.spot(place[:80])
    except WeatherError:
        log.info("place lookup unavailable", exc_info=True)
        return CurrencyOut(currency=None, country=None)
    if spot is None:
        return CurrencyOut(currency=None, country=None)
    return CurrencyOut(currency=currency_of(spot.country_code), country=spot.country)


@router.post("/trips/{trip_id}/packing/suggest")
async def suggest_packing(trip_id: str, auth: Auth, web: Runtime) -> TripOut:
    """Adds what a trip like this usually needs, from the weather when it's known."""
    today = _today(auth, web)
    current = await trip_cases.get_trip(web.uow(), auth.user.id, _uuid(trip_id))
    weather = await _weather(web, current, today)
    trip = await trip_cases.suggest_packing(
        web.uow(),
        auth.user,
        current.id,
        latitude=weather.place.latitude if weather else None,
        outlook=weather.outlook() if weather else None,
        now=web.clock(),
    )
    return await _with_photo(web, trip, today)


class WeatherDayOut(Model):
    day: date
    high: float | None
    low: float | None
    rain: int | None  # chance of rain, %
    summary: str | None  # "Light rain"
    code: int | None


class WeatherOut(Model):
    place: str  # "Tokyo, Japan"
    kind: str  # forecast, or typical (the same dates in recent years)
    years: int  # how many years "typical" averages
    days: list[WeatherDayOut]


@router.get("/trips/{trip_id}/weather")
async def trip_weather(trip_id: str, auth: Auth, web: Runtime) -> WeatherOut | None:
    """The forecast once it reaches the trip, else the same dates in recent years.
    None when the trip is over or the weather isn't available."""
    trip = await trip_cases.get_trip(web.uow(), auth.user.id, _uuid(trip_id))
    weather = await _weather(web, trip, _today(auth, web))
    if weather is None or not weather.days:
        return None
    where = weather.place
    return WeatherOut(
        place=f"{where.name}, {where.country}" if where.country else where.name,
        kind=weather.kind.value,
        years=YEARS,
        days=[
            WeatherDayOut(
                day=d.day,
                high=d.high,
                low=d.low,
                rain=d.rain,
                summary=describe(d.code),
                code=d.code,
            )
            for d in weather.days
        ],
    )


# --- the read-only link for the people going ---------------------------------------------


class ShareOut(Model):
    token: str | None  # the link is /shared/<token>; None when the trip isn't shared
    # Whether the link shows flights, stays and tickets (on unless turned off). Money,
    # booking references, notes and who's going are never shown.
    show_bookings: bool = True


class ShareIn(Model):
    renew: bool = False  # a new link; the old one stops working
    # Show flights, stays and tickets on the link. Left out, the link keeps its setting
    # (on for a new one).
    show_bookings: bool | None = None


@router.get("/trips/{trip_id}/share")
async def get_share(trip_id: str, auth: Auth, web: Runtime) -> ShareOut:
    share = await trip_cases.share_link(web.uow(), auth.user.id, _uuid(trip_id))
    return (
        ShareOut(token=share.token, show_bookings=share.show_bookings)
        if share
        else ShareOut(token=None)
    )


@router.post("/trips/{trip_id}/share")
async def share_trip(trip_id: str, body: ShareIn, auth: Auth, web: Runtime) -> ShareOut:
    """The trip's read-only link, made if it has none (or anew with ``renew``). With
    ``show_bookings`` it also sets whether the link shows flights, stays and tickets."""
    share = await trip_cases.share_trip(
        web.uow(),
        auth.user.id,
        _uuid(trip_id),
        renew=body.renew,
        show_bookings=body.show_bookings,
        now=web.clock(),
    )
    return ShareOut(token=share.token, show_bookings=share.show_bookings)


@router.delete("/trips/{trip_id}/share", status_code=204)
async def stop_sharing(trip_id: str, auth: Auth, web: Runtime) -> Response:
    await trip_cases.stop_sharing(web.uow(), auth.user.id, _uuid(trip_id))
    return Response(status_code=204)


# Opened by anyone with the link, signed in or not. What it shows is an allow-list: the
# plan (days, times, places), never money, booking references, notes or who's going.
shared_router = APIRouter(prefix="/api/shared")


class SharedBookingOut(Model):
    kind: str
    title: str
    provider: str | None
    starts: date
    ends: date | None
    segments: list[SegmentOut]
    hotel: str | None
    address: str | None
    check_in: date | None
    check_out: date | None
    day: date | None
    at: str | None
    category: str | None


class SharedTripOut(Model):
    destination: str
    start: date
    end: date
    days: int
    status: str
    days_until: int
    day_number: int | None
    day_labels: dict[date, str]
    stops: list[StopOut]
    photo: PhotoOut | None
    bookings: list[SharedBookingOut]
    # False when the owner hides flights, stays and tickets: `bookings` then holds only
    # their own plans, and `hidden_days` the days a hidden booking starts or ends on
    # (dates alone), so the page can say "Travel day" instead of "Free day".
    show_bookings: bool = True
    hidden_days: list[date] = Field(default_factory=list)


def _shared_booking(b: Booking) -> SharedBookingOut:
    full = _booking(b)
    return SharedBookingOut(
        kind=full.kind,
        title=full.title,
        provider=full.provider,
        starts=full.starts,
        ends=full.ends,
        segments=full.segments,
        hotel=full.hotel,
        address=full.address,
        check_in=full.check_in,
        check_out=full.check_out,
        day=full.day,
        at=full.at,
        category=full.category,
    )


def _check_shared_limit(web: WebRuntime, token: str) -> None:
    if not web.limits.allow("shared", token):
        raise HTTPException(status_code=429, detail="Too many at once. Try again in a minute.")


@shared_router.get("/trips/{token}")
async def shared_trip(token: str, web: Runtime) -> SharedTripOut:
    """A shared trip's plan, for anyone with its link."""
    _check_shared_limit(web, token)
    shared = await trip_cases.open_shared(web.uow(), token)
    trip = shared.trip
    today = web.clock().date()
    photos = await photo_cases.photos_of(web.uow(), [trip]) if not trip.photo_off else {}
    photo = _photo(photos.get(trip.photo_id)) if trip.photo_id else None
    if photo is not None:
        photo = photo.model_copy(update={"url": f"/api/shared/trips/{token}/photo"})
    return SharedTripOut(
        destination=trip.destination,
        start=trip.start,
        end=trip.end,
        days=trip.days,
        status=trip.status(today).value,
        days_until=(trip.start - today).days,
        day_number=trip.day_number(today),
        day_labels=dict(trip.day_labels),
        stops=_stops(trip.stops),
        photo=photo,
        bookings=[_shared_booking(b) for b in _in_order(shared.bookings)],
        show_bookings=shared.show_bookings,
        hidden_days=shared.hidden_days,
    )


def _in_order(bookings: list[Booking]) -> list[Booking]:
    """The scheduled entries day by day, each day as the itinerary has it (rearranged
    by hand, or by time)."""
    scheduled = [b for b in bookings if b.scheduled]
    seen: set[UUID] = set()
    ordered = []
    for day in itinerary.days_of(scheduled):
        for b in itinerary.on_day(scheduled, day):
            if b.id not in seen:  # a flight landing the next day is listed once
                seen.add(b.id)
                ordered.append(b)
    return ordered


@shared_router.get("/trips/{token}/photo")
async def shared_photo(token: str, web: Runtime) -> Response:
    _check_shared_limit(web, token)
    trip = (await trip_cases.open_shared(web.uow(), token)).trip
    found = (
        await photo_cases.photo_file(web.uow(), trip.photo_id)
        if trip.photo_id and not trip.photo_off
        else None
    )
    if found is None:
        raise NotFound("this trip has no photo")
    data, mime = found
    return Response(
        data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )
