"""Giving a plan the chat adds to a trip day without a time one.

The day's timed entries are read (flights and trains included, hotels not), the earliest
the plan could start is worked out (now, when the day is today; else 09:00; or right
after the plan it was asked to follow, with room to get there) and the first free gap
that fits it is taken (``domain.itinerary.pick_slot``). A time the user gave always
wins. When nothing fits before 23:00 the plan is left as it was: last in the day, with
no time.

Room between two places is the Routes API's travel time when both are linked to Google
Maps, asked for within a couple of seconds; otherwise, or if that fails, a quarter hour.
It never fails the add.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, time
from uuid import UUID

from nexus.application.places import Places
from nexus.application.ports import UnitOfWork
from nexus.application.routes import Routes, travel_buffers
from nexus.domain import itinerary
from nexus.domain.bookings import Booking, BookingDraft, BookingKind
from nexus.domain.ledger import UserId
from nexus.domain.trips import Trip

# Asking for travel times may take this long in all, whatever it takes to add the plan.
ROUTES_WITHIN = 2.0

type UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class Fitted:
    draft: BookingDraft  # with the time picked, when there was one to pick
    picked: bool = False  # a time was looked for (the plan had none)
    slot: itinerary.Slot | None = None  # what was found; None with ``picked``: no room
    after: Booking | None = None  # the plan it was asked to follow, when that has a time


def _plus(at: time, minutes: int) -> time | None:
    """``at`` and ``minutes`` later, or None when that is past the end of the day."""
    total = at.hour * 60 + at.minute + minutes
    return time(total // 60, total % 60) if total < 24 * 60 else None


async def fit_plan(
    uow: UowFactory,
    places: Places | None,
    routes: Routes | None,
    user_id: UserId,
    owner_id: UserId,
    trip: Trip,
    draft: BookingDraft,
    *,
    now: datetime,
    after: str | None = None,
    minutes: int | None = None,
) -> Fitted:
    """A new plan with a time picked for it. ``now`` is the user's local time;
    ``user_id`` is who is chatting and ``owner_id`` whose trip it is. A plan that isn't on
    a day, or has a time or an end already, comes back as it was (with ``minutes`` and a
    start, an end)."""
    day = draft.day
    if draft.kind is not BookingKind.ACTIVITY or day is None:
        return Fitted(draft)
    if draft.at is not None:
        end = _plus(draft.at, minutes) if minutes and draft.ends_at is None else None
        return Fitted(replace(draft, ends_at=end) if end else draft)
    if draft.ends_at is not None:
        return Fitted(draft)
    async with uow() as tx:
        items = await tx.trips.list_bookings(owner_id, trip_id=trip.id)
    anchor = (
        itinerary.match_entry(itinerary.on_day(items, day), after, has=f"{day:%a %d %b} has")
        if after
        else None
    )
    deadline = asyncio.get_running_loop().time() + ROUTES_WITHIN
    buffers: dict[UUID, int] = {}
    place = draft.place_id if places is not None and routes is not None else None

    async def learn(before: Sequence[Booking], following: Sequence[Booking]) -> None:
        if place and places is not None and routes is not None and (before or following):
            buffers.update(
                await travel_buffers(
                    places, routes, user_id, trip, day, place,
                    previous=before, following=following, deadline=deadline,
                )
            )  # fmt: skip

    # Today it starts from now, and any other day from the morning.
    earliest = now.time() if day == now.date() else itinerary.DAY_STARTS
    if anchor is not None:
        ended = itinerary.finish(anchor, day)
        if ended is not None:
            await learn([anchor], [])
            ready = _plus(ended, buffers.get(anchor.id, itinerary.TRAVEL_BUFFER))
            if ready is None:
                return Fitted(draft, True, None, anchor)
            earliest = max(earliest, ready) if day == now.date() else ready
    length = minutes or itinerary.usual_minutes(draft.category)

    def pick() -> itinerary.Slot | None:
        return itinerary.pick_slot(items, day, earliest=earliest, minutes=length, buffers=buffers)

    slot = pick()
    if slot is not None:
        # The ones either side of it, now known, may be further away than the allowance.
        near_before = [b for b in (slot.previous,) if b is not None and b.id not in buffers]
        near_after = [b for b in (slot.next,) if b is not None and b.id not in buffers]
        if near_before or near_after:
            await learn(near_before, near_after)
            slot = pick()
    if slot is None:
        return Fitted(draft, True, None, anchor)
    return Fitted(replace(draft, at=slot.start, ends_at=slot.end), True, slot, anchor)
