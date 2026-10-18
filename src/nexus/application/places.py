"""Google Maps places for trips: finding places, linking itinerary entries to them,
and their ratings, regular hours and reviews.

Only a place's id is stored, on its itinerary entry. Details are fetched when shown
and kept in memory for a short while, so a page refresh doesn't pay again. Each
user has a cap on the lookups that reach Google, which keeps the bill inside the
free monthly allowance for personal use.
"""

import asyncio
import logging
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from nexus.application.clock import utcnow
from nexus.application.limits import RateLimiter, Window
from nexus.application.ports import UnitOfWork
from nexus.domain.bookings import Booking, BookingKind
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import UserId
from nexus.domain.places import Circle, Place, PlacePhoto, Point, circle_around, place_id
from nexus.domain.routes import stations_on
from nexus.domain.stops import suggest_stops
from nexus.domain.trips import Stop, Trip

log = logging.getLogger(__name__)

MAX_RESULTS = 5
MAX_QUERY = 120
MAX_LINKED = 30  # entries a trip page looks up at once
CACHE_FOR = timedelta(minutes=30)
CACHE_SIZE = 500
# Lookups that reach Google, per user (cached answers don't count).
LIMITS: Sequence[Window] = ((30, timedelta(minutes=1)), (200, timedelta(days=1)))
# Photos fetched from Google, per user (billed per photo; cached ones don't count).
PHOTO_LIMITS: Sequence[Window] = ((30, timedelta(minutes=1)), (100, timedelta(days=1)))
PHOTO_CACHE_SIZE = 150
# How far round a day's places a "near this day" search leans, in metres.
NEAR_RADIUS = 2000.0


class PlacesError(Exception):
    """Google Maps couldn't be asked, or didn't answer usefully."""


class PlaceSource(Protocol):
    async def search(
        self, query: str, *, limit: int, near: Circle | None = None
    ) -> list[Place]: ...

    async def details(self, place_id: str) -> Place | None: ...

    async def photo(self, name: str) -> tuple[bytes, str]: ...


