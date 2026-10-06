"""Header photos for trips: a famous, recognisable view of the first place a trip goes,
in the season it goes, found once and shared by every trip there.

How one is found:
1. Wikipedia names the place and where it is (its latitude gives the season).
2. A model names two or three famous spots there, at their best in that season.
3. Their Wikipedia articles' photos are gathered; photos named for the season
   ("Kiyomizudera_Snow.JPG") come first, and only wide, large, freely licensed
   photographs are kept as candidates.
4. A vision model looks at up to four and picks the one that best says "this place",
   or none of them.
5. The pick is kept, with its author and licence for the credit line.

When nothing suits, that's noted, so the place isn't searched again for a while, and
the trip shows a photo from another season of the place, or none (the page then
shows a plain gradient).
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from nexus.application.ports import UnitOfWork
from nexus.domain.destination_photos import (
    RETRY_DAYS,
    Candidate,
    DestinationPhoto,
    Season,
    first_place,
    place_key,
    ranked,
    season,
)
from nexus.domain.trips import Trip

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

PHOTOS_JOB = "travel.photos"
MAX_SPOTS = 3  # famous spots asked for
MAX_LOOKS = 4  # photos the vision model chooses between
PER_SWEEP = 3  # trips given a photo per run
SWEEP_BUDGET_SECONDS = 60.0  # no new trip started after this; the job's limit is 90s
TRY_AGAIN = timedelta(hours=6)  # a trip whose search failed (Wikipedia down) waits this long


class PhotoSourceError(Exception):
    """Wikipedia couldn't answer right now; try again later."""


@dataclass(frozen=True, slots=True)
class PlaceInfo:
    title: str  # Wikipedia's name for it ("Kyoto")
    latitude: float | None


class PhotoSource(Protocol):
    async def place(self, name: str) -> PlaceInfo | None:
        """The place's Wikipedia article, or None when there's no such place."""
        ...

    async def candidates(self, spot: str, of: Season, latitude: float | None) -> list[Candidate]:
        """Photos from the spot's Wikipedia article: its lead photo, and photos named
        for the season."""
        ...

    async def download(self, url: str) -> tuple[bytes, str]:
        """An image's bytes and type."""
        ...


class Spotter(Protocol):
    async def spots(self, place: str, of: Season) -> list[str]:
        """Wikipedia titles of the place's most famous sights, best in that season
        first."""
        ...


class Chooser(Protocol):
    async def choose(self, place: str, of: Season, previews: list[bytes]) -> int | None:
        """The index of the photo that best shows the place, or None if none does."""
        ...


@dataclass(frozen=True, slots=True)
class PhotoFinder:
    """Where photos come from, and the models that pick them. Without models, the
    lead photo of the place's own article is taken, if it suits."""

    source: PhotoSource
    spotter: Spotter | None = None
    chooser: Chooser | None = None


def _usable_now(photo: DestinationPhoto, now: datetime) -> bool:
    """A kept photo, or a recent note that none was found."""
    return photo.found or now - photo.created_at < timedelta(days=RETRY_DAYS)


def _fallback(photos: list[DestinationPhoto]) -> DestinationPhoto | None:
    """Another season's photo of the place, the year-round one first."""
    found = sorted((p for p in photos if p.found), key=lambda p: p.season is not Season.ANY)
    return found[0] if found else None


async def photo_for(
    uow: UowFactory,
    finder: PhotoFinder,
    destination: str,
    start: date,
    *,
    now: datetime,
) -> DestinationPhoto | None:
    """The header photo for a trip to ``destination`` starting ``start``: kept from an
    earlier trip there, or found now. None when there isn't a suitable one.
    Raises PhotoSourceError when Wikipedia can't be asked."""
    place = first_place(destination)
    key = place_key(place)
    if not key:
        return None
    async with uow() as tx:
        kept = await tx.trips.place_photos(key)
    if kept:
        latitude = kept[0].latitude
        of = season(start, latitude)
        match = next((p for p in kept if p.season is of), None)
        if match is not None and _usable_now(match, now):
            return match if match.found else _fallback(kept)
    info = await finder.source.place(place)
    latitude = info.latitude if info else None
    of = season(start, latitude)
    title = info.title if info else place
    found = await _search(finder, title, of, latitude) if info else None
    if found is None:
        note = DestinationPhoto(
            uuid4(), key, of, latitude, False, None, None, None, None, None, now
        )
        async with uow() as tx:
            await tx.trips.save_photo(note, None, None)
            await tx.commit()
            kept = await tx.trips.place_photos(key)
        return _fallback(kept)
    pick, data, mime = found
    photo = DestinationPhoto(
        uuid4(), key, of, latitude, True, pick.spot, pick.author, pick.licence,
        pick.licence_url, pick.page, now,
    )  # fmt: skip
    async with uow() as tx:
        saved = await tx.trips.save_photo(photo, data, mime)
        await tx.commit()
    return saved


