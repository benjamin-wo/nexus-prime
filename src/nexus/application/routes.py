"""How long it takes to get between a trip day's stops, from Google's Routes API.

Each hop is asked for by its two Google place ids and a way of travelling (walking
for a short hop, public transport or a hire car for a longer one, or what the user
picked for it, which is kept; driving when public transport finds no route). Answers
are kept in memory for a short while, like place details, and never stored. Each user
has a cap on the calls that reach Google, which keeps the bill inside the free monthly
allowance for personal use.

The airports and stations a day's flights and trains leave from and land at are
looked up on Google Maps once, by name ("BCN airport"), and only their place ids kept
on the booking, as for a plan's place.

A plan the chat adds to a day without a time is fitted between the day's other entries
with the travel time to its neighbours as room (``travel_buffers``): a best effort that
never fails the add, so anything that goes wrong just leaves the usual allowance.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from nexus.application.clock import utcnow
from nexus.application.limits import RateLimiter, Window
from nexus.application.places import Places, PlacesError
from nexus.application.ports import UnitOfWork
from nexus.domain.bookings import MAX_STATIONS, Booking, BookingKind
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import UserId
from nexus.domain.places import Place, metres_between
from nexus.domain.routes import (
    Hop,
    Mode,
    Stop,
    beside_airport,
    day_hops,
    default_mode,
    directions_url,
    hop_key,
    stations_on,
    tight,
    without_the_car,
)
from nexus.domain.trips import MAX_HOP_MODES, GettingAround, Trip

log = logging.getLogger(__name__)

CACHE_FOR = timedelta(minutes=30)
CACHE_SIZE = 1000
# Calls that reach Google, per user (cached answers don't count).
LIMITS: Sequence[Window] = ((60, timedelta(minutes=1)), (300, timedelta(days=1)))


class RoutesError(Exception):
    """Google's Routes API couldn't be asked, or didn't answer usefully."""


@dataclass(frozen=True, slots=True)
class Leg:
    seconds: int
    metres: int


class RouteSource(Protocol):
    async def route(self, origin: str, destination: str, mode: Mode) -> Leg | None:
        """The trip between two Google place ids, or None when there's no route that
        way (no public transport, say)."""
        ...


class Routes:
    """Routes between places, cached briefly and capped per user."""

    def __init__(
        self,
        source: RouteSource,
        *,
        clock: Callable[[], datetime] = utcnow,
        limits: Sequence[Window] = LIMITS,
    ) -> None:
        self._source = source
        self._clock = clock
        self._limiter = RateLimiter({"routes": limits}, clock=clock)
        self._cache: OrderedDict[tuple[str, str, Mode], tuple[datetime, Leg | None]] = OrderedDict()

    async def leg(self, user_id: UserId, origin: str, destination: str, mode: Mode) -> Leg | None:
        key = (origin, destination, mode)
        hit = self._cache.get(key)
        now = self._clock()
        if hit is not None and now - hit[0] < CACHE_FOR:
            self._cache.move_to_end(key)
            return hit[1]
        if not self._limiter.allow("routes", user_id):
            raise InvalidInput("that's a lot of travel times at once; try again later")
        found = await self._source.route(origin, destination, mode)
        self._cache[key] = (now, found)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return found


@dataclass(frozen=True, slots=True)
class HopTime:
    hop: Hop
    mode: Mode
    minutes: int | None  # None when Google found no way to get there
    metres: int | None
    tight: bool  # longer than the time between the two plans
    directions: str  # Google Maps directions, which open the Maps app on a phone
    beside_airport: bool = False  # between an airport and a place right by it: not timed


async def _time(
    routes: Routes, user_id: UserId, hop: Hop, mode: Mode, *, fallback: bool
) -> HopTime:
    leg = await routes.leg(user_id, hop.start.place_id, hop.end.place_id, mode)
    if leg is None and fallback and mode is Mode.TRANSIT:
        mode = Mode.DRIVE  # no public transport that way
        leg = await routes.leg(user_id, hop.start.place_id, hop.end.place_id, mode)
    minutes = max(1, round(leg.seconds / 60)) if leg else None
    return HopTime(
        hop,
        mode,
        minutes,
        leg.metres if leg else None,
        tight(hop, minutes) if minutes is not None else False,
        directions_url(hop, mode),
    )