class Places:
    """Google lookups, cached briefly and capped per user."""

    def __init__(
        self,
        source: PlaceSource,
        *,
        clock: Callable[[], datetime] = utcnow,
        limits: Sequence[Window] = LIMITS,
        photo_limits: Sequence[Window] = PHOTO_LIMITS,
    ) -> None:
        self._source = source
        self._clock = clock
        self._limiter = RateLimiter({"places": limits, "photos": photo_limits}, clock=clock)
        self._photos: OrderedDict[str, tuple[datetime, bytes, str]] = OrderedDict()
        self._cache: OrderedDict[str, tuple[datetime, object]] = OrderedDict()

    def _cached(self, key: str) -> object | None:
        found = self._cache.get(key)
        if found is None:
            return None
        at, value = found
        if self._clock() - at >= CACHE_FOR:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def _keep(self, key: str, value: object) -> None:
        self._cache[key] = (self._clock(), value)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)

    def _allow(self, user_id: UserId) -> None:
        if not self._limiter.allow("places", user_id):
            raise InvalidInput("that's a lot of Google Maps lookups at once; try again later")

    async def search(self, user_id: UserId, query: str, near: Circle | None = None) -> list[Place]:
        """Places for a phrase, leaning towards ``near`` when given. The cache tells
        searches apart by where they lean, to about a hundred metres."""
        query = " ".join(query.split())[:MAX_QUERY]
        if not query:
            raise InvalidInput("say what to look for, like 'ramen in Shinjuku'")
        key = f"search:{query.casefold()}"
        if near is not None:
            key += f"@{near.center.lat:.3f},{near.center.lng:.3f},{near.radius:.0f}"
        cached = self._cached(key)
        if isinstance(cached, list):
            return cached
        self._allow(user_id)
        found = await self._source.search(query, limit=MAX_RESULTS, near=near)
        self._keep(key, found)
        return found

    async def details(self, user_id: UserId, wanted: str) -> Place:
        pid = place_id(wanted)
        if pid is None:
            raise NotFound("no place with that id")
        cached = self._cached(f"place:{pid}")
        if isinstance(cached, Place):
            return cached
        self._allow(user_id)
        found = await self._source.details(pid)
        if found is None:
            raise NotFound("Google Maps doesn't know that place")
        self._keep(f"place:{pid}", found)
        return found

    async def photo(self, user_id: UserId, wanted: str) -> tuple[bytes, str, PlacePhoto]:
        """A place's first photo, for a thumbnail: its bytes, type and who to credit.
        Kept in memory for a short while like the details, never stored."""
        place = await self.details(user_id, wanted)
        if place.photo is None:
            raise NotFound("Google Maps has no photo of that place")
        hit = self._photos.get(place.id)
        if hit is not None and self._clock() - hit[0] < CACHE_FOR:
            self._photos.move_to_end(place.id)
            return hit[1], hit[2], place.photo
        if not self._limiter.allow("photos", user_id):
            raise InvalidInput("that's a lot of Google Maps photos at once; try again later")
        data, mime = await self._source.photo(place.photo.name)
        self._photos[place.id] = (self._clock(), data, mime)
        self._photos.move_to_end(place.id)
        while len(self._photos) > PHOTO_CACHE_SIZE:
            self._photos.popitem(last=False)
        return data, mime, place.photo

    async def many(self, user_id: UserId, ids: Sequence[str]) -> dict[str, Place]:
        """Details for several places at once; any that fail are left out."""
        wanted = list(dict.fromkeys(ids))[:MAX_LINKED]
        gate = asyncio.Semaphore(4)

        async def one(pid: str) -> tuple[str, Place | None]:
            async with gate:
                try:
                    return pid, await self.details(user_id, pid)
                except (PlacesError, NotFound, InvalidInput):
                    log.info("place details unavailable", exc_info=True)
                    return pid, None

        results = await asyncio.gather(*(one(pid) for pid in wanted))
        return {pid: place for pid, place in results if place is not None}


def query_for(what: str, destination: str | None) -> str:
    """Narrows a search to the trip's destination unless it's already named."""
    what = " ".join(what.split())
    if destination and destination.casefold() not in what.casefold():
        return f"{what}, {destination}"
    return what


def linkable(booking: Booking) -> bool:
    """Plans, places to visit and hotels can be linked; flights and trains can't."""
    return booking.draft.kind in (BookingKind.ACTIVITY, BookingKind.HOTEL)


def entry_query(booking: Booking, destination: str | None) -> str:
    """What to search Google Maps for to find this entry's place."""
    d = booking.draft
    name = (d.hotel if d.kind is BookingKind.HOTEL else d.name) or d.title
    where = f" {d.address}" if d.address else ""
    return query_for(f"{name}{where}", destination)


async def link_place(
    uow: UnitOfWork, user_id: UserId, booking_id: UUID, wanted: str | None
) -> Booking:
    """Links a plan, place to visit or hotel to a Google Maps place (or unlinks it)."""
    pid = place_id(wanted) if wanted else None
    if wanted and pid is None:
        raise InvalidInput("that isn't a Google Maps place id")
    async with uow:
        current = await uow.trips.get_booking(user_id, booking_id)
        if current is None:
            raise NotFound("no booking with that id")
        if not linkable(current):
            raise InvalidInput("only plans, places to visit and hotels go on Google Maps")
        draft = replace(current.draft, place_id=pid)
        if pid:  # the place has its own position: the user's pin is let go
            draft = replace(draft, lat=None, lng=None)
        changed = replace(current, draft=draft)
        await uow.trips.update_booking(changed)
        await uow.commit()
    return changed


