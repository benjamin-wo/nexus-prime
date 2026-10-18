"""Suggested stops: where a trip is, worked out from its hotel stays. Pure rules, no I/O.

A run of stays in the same place is one stop; the day one stop ends and the next one
starts is the travel day between them. The user can set their own stops instead
(``Trip.stops``); until they do, these follow the hotels.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from nexus.domain.bookings import Booking, BookingKind
from nexus.domain.trips import MAX_STOP_NAME, MAX_STOPS, Stop, Trip

# A postcode or house number in an address part: a word with digits in it.
_CODE = re.compile(r"\b(?=[\w-]*\d)[\w-]+\b")


def address_place(address: str | None) -> str | None:
    """The last part of an address that names a place ("12 Example St, Kyoto 605-0001"
    gives "Kyoto"), without postcodes or numbers."""
    for part in reversed((address or "").split(",")):
        name = " ".join(_CODE.sub(" ", part).split())
        if name:
            return name[:MAX_STOP_NAME].strip()
    return None


def _destination(trip: Trip) -> str:
    return " ".join(trip.destination.split())[:MAX_STOP_NAME].strip() or "Trip"


def suggest_stops(
    trip: Trip, bookings: Sequence[Booking], cities: Mapping[str, str]
) -> tuple[Stop, ...]:
    """Stops from the trip's hotel stays. A stay's place is its Google Maps city
    (``cities``, by place id) when it's linked, else the last part of its address, else
    the trip's destination. A trip with no stays is one stop, the destination."""
    stays = sorted(
        (
            b.draft
            for b in bookings
            if b.draft.kind is BookingKind.HOTEL and b.draft.check_in is not None
        ),
        key=lambda d: (d.check_in or trip.start, d.check_out or trip.start),
    )
    runs: list[tuple[str, date, date]] = []
    for d in stays:
        if d.check_in is None:
            continue
        # Clipped to the trip's days; a stay wholly outside them says nothing about it.
        start = max(d.check_in, trip.start)
        end = min(d.check_out or d.check_in + timedelta(days=1), trip.end)
        if start > trip.end or end < trip.start:
            continue
        name = (
            (cities.get(d.place_id) if d.place_id else None)
            or address_place(d.address)
            or _destination(trip)
        )[:MAX_STOP_NAME].strip()
        if runs and runs[-1][0].casefold() == name.casefold():
            runs[-1] = (runs[-1][0], runs[-1][1], max(runs[-1][2], end))
        else:
            runs.append((name, start, end))

    stops: list[Stop] = []
    for name, start, end in runs:
        if stops and start < stops[-1].end:
            start = stops[-1].end  # overlapping stays: this one starts as the last ends
        if end < start:
            continue
        # A stay with no nights inside the trip is kept only for a day of its own: an
        # arrival after the trip began, not on the day another stop started.
        if end == start and (start == trip.start or (stops and stops[-1].start == start)):
            continue
        stops.append(Stop(name, start, end))
    if not stops:
        return (Stop(_destination(trip), trip.start, trip.end),)
    stops = stops[:MAX_STOPS]
    # The first stop is where the trip begins and the last where it ends, whatever days
    # the hotels cover (the flight out, a late check-out).
    stops[0] = Stop(stops[0].name, trip.start, stops[0].end)
    stops[-1] = Stop(stops[-1].name, stops[-1].start, trip.end)
    return tuple(stops)
