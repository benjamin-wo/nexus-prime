"""How long it takes to get between a trip day's stops, from Google's Routes API.

Each hop is asked for by its two Google place ids and a way of travelling (walking
for a short hop, public transport for a longer one, or what the user picks; driving
when public transport finds no route). Answers are kept in memory for a short while,
like place details, and never stored. Each user has a cap on the calls that reach
Google, which keeps the bill inside the free monthly allowance for personal use.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from nexus.application.clock import utcnow
from nexus.application.limits import RateLimiter, Window
from nexus.application.places import Places
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import UserId
from nexus.domain.places import metres_between
from nexus.domain.routes import Hop, Mode, day_hops, default_mode, directions_url, tight

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


async def hop_times(
    uow: UnitOfWork,
    places: Places,
    routes: Routes,
    user_id: UserId,
    trip_id: UUID,
    day: date,
) -> list[HopTime]:
    """Each hop on the trip's ``day`` with how long it takes, by the default way of
    travelling for its distance. A hop Google can't answer is left without a time."""
    hops = await _day(uow, user_id, trip_id, day)
    if not hops:
        return []
    ids = {pid for h in hops for pid in (h.start.place_id, h.end.place_id)}
    found = await places.many(user_id, sorted(ids))

    async def one(hop: Hop) -> HopTime:
        a, b = found.get(hop.start.place_id), found.get(hop.end.place_id)
        metres = (
            metres_between(a.location, b.location)
            if a is not None and b is not None and a.location and b.location
            else None
        )
        mode = default_mode(metres)
        try:
            return await _time(routes, user_id, hop, mode, fallback=True)
        except RoutesError:
            log.info("no travel time for a hop", exc_info=True)
            return HopTime(hop, mode, None, None, False, directions_url(hop, mode))

    gate = asyncio.Semaphore(4)

    async def gated(hop: Hop) -> HopTime:
        async with gate:
            return await one(hop)

    return list(await asyncio.gather(*(gated(h) for h in hops)))


async def hop_time(
    uow: UnitOfWork,
    routes: Routes,
    user_id: UserId,
    trip_id: UUID,
    day: date,
    start: UUID,
    end: UUID,
    mode: Mode,
) -> HopTime:
    """One hop of the day, the way the user picked."""
    hops = await _day(uow, user_id, trip_id, day)
    hop = next((h for h in hops if h.start.booking_id == start and h.end.booking_id == end), None)
    if hop is None:
        raise NotFound("those two aren't one after the other that day")
    return await _time(routes, user_id, hop, mode, fallback=False)


async def _day(uow: UnitOfWork, user_id: UserId, trip_id: UUID, day: date) -> list[Hop]:
    async with uow:
        trip = await uow.trips.get_trip(user_id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        bookings = await uow.trips.list_bookings(user_id, trip_id=trip_id)
    return day_hops(bookings, day)