@dataclass(frozen=True, slots=True)
class LinkedPlace:
    booking_id: UUID
    place: Place
    warning: str | None  # closed that day, or not open at the planned time
    # A flight's or train's airport or station: its name as searched, and the days it's
    # left from ("from") or landed at ("to").
    station: str | None = None
    stops: tuple[tuple[date, str], ...] = ()


async def trip_places(
    uow: UnitOfWork, places: Places, user_id: UserId, trip_id: UUID
) -> list[LinkedPlace]:
    """Google's details for the trip's linked entries, with a warning where the plan's
    day or time falls outside the place's regular hours, and the airports and stations
    its flights and trains use, once found."""
    async with uow:
        if await uow.trips.get_trip(user_id, trip_id) is None:
            raise NotFound("no trip with that id")
        items = await uow.trips.list_bookings(user_id, trip_id=trip_id)
    linked = [b for b in items if b.draft.place_id and linkable(b)]
    stations = [
        (b, name, pid, stops)
        for b in items
        for name, pid in b.draft.stations
        if pid and (stops := station_stops(b, name))
    ]
    wanted = [b.draft.place_id for b in linked if b.draft.place_id] + [s[2] for s in stations]
    found = await places.many(user_id, wanted)
    result = []
    for b in linked:
        place = found.get(b.draft.place_id or "")
        if place is None:
            continue
        hotel = b.draft.kind is BookingKind.HOTEL
        warning = place.warning(None) if hotel else place.warning(b.draft.day, b.draft.at)
        result.append(LinkedPlace(b.id, place, warning))
    for b, name, pid, stops in stations:
        if (place := found.get(pid)) is not None:
            result.append(LinkedPlace(b.id, place, None, name, stops))
    return result


async def suggested_stops(
    places: Places | None, user_id: UserId, trip: Trip, bookings: Sequence[Booking]
) -> tuple[Stop, ...]:
    """The stops the hotels suggest, named by the city of each hotel's Google Maps place
    where it's linked. Without Google Maps (or when it can't be asked) the hotels'
    addresses and the destination name them."""
    ids = [
        b.draft.place_id for b in bookings if b.draft.kind is BookingKind.HOTEL and b.draft.place_id
    ]
    found = await places.many(user_id, ids) if places is not None and ids else {}
    cities = {pid: p.city for pid, p in found.items() if p.city}
    return suggest_stops(trip, bookings, cities)


@dataclass(frozen=True, slots=True)
class SearchScope:
    """Where a search for a trip looks: the place named in the search text (the trip's
    destination, a stop, or an area of a stop) and, for a day, a circle round the places
    already planned that day. Worked out when asked, never stored."""

    place: str
    near: Circle | None = None


def _stop_named(stops: Sequence[Stop], wanted: str) -> Stop:
    for s in stops:
        if s.name.casefold() == " ".join(wanted.split()).casefold():
            return s
    listed = ", ".join(s.name for s in stops)
    raise InvalidInput(f"{wanted.strip()!r} isn't one of the trip's stops ({listed})")


def _stop_on(stops: Sequence[Stop], day: date) -> Stop | None:
    """The stop a day is in; on a travel day, the one arrived at."""
    found = [s for s in stops if s.start <= day <= s.end]
    return found[-1] if found else None