async def _search(
    finder: PhotoFinder,
    place: str,
    of: Season,
    latitude: float | None,
) -> tuple[Candidate, bytes, str] | None:
    source, spotter, chooser = finder.source, finder.spotter, finder.chooser
    spots: list[str] = []
    if spotter is not None:
        try:
            spots = await spotter.spots(place, of)
        except Exception:
            log.warning("couldn't ask for famous spots; using the place's own photos")
    names = list(dict.fromkeys([*spots[:MAX_SPOTS], place]))
    found: list[Candidate] = []
    failed: PhotoSourceError | None = None
    for name in names:
        try:
            found.extend(await source.candidates(name, of, latitude))
        except PhotoSourceError as exc:
            failed = exc  # one spot's article not answering doesn't stop the others
    choices = ranked(found)[:MAX_LOOKS]
    if not choices:
        if failed is not None:
            raise failed  # not "nothing suits": try again later
        return None
    pick: Candidate | None = choices[0]
    if chooser is not None:
        previews: list[tuple[Candidate, bytes]] = []
        for c in choices:
            try:
                previews.append((c, (await source.download(c.preview))[0]))
            except PhotoSourceError:
                continue
        if not previews:
            return None
        try:
            n = await chooser.choose(place, of, [b for _, b in previews])
        except Exception:
            log.warning("the photo chooser failed; keeping the first candidate")
            n = 0
        pick = previews[n][0] if n is not None and 0 <= n < len(previews) else None
    if pick is None:
        return None
    data, mime = await source.download(pick.url)
    return pick, data, mime


async def photos_of(uow: UnitOfWork, trips: list[Trip]) -> dict[UUID, DestinationPhoto]:
    """The header photos of these trips, by id (without the image bytes)."""
    ids = list({t.photo_id for t in trips if t.photo_id is not None})
    if not ids:
        return {}
    async with uow:
        return await uow.trips.photos(ids)


async def photo_file(uow: UnitOfWork, photo_id: UUID) -> tuple[bytes, str] | None:
    async with uow:
        return await uow.trips.photo_file(photo_id)


async def queue_photo(uow: UnitOfWork, now: datetime) -> None:
    """Look for photos soon (a trip was added or moved), inside the caller's
    transaction; one job a minute however many saves."""
    minute = now.replace(second=0, microsecond=0)
    await uow.jobs.enqueue(
        PHOTOS_JOB, {}, dedupe_key=f"{PHOTOS_JOB}:soon@{minute.isoformat()}", run_at=now
    )


async def sweep(
    uow: UowFactory,
    finder: PhotoFinder,
    *,
    now: datetime,
) -> int:
    """Give trips not yet over a header photo. Returns how many were looked at."""
    async with uow() as tx:
        due = await tx.trips.trips_needing_photos(
            (now - timedelta(days=1)).date(), now - TRY_AGAIN, limit=PER_SWEEP
        )
    started = time.monotonic()
    done = 0
    for trip in due:
        if time.monotonic() - started > SWEEP_BUDGET_SECONDS:
            break
        await _one(uow, finder, trip, now)
        done += 1
    return done


async def _one(
    uow: UowFactory,
    finder: PhotoFinder,
    trip: Trip,
    now: datetime,
) -> None:
    try:
        async with asyncio.timeout(SWEEP_BUDGET_SECONDS):
            photo = await photo_for(uow, finder, trip.destination, trip.start, now=now)
    except (PhotoSourceError, TimeoutError) as exc:
        log.warning("a trip photo couldn't be found right now: %s", type(exc).__name__)
        photo = None
    except Exception:
        log.exception("a trip photo couldn't be found")
        photo = None
    async with uow() as tx:
        await tx.trips.set_trip_photo(trip.id, photo.id if photo else None, now)
        await tx.commit()
