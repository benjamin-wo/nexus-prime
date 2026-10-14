"""Getting from one stop to the next on a trip day. Pure rules, no I/O.

A day's stops are its plans and hotels linked to a Google Maps place, in the order
the itinerary shows them (``domain.itinerary.on_day``), starting at the hotel
slept in the night before and ending at the one slept in that night. A flight or
train adds the airport or station it leaves from (the last stop before it) and the
one it lands at (the first stop after it), once found on Google Maps; nothing is
worked out across the journey itself. A plan with no place breaks the chain, since
where the traveller is then isn't known.

Longer hops go by public transport, or by car when the trip says it has one; a way
the user picked for a hop is kept and used again.
"""

import re
from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import StrEnum
from urllib.parse import urlencode
from uuid import UUID

from nexus.domain.bookings import Booking, BookingKind, Segment
from nexus.domain.itinerary import landing, leaving, on_day
from nexus.domain.trips import GettingAround

# Up to this far apart (in a straight line), a hop is walked by default.
WALK_UP_TO = 1500
# A place this close to an airport is part of being there (a car hire desk, an airport
# hotel): the way between the two isn't worth a travel time.
AIRPORT_SIDE = 3000
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
    at: time | None  # when a plan starts, a flight leaves or lands, if known


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


def station_query(kind: BookingKind, name: str | None) -> str | None:
    """What to search Google Maps for to find where a flight or train leaves or lands:
    "BCN airport", "Kyoto station"."""
    name = " ".join((name or "").split())
    if not name:
        return None
    word = "airport" if kind is BookingKind.FLIGHT else "station"
    return name if word in name.casefold() else f"{name} {word}"


def stations_on(b: Booking, day: date) -> tuple[str | None, str | None]:
    """The airport or station a flight or train leaves from on ``day`` and the one it
    lands at that day, as searched for on Google Maps."""
    out, back = leaving(b, day), landing(b, day)
    return (
        station_query(b.draft.kind, out[0].origin) if out else None,
        station_query(b.draft.kind, back[-1].destination) if back else None,
    )


def _station(b: Booking, name: str | None, leg: Segment | None, *, lands: bool) -> Stop | None:
    pid = b.draft.station(name) if name else None
    if not pid or leg is None:
        return None
    when = leg.arrives if lands else leg.departs
    return Stop(b.id, pid, name or "", when.time() if when else None)


def day_hops(bookings: list[Booking], day: date) -> list[Hop]:
    """The hops on ``day``, in order: one per pair of consecutive stops with nothing
    unknown between them (a flight or train in progress, an unplaced plan), and never
    from a place to itself."""
    hotels = [b for b in bookings if b.draft.kind is BookingKind.HOTEL]
    morning = next((b for b in hotels if _night(b, day - timedelta(days=1))), None)
    tonight = next((b for b in hotels if _night(b, day)), None)
    entries = on_day(bookings, day)
    hops: list[Hop] = []
    previous: Stop | None = None

    def reach(stop: Stop) -> None:
        nonlocal previous
        if previous is not None and previous.place_id != stop.place_id:
            hops.append(Hop(previous, stop))
        previous = stop

    for b in [morning, *entries, tonight]:
        if b is None:
            continue
        if b.draft.kind in (BookingKind.FLIGHT, BookingKind.RAIL):
            leave, land = stations_on(b, day)
            out, back = leaving(b, day), landing(b, day)
            gone = _station(b, leave, out[0] if out else None, lands=False)
            if gone is not None:
                reach(gone)  # to the airport or station
            previous = None  # on the way: nothing is worked out across the journey
            arrived = _station(b, land, back[-1] if back else None, lands=True)
            if arrived is not None:
                previous = arrived
            continue
        stop = _linked(b)
        if stop is None:
            # A plan with no place: where they are is unknown.
            if b.draft.kind is not BookingKind.HOTEL:
                previous = None
            continue
        reach(stop)
    return hops[:MAX_HOPS]


def beside_airport(hop: Hop, metres: float | None, flights: set[UUID]) -> bool:
    """Whether a hop only goes between an airport and a place right beside it."""
    at_airport = hop.start.booking_id in flights or hop.end.booking_id in flights
    return at_airport and metres is not None and metres <= AIRPORT_SIDE


def hop_key(hop: Hop) -> str:
    """How a hop is known when the way the user picked for it is kept."""
    return f"{hop.start.booking_id}:{hop.end.booking_id}"


_CAR = r"(?:car|rental|hire|vehicle)"


def _either_way(action: str) -> re.Pattern[str]:
    """The car and the action named in either order: "car return", "return the car"."""
    return re.compile(rf"\b(?:{_CAR}\b.*\b{action}|{action}\b.*\b{_CAR})\b", re.I)


_PICKUP = _either_way(r"(?:pick[- ]?up|collect(?:ion)?)")
_RETURN = _either_way(r"(?:return|drop[- ]?off)")


def without_the_car(hop: Hop) -> bool:
    """A hop made without the hire car: to where it's picked up, or on from where it's
    handed back ("Car pickup", "Car return — Barcelona Airport T1")."""
    return bool(_PICKUP.search(hop.end.title) or _RETURN.search(hop.start.title))


def default_mode(metres: float | None, by: GettingAround = GettingAround.TRANSIT) -> Mode:
    """Walking for a short hop; for a longer one (or when the distance isn't known),
    public transport, or driving on a trip with a car."""
    if metres is not None and metres <= WALK_UP_TO:
        return Mode.WALK
    return Mode.DRIVE if by is GettingAround.CAR else Mode.TRANSIT


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
