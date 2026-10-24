"""The time zone that follows the user: ``report_zone`` takes what their phone, they
themselves or their trip says about where they are, applies the rule
(``domain.whereabouts.decide``), saves it and, when the zone itself changed, tells them
once on Telegram. An hourly sweep applies what the trips say. The rules are in the domain
module; ``User.timezone`` is the current zone, which every reader of it follows.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from nexus.application.budgets import TELEGRAM_SEND, UowFactory
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import NotFound
from nexus.domain.ledger import User, UserId, ZoneSource
from nexus.domain.notifications import Kind, Level
from nexus.domain.stops import stop_on, suggest_stops
from nexus.domain.trips import Trip as OngoingTrip
from nexus.domain.whereabouts import (
    Chat,
    Phone,
    Signal,
    Trip,
    decide,
    known_zone,
    switched_text,
    valid_zone,
)

log = logging.getLogger(__name__)

FOLLOW_JOB = "whereabouts.follow"


class ZoneFinder(Protocol):
    async def zone_of(self, place: str) -> str | None:
        """The IANA time zone of a place by name, or None. Never raises."""
        ...


@dataclass(frozen=True, slots=True)
class Reported:
    """What a report did. ``changed``: the current zone is now a different one (and the
    user was told, unless the caller said not to)."""

    user: User
    changed: bool
    old: str
    new: str


def signal_of(source: ZoneSource, zone: str | None) -> Signal:
    """The signal for who is speaking: the phone, the user (in chat or Settings; HOME is
    them saying they are back home, whatever zone is given) or a trip (None: none is on)."""
    if source is ZoneSource.PHONE:
        return Phone(valid_zone(zone))
    if source is ZoneSource.CHAT:
        return Chat(valid_zone(zone) if zone is not None else None)
    if source is ZoneSource.HOME:
        return Chat(None)
    return Trip(valid_zone(zone) if zone is not None else None)


async def report_zone(
    uow: UnitOfWork,
    user_id: UserId,
    zone: str | None,
    source: ZoneSource,
    now: datetime,
    *,
    notify: bool = True,
) -> Reported:
    """Apply what ``source`` says about where the user is. Raises InvalidInput for a zone
    that does not exist. When the current zone changes, ONE message goes to their Telegram
    chat ("🕑 Switched to Madrid time (UTC+2)." or "🕑 Back on Singapore time."); a phone
    that repeats the zone they are already in, or any report that changes nothing, sends
    none. ``notify=False`` is for callers whose own reply already says it (the chat)."""
    signal = signal_of(source, zone)
    async with uow:
        user = await uow.ledger.get_user(user_id, for_update=True)
        if user is None:
            raise NotFound("user not found")
        change = decide(
            user.timezone,
            user.home_timezone,
            user.timezone_source,
            user.timezone_set_at,
            signal,
            now,
        )
        if change is None:
            return Reported(user, False, user.timezone, user.timezone)
        await uow.ledger.set_timezone(user_id, change.zone, change.source, change.set_at)
        if change.switched and notify and user.telegram_chat_id is not None:
            await uow.jobs.enqueue(
                TELEGRAM_SEND,
                {
                    "user_id": str(user_id),
                    "text": switched_text(change.zone, user.home_timezone, now),
                    "kind": Kind.TIMEZONE,
                    # Never counted toward the day's cap (Kind.TIMEZONE is uncapped), but
                    # it keeps to quiet hours in the new zone: a switch made by the trip
                    # sweep at 3am waits for the morning.
                    "level": Level.NOW,
                },
                dedupe_key=f"timezone:{user_id}:{change.zone}:{now.isoformat()}",
                run_at=now,
            )
        await uow.commit()
    updated = replace(
        user, timezone=change.zone, timezone_source=change.source, timezone_set_at=change.set_at
    )
    return Reported(updated, change.switched, user.timezone, change.zone)


# --- the trip sweep ----------------------------------------------------------------------


def _ongoing(trips: Sequence[OngoingTrip]) -> OngoingTrip | None:
    """The trip that is on: the one that started last, when two overlap."""
    return max(trips, key=lambda t: (t.start, t.created_at), default=None)


async def trip_zone(
    uow: UowFactory, zones: ZoneFinder, user: User, now: datetime
) -> tuple[bool, str | None]:
    """(whether a trip is on today in the user's own day, the zone of where it is today).
    The zone is the day's stop, else the destination; None when no place's zone could be
    found, which says nothing about whether a trip is on."""
    today = now.astimezone(ZoneInfo(user.timezone)).date()
    async with uow() as tx:
        trip = _ongoing(await tx.trips.trips_on(user.id, today))
        if trip is None:
            return False, None
        stops = trip.stops
        if not stops:
            bookings = await tx.trips.list_bookings(user.id, trip_id=trip.id)
            stops = suggest_stops(trip, bookings, {})
    stop = stop_on(stops, today)
    for place in dict.fromkeys(p for p in (stop.name if stop else None, trip.destination) if p):
        zone = await zones.zone_of(place)
        if zone is not None and known_zone(zone) is not None:
            return True, zone
    return True, None


async def follow_trip(uow: UowFactory, zones: ZoneFinder, user: User, *, now: datetime) -> bool:
    """Apply what the user's trip says about where they are. Returns whether the current
    zone changed."""
    on, zone = await trip_zone(uow, zones, user, now)
    if on and zone is None:
        return False  # a trip is on but we cannot tell where: leave things as they are
    reported = await report_zone(uow(), user.id, zone, ZoneSource.TRIP, now)
    return reported.changed


async def follow_trips(uow: UowFactory, zones: ZoneFinder, *, now: datetime) -> int:
    """The hourly sweep: move everyone with a trip on to where it is today, and everyone
    the trip had moved back home once it is over. Returns how many changed zone."""
    async with uow() as tx:
        # Anyone with a trip not over (in any zone) or one that moved them.
        ids = set(await tx.trips.travellers(now.date() - timedelta(days=1)))
        ids.update(await tx.ledger.users_with_zone_source(ZoneSource.TRIP))
    changed = 0
    for user_id in ids:
        try:
            async with uow() as tx:
                user = await tx.ledger.get_user(user_id)
            if user is not None:
                changed += int(await follow_trip(uow, zones, user, now=now))
        except Exception:
            # One user's failure must not stop the others; the next sweep retries.
            log.exception("could not follow a trip's time zone for a user")
    return changed