type UowFactory = Callable[[], UnitOfWork]


async def hop_times(
    uow: UowFactory,
    places: Places,
    routes: Routes,
    user_id: UserId,
    trip_id: UUID,
    day: date,
) -> list[HopTime]:
    """Each hop on the trip's ``day`` with how long it takes: the way picked for it,
    else the trip's usual way for its distance. A hop Google can't answer is left
    without a time."""
    trip, bookings = await _load(uow(), user_id, trip_id)
    bookings = await find_stations(uow(), places, user_id, bookings, day)
    hops = day_hops(bookings, day)
    if not hops:
        return []
    ids = {pid for h in hops for pid in (h.start.place_id, h.end.place_id)}
    found = await places.many(user_id, sorted(ids))
    flights = {b.id for b in bookings if b.draft.kind is BookingKind.FLIGHT}

    async def one(hop: Hop) -> HopTime:
        a, b = found.get(hop.start.place_id), found.get(hop.end.place_id)
        metres = (
            metres_between(a.location, b.location)
            if a is not None and b is not None and a.location and b.location
            else None
        )
        if beside_airport(hop, metres, flights):
            # Landing and collecting a hire car, say: part of the arrival, not a trip.
            walk = directions_url(hop, Mode.WALK)
            return HopTime(hop, Mode.WALK, None, round(metres or 0), False, walk, True)
        picked = _picked(trip, hop)
        # Even on a trip with a hire car, not before it's picked up or after it's back.
        by = GettingAround.TRANSIT if without_the_car(hop) else trip.getting_around
        mode = picked or default_mode(metres, by)
        try:
            return await _time(routes, user_id, hop, mode, fallback=picked is None)
        except RoutesError:
            log.info("no travel time for a hop", exc_info=True)
            return HopTime(hop, mode, None, None, False, directions_url(hop, mode))

    gate = asyncio.Semaphore(4)

    async def gated(hop: Hop) -> HopTime:
        async with gate:
            return await one(hop)

    return list(await asyncio.gather(*(gated(h) for h in hops)))


async def hop_time(
    uow: UowFactory,
    routes: Routes,
    user_id: UserId,
    trip_id: UUID,
    day: date,
    start: UUID,
    end: UUID,
    mode: Mode,
) -> HopTime:
    """One hop of the day, the way the user picked; the pick is kept for next time."""
    _, bookings = await _load(uow(), user_id, trip_id)
    hops = day_hops(bookings, day)
    hop = next((h for h in hops if h.start.booking_id == start and h.end.booking_id == end), None)
    if hop is None:
        raise NotFound("those two aren't one after the other that day")
    found = await _time(routes, user_id, hop, mode, fallback=False)
    await _keep_pick(uow(), user_id, trip_id, hop, mode)
    return found


def _place_of(b: Booking, day: date, *, coming_from: bool) -> str | None:
    """The Google place id of where an entry is on the way in or out of: a plan's, or
    the station a train or flight lands at (``coming_from``) or leaves from."""
    d = b.draft
    if d.kind is BookingKind.ACTIVITY:
        return d.place_id
    if d.kind in (BookingKind.FLIGHT, BookingKind.RAIL):
        leave, land = stations_on(b, day)
        return d.station((land if coming_from else leave) or "") or None
    return None


