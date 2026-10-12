"""Getting from one stop to the next on a trip day. Pure rules, no I/O.

A day's stops are its plans and hotels linked to a Google Maps place, in the order
the itinerary shows them (``domain.itinerary.on_day``), starting at the hotel
slept in the night before and ending at the one slept in that night. A flight, a
train or a plan with no place breaks the chain: nothing is worked out across it,
since where the traveller is in between isn't known.
"""

from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import StrEnum
from urllib.parse import urlencode
from uuid import UUID

from nexus.domain.bookings import Booking, BookingKind
from nexus.domain.itinerary import on_day

# Up to this far apart (in a straight line), a hop is walked by default.
WALK_UP_TO = 1500
MAX_HOPS = 12


class Mode(StrEnum):
    WALK = "walk"
    TRANSIT = "transit"
    DRIVE = "drive"


_MAPS_MODE = {Mode.WALK: "walking", Mode.TRANSIT: "transit", Mode.DRIVE: "driving"}


@dataclass(frozen=True, slots=True)
class Stop:
    booking_id: UUID
    place_id: str
    title: str
    at: time | None  # when a plan starts, if it has a time


@dataclass(frozen=True, slots=True)
class Hop:
    start: Stop
    end: Stop


def _linked(b: Booking) -> Stop | None:
    d = b.draft
    if not d.place_id or d.kind not in (BookingKind.ACTIVITY, BookingKind.HOTEL):
        return None
    name = (d.hotel or d.provider or "Hotel") if d.kind is BookingKind.HOTEL else d.title
    at = d.at if d.kind is BookingKind.ACTIVITY else None
    return Stop(b.id, d.place_id, name, at)


def _night(b: Booking, night: date) -> bool:
    """Whether the hotel is slept in on the night that starts on ``night``."""
    d = b.draft
    return (
        d.kind is BookingKind.HOTEL
        and d.check_in is not None
        and d.check_out is not None
        and d.check_in <= night < d.check_out
    )


def day_hops(bookings: list[Booking], day: date) -> list[Hop]:
    """The hops on ``day``, in order: one per pair of consecutive linked stops with no
    flight, train or unplaced plan between them, and never from a place to itself."""
    hotels = [b for b in bookings if b.draft.kind is BookingKind.HOTEL]
    morning = next((b for b in hotels if _night(b, day - timedelta(days=1))), None)
    tonight = next((b for b in hotels if _night(b, day)), None)
    entries = on_day(bookings, day)
    chain: list[Booking | None] = [morning, *entries, tonight]
    hops: list[Hop] = []
    previous: Stop | None = None
    for b in chain:
        if b is None:
            continue
        stop = _linked(b)
        if stop is None:
            # A flight, a train or a plan with no place: where they are is unknown.
            if b.draft.kind is not BookingKind.HOTEL:
                previous = None
            continue
        if previous is not None and previous.place_id != stop.place_id:
            hops.append(Hop(previous, stop))
        previous = stop
    return hops[:MAX_HOPS]


def default_mode(metres: float | None) -> Mode:
    """Walking for a short hop, public transport for a longer one (or when the
    distance isn't known)."""
    return Mode.WALK if metres is not None and metres <= WALK_UP_TO else Mode.TRANSIT


def tight(hop: Hop, minutes: int) -> bool:
    """Whether getting there takes longer than the time between the two plans' start
    times (only when both have one)."""
    if hop.start.at is None or hop.end.at is None:
        return False
    gap = (hop.end.at.hour * 60 + hop.end.at.minute) - (
        hop.start.at.hour * 60 + hop.start.at.minute
    )
    return 0 <= gap < minutes


def directions_url(hop: Hop, mode: Mode) -> str:
    """Google Maps directions between the two places, which opens the Maps app on a
    phone."""
    query = urlencode(
        {
            "api": "1",
            "origin": hop.start.title,
            "origin_place_id": hop.start.place_id,
            "destination": hop.end.title,
            "destination_place_id": hop.end.place_id,
            "travelmode": _MAPS_MODE[mode],
        }
    )
    return f"https://www.google.com/maps/dir/?{query}"