def scope_of_day(
    trip: Trip,
    stops: Sequence[Stop],
    bookings: Sequence[Booking],
    found: Mapping[str, Place],
    *,
    stop: str | None = None,
    day: date | None = None,
) -> SearchScope:
    """The search scope for a stop and/or a day of the trip. ``found`` holds the Google
    details of the trip's linked places, by id. A day with nothing planned has no circle
    and is searched by its stop's name alone."""
    if stop is None and day is None:
        return SearchScope(trip.destination)
    chosen = _stop_named(stops, stop) if stop is not None else None
    if day is not None:
        if not trip.start <= day <= trip.end:
            raise InvalidInput(
                f"{day:%d %b} is outside the trip ({trip.start:%d %b} to {trip.end:%d %b})"
            )
        there = _stop_on(stops, day)
        if chosen is not None and not chosen.start <= day <= chosen.end:
            raise InvalidInput(f"{day:%d %b} isn't in {chosen.name}")
        chosen = chosen or there
    name = chosen.name if chosen is not None else trip.destination
    if day is None:
        return SearchScope(name)
    planned = [
        b.draft for b in bookings if b.draft.kind is BookingKind.ACTIVITY and b.draft.day == day
    ]
    places = [p for d in planned if d.place_id and (p := found.get(d.place_id)) is not None]
    points: list[Point] = [p.location for p in places if p.location is not None]
    points += [
        Point(d.lat, d.lng)
        for d in planned
        if not d.place_id and d.lat is not None and d.lng is not None
    ]
    areas = Counter(p.area for p in places if p.area)
    area = areas.most_common(1)[0][0] if areas else None
    text = f"{area}, {name}" if area and area.casefold() != name.casefold() else name
    return SearchScope(text, circle_around(points, NEAR_RADIUS))


async def search_scope(
    uow: UnitOfWork,
    places: Places | None,
    user_id: UserId,
    trip_id: UUID,
    *,
    stop: str | None = None,
    day: date | None = None,
) -> tuple[Trip, SearchScope]:
    """The trip and where a search for it should look: the whole trip (its destination),
    one of its stops, or near a day. The stop must be one of the trip's stops (as set, or
    as its hotels suggest) and the day inside the trip."""
    async with uow:
        trip = await uow.trips.get_trip(user_id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        bookings = await uow.trips.list_bookings(user_id, trip_id=trip_id) if (stop or day) else []
    if stop is None and day is None:
        return trip, SearchScope(trip.destination)
    stops = trip.stops or await suggested_stops(places, user_id, trip, bookings)
    ids = [
        b.draft.place_id
        for b in bookings
        if day is not None and b.draft.day == day and b.draft.place_id and linkable(b)
    ]
    found = await places.many(user_id, ids) if places is not None and ids else {}
    return trip, scope_of_day(trip, stops, bookings, found, stop=stop, day=day)


def station_stops(b: Booking, name: str) -> tuple[tuple[date, str], ...]:
    """The days a flight or train leaves from or lands at the named station."""
    days = sorted({t.date() for s in b.draft.segments for t in (s.departs, s.arrives) if t})
    stops: list[tuple[date, str]] = []
    for day in days:
        leave, land = stations_on(b, day)
        if leave == name:
            stops.append((day, "from"))
        if land == name:
            stops.append((day, "to"))
    return tuple(stops)


_COMMON = frozenset(
    "the and at in on of for to a an by with near dinner lunch breakfast brunch "
    "visit trip day tour hotel restaurant cafe bar market shop".split()
)


def _words(value: str) -> set[str]:
    cleaned = "".join(c if c.isalnum() else " " for c in value.casefold())
    return {w for w in cleaned.split() if len(w) >= 3 and w not in _COMMON}


def same_place(name: str, place: Place) -> bool:
    """Whether a search result is plausibly what the user named: they share a word
    that isn't a filler like "dinner" or "hotel". Names in other scripts share
    characters instead."""
    mine, theirs = _words(name), _words(place.name)
    if mine & theirs:
        return True
    wide = {c for c in name if ord(c) > 0x2E80}  # CJK and similar scripts
    return len(wide & set(place.name)) >= 2


async def best_match(places: Places, user_id: UserId, name: str, query: str) -> Place | None:
    """The top search result if it's plausibly the place named; None when unsure or
    when Google Maps can't be asked."""
    try:
        found = await places.search(user_id, query)
    except (PlacesError, InvalidInput):
        log.info("no Google Maps match looked up", exc_info=True)
        return None
    top = found[0] if found else None
    return top if top is not None and same_place(name, top) else None