async def travel_buffers(
    places: Places,
    routes: Routes,
    user_id: UserId,
    trip: Trip,
    day: date,
    place_id: str,
    *,
    previous: Sequence[Booking],
    following: Sequence[Booking],
    deadline: float,
) -> dict[UUID, int]:
    """Minutes to get between a new plan's place and the entries just before it (from
    them to it) and just after it (from it to them), for each one with a place of its
    own: walking when close, else the trip's usual way, as for a day's hops. Whatever
    can't be worked out by the event loop's ``deadline`` (or fails) is left out, and so
    gets the usual allowance. Never raises."""
    found: dict[UUID, int] = {}
    hops: dict[UUID, Hop] = {}
    for b in previous:
        pid = _place_of(b, day, coming_from=True)
        if pid and pid != place_id:
            hops[b.id] = Hop(Stop(b.id, pid, b.draft.title, None), Stop(b.id, place_id, "", None))
    for b in following:
        pid = _place_of(b, day, coming_from=False)
        if pid and pid != place_id and b.id not in hops:
            hops[b.id] = Hop(Stop(b.id, place_id, "", None), Stop(b.id, pid, b.draft.title, None))
    if not hops:
        return found

    async def one(key: UUID, hop: Hop, places_found: dict[str, Place]) -> None:
        a, b = places_found.get(hop.start.place_id), places_found.get(hop.end.place_id)
        metres = (
            metres_between(a.location, b.location)
            if a is not None and b is not None and a.location and b.location
            else None
        )
        mode = default_mode(metres, trip.getting_around)
        timed = await _time(routes, user_id, hop, mode, fallback=True)
        if timed.minutes is not None:
            found[key] = timed.minutes

    try:
        async with asyncio.timeout_at(deadline):
            ids = {pid for h in hops.values() for pid in (h.start.place_id, h.end.place_id)}
            details = await places.many(user_id, sorted(ids))
            await asyncio.gather(
                *(one(k, h, details) for k, h in hops.items()), return_exceptions=True
            )
    except Exception:  # a best effort: the usual allowance stands in
        log.info("no travel times for a new plan", exc_info=True)
    return found


def _picked(trip: Trip, hop: Hop) -> Mode | None:
    try:
        return Mode(trip.hop_modes[hop_key(hop)])
    except (KeyError, ValueError):
        return None


async def _keep_pick(uow: UnitOfWork, user_id: UserId, trip_id: UUID, hop: Hop, mode: Mode) -> None:
    async with uow:
        trip = await uow.trips.get_trip(user_id, trip_id)
        if trip is None:
            return
        modes = {k: v for k, v in trip.hop_modes.items() if k != hop_key(hop)}
        modes[hop_key(hop)] = mode.value
        await uow.trips.set_hop_modes(user_id, trip_id, dict(list(modes.items())[-MAX_HOP_MODES:]))
        await uow.commit()


async def _load(uow: UnitOfWork, user_id: UserId, trip_id: UUID) -> tuple[Trip, list[Booking]]:
    async with uow:
        trip = await uow.trips.get_trip(user_id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        bookings = await uow.trips.list_bookings(user_id, trip_id=trip_id)
    return trip, bookings


def _station_place(kind: BookingKind, found: list[Place]) -> Place | None:
    """The first result that's an airport (for a flight) or a station (for a train)."""
    word = "airport" if kind is BookingKind.FLIGHT else "station"
    return next(
        (p for p in found if word in f"{p.kind or ''} {p.name}".casefold()),
        None,
    )


async def find_stations(
    uow: UnitOfWork, places: Places, user_id: UserId, bookings: list[Booking], day: date
) -> list[Booking]:
    """Looks up on Google Maps, once, the airports and stations the day's flights and
    trains leave from and land at, and keeps their place ids ("" when there's no such
    place). Lookups that fail are tried again another time."""
    changed: dict[UUID, Booking] = {}
    for b in bookings:
        if b.draft.kind not in (BookingKind.FLIGHT, BookingKind.RAIL):
            continue
        wanted = [n for n in stations_on(b, day) if n and b.draft.station(n) is None]
        found = dict(b.draft.stations)
        for name in dict.fromkeys(wanted):
            if len(found) >= MAX_STATIONS:
                break
            try:
                place = _station_place(b.draft.kind, await places.search(user_id, name))
            except (PlacesError, InvalidInput):
                log.info("no airport or station looked up", exc_info=True)
                continue
            found[name] = place.id if place else ""
        if found != dict(b.draft.stations):
            changed[b.id] = replace(b, draft=replace(b.draft, stations=tuple(found.items())))
    if not changed:
        return bookings
    async with uow:
        for b in changed.values():
            await uow.trips.update_booking(b)
        await uow.commit()
    return [changed.get(b.id, b) for b in bookings]
