"""Google Maps places for trips: finding places, linking itinerary entries to them,
and their ratings, regular hours and reviews.

Only a place's id is stored, on its itinerary entry. Details are fetched when shown
and kept in memory for a short while, so a page refresh doesn't pay again. Each
user has a cap on the lookups that reach Google, which keeps the bill inside the
free monthly allowance for personal use.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from nexus.application.clock import utcnow
from nexus.application.limits import RateLimiter, Window
from nexus.application.ports import UnitOfWork
from nexus.domain.bookings import Booking, BookingKind
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import UserId
from nexus.domain.places import Place, place_id

log = logging.getLogger(__name__)

MAX_RESULTS = 5
MAX_QUERY = 120
MAX_LINKED = 30  # entries a trip page looks up at once
CACHE_FOR = timedelta(minutes=30)
CACHE_SIZE = 500
# Lookups that reach Google, per user (cached answers don't count).
LIMITS: Sequence[Window] = ((30, timedelta(minutes=1)), (200, timedelta(days=1)))


class PlacesError(Exception):
    """Google Maps couldn't be asked, or didn't answer usefully."""


class PlaceSource(Protocol):
    async def search(self, query: str, *, limit: int) -> list[Place]: ...

    async def details(self, place_id: str) -> Place | None: ...


class Places:
    """Google lookups, cached briefly and capped per user."""

    def __init__(
        self,
        source: PlaceSource,
        *,
        clock: Callable[[], datetime] = utcnow,
        limits: Sequence[Window] = LIMITS,
    ) -> None:
        self._source = source
        self._clock = clock
        self._limiter = RateLimiter({"places": limits}, clock=clock)
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

    async def search(self, user_id: UserId, query: str) -> list[Place]:
        query = " ".join(query.split())[:MAX_QUERY]
        if not query:
            raise InvalidInput("say what to look for, like 'ramen in Shinjuku'")
        key = f"search:{query.casefold()}"
        cached = self._cached(key)
        if isinstance(cached, list):
            return cached
        self._allow(user_id)
        found = await self._source.search(query, limit=MAX_RESULTS)
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
        changed = replace(current, draft=replace(current.draft, place_id=pid))
        await uow.trips.update_booking(changed)
        await uow.commit()
    return changed


@dataclass(frozen=True, slots=True)
class LinkedPlace:
    booking_id: UUID
    place: Place
    warning: str | None  # closed that day, or not open at the planned time


async def trip_places(
    uow: UnitOfWork, places: Places, user_id: UserId, trip_id: UUID
) -> list[LinkedPlace]:
    """Google's details for the trip's linked entries, with a warning where the plan's
    day or time falls outside the place's regular hours."""
    async with uow:
        if await uow.trips.get_trip(user_id, trip_id) is None:
            raise NotFound("no trip with that id")
        items = await uow.trips.list_bookings(user_id, trip_id=trip_id)
    linked = [b for b in items if b.draft.place_id and linkable(b)]
    found = await places.many(user_id, [b.draft.place_id for b in linked if b.draft.place_id])
    result = []
    for b in linked:
        place = found.get(b.draft.place_id or "")
        if place is None:
            continue
        hotel = b.draft.kind is BookingKind.HOTEL
        warning = place.warning(None) if hotel else place.warning(b.draft.day, b.draft.at)
        result.append(LinkedPlace(b.id, place, warning))
    return result


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
