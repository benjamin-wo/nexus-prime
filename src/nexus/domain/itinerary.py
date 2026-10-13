"""A trip day's itinerary in order, and what to watch out for on it. Pure rules, no I/O.

Until the user rearranges a day, it runs by time, as it always has: each entry at its
time (a hotel check-in at 15:00, a plan with no time first). Once a plan has been
moved, the day's plans keep the user's order and flights, trains and hotel check-ins
slot in by their times; a plan added later without a place in that order goes where
its time fits (one with no time goes last).

A flight or train is on every day one of its legs leaves or lands: an overnight
flight shows where it leaves, at its departure, and on the next day where it lands,
at its arrival.

Each day can carry notes, worked out here and shown on the trip page and in chat:
two things that overlap, a plan that comes after a later one in the user's order,
landing well before the hotel's check-in, and three hours or more of free time
between 09:00 and 21:00 (not on a day spent arriving, nor outside the trip's dates).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from itertools import pairwise
from uuid import UUID

from nexus.domain.bookings import Booking, BookingKind, Segment

CHECK_IN = time(15, 0)
# Free time worth saying, and the part of the day it's looked for in.
FREE_FOR = timedelta(hours=3)
DAY_STARTS, DAY_ENDS = time(9, 0), time(21, 0)
# A plan with a start and no end is taken to last this long when looking for free time.
USUAL_LENGTH = timedelta(hours=1)
MAX_NOTES = 5
# Landing at least this long before the hotel's check-in is worth a note.
EARLY_BY = timedelta(hours=2)


class NoteKind(StrEnum):
    CLASH = "clash"  # two entries overlap
    ORDER = "order"  # a plan comes after a later one in the user's order
    FREE = "free"  # three hours or more with nothing planned
    ARRIVAL = "arrival"  # landing well before the hotel's check-in


@dataclass(frozen=True, slots=True)
class DayNote:
    kind: NoteKind
    text: str
    ids: tuple[UUID, ...] = ()  # the entries it's about
    start: time | None = None  # free time: from; arrival: landing
    end: time | None = None  # free time: until; arrival: check-in


def _transport(b: Booking) -> bool:
    return b.draft.kind in (BookingKind.FLIGHT, BookingKind.RAIL)


def leaving(b: Booking, day: date) -> list[Segment]:
    """A flight's or train's legs that leave on ``day``."""
    return [s for s in b.draft.segments if s.departs and s.departs.date() == day]


def landing(b: Booking, day: date) -> list[Segment]:
    """A flight's or train's legs that land on ``day``."""
    return [s for s in b.draft.segments if s.arrives and s.arrives.date() == day]


def _on(b: Booking, day: date) -> bool:
    if _transport(b):
        return bool(leaving(b, day) or landing(b, day))
    return b.draft.starts == day


def _time(b: Booking, day: date) -> time | None:
    """When an entry happens on ``day``: a plan's time, a hotel's check-in, a flight's
    or train's first departure that day, or else its landing."""
    d = b.draft
    if d.kind is BookingKind.ACTIVITY:
        return d.at
    if d.kind is BookingKind.HOTEL:
        return CHECK_IN
    out = [s.departs for s in leaving(b, day) if s.departs]
    if out:
        return min(out).time()
    back = [s.arrives for s in landing(b, day) if s.arrives]
    return max(back).time() if back else None


def on_day(bookings: Sequence[Booking], day: date) -> list[Booking]:
    """Everything on ``day``, in itinerary order: what starts that day, and flights
    and trains landing that day."""
    entries = [b for b in bookings if _on(b, day)]

    def by_time(b: Booking) -> time:
        return _time(b, day) or time(0)

    plans = [b for b in entries if b.draft.kind is BookingKind.ACTIVITY]
    placed = (p for p in plans if p.draft.order is not None)
    ordered = sorted(placed, key=lambda p: (p.draft.order or 0, by_time(p)))
    if not ordered:
        return sorted(entries, key=by_time)
    arranged = list(ordered)
    unordered = (p for p in plans if p.draft.order is None)
    for b in sorted(unordered, key=lambda p: (p.draft.at is None, by_time(p))):
        _fit(arranged, b, day, end_if_untimed=True)
    others = (e for e in entries if e.draft.kind is not BookingKind.ACTIVITY)
    for b in sorted(others, key=by_time):
        _fit(arranged, b, day, end_if_untimed=False)
    return arranged


def days_of(bookings: Sequence[Booking]) -> list[date]:
    """Every day something is on, in order: each entry's first day, and every day a
    flight's or train's leg leaves or lands."""
    days = {b.draft.starts for b in bookings if b.draft.starts is not None}
    for b in bookings:
        if _transport(b):
            days.update(t.date() for s in b.draft.segments for t in (s.departs, s.arrives) if t)
    return sorted(days)


def places_to_visit(bookings: Sequence[Booking]) -> list[Booking]:
    """Plans with no day yet, in the user's order (then oldest first)."""
    places = [b for b in bookings if b.draft.kind is BookingKind.ACTIVITY and b.draft.day is None]
    return sorted(places, key=lambda b: (b.draft.order is None, b.draft.order or 0, b.created_at))


def _when(b: Booking, day: date) -> tuple[time, int] | None:
    """Where an entry falls in the day: its time, or for a plan with none, just after
    the time it was put after (so a check-in at that same time comes before it)."""
    at = _time(b, day)
    if at is not None:
        return (at, 0)
    follows = b.draft.follows if b.draft.kind is BookingKind.ACTIVITY else None
    return (follows, 1) if follows is not None else None


def follows_at(arranged: Sequence[Booking], day: date) -> time:
    """For a plan with no time put at the end of ``arranged``: the time it comes after,
    from the last entry with one (midnight when there's none)."""
    for e in reversed(arranged):
        when = _when(e, day)
        if when is not None:
            return when[0]
    return time(0)


def _fit(arranged: list[Booking], b: Booking, day: date, *, end_if_untimed: bool) -> None:
    """Puts ``b`` right after the last entry that falls no later than it."""
    at = _when(b, day)
    if at is None:
        if end_if_untimed:
            arranged.append(b)
        else:
            arranged.insert(0, b)
        return
    after = -1
    for i, e in enumerate(arranged):
        when = _when(e, day)
        if when is not None and when <= at:
            after = i
    arranged.insert(after + 1, b)


def _span(b: Booking, day: date) -> tuple[time, time | None] | None:
    """When an entry starts and ends on ``day``, if it has a time that day. Hotels are
    left out: a check-in isn't an appointment."""
    d = b.draft
    if d.kind is BookingKind.ACTIVITY:
        return (d.at, d.ends_at) if d.at else None
    if d.kind is BookingKind.HOTEL:
        return None
    out = leaving(b, day)
    if out and out[0].departs:
        arrives = out[-1].arrives
        ends = arrives.time() if arrives and arrives.date() == day else time(23, 59)
        return out[0].departs.time(), ends
    back = [s.arrives for s in landing(b, day) if s.arrives]
    # Landing after a night away: taken up from midnight until it lands.
    return (time(0), max(back).time()) if back else None


def _arrival(arranged: Sequence[Booking], day: date) -> DayNote | None:
    """Landing well before the hotel the traveller checks into that day lets them in."""
    lands = [
        (max(arrived).time(), b)
        for b in arranged
        if _transport(b) and (arrived := [s.arrives for s in landing(b, day) if s.arrives])
    ]
    hotel = next((b for b in arranged if b.draft.kind is BookingKind.HOTEL), None)
    if not lands or hotel is None:
        return None
    at, flight = max(lands, key=lambda t: t[0])
    wait = datetime.combine(day, CHECK_IN) - datetime.combine(day, at)
    if wait < EARLY_BY:
        return None
    via = "airport" if flight.draft.kind is BookingKind.FLIGHT else "station"
    name = hotel.draft.hotel or "the hotel"
    return DayNote(
        NoteKind.ARRIVAL,
        f"Land {at:%H:%M}, check-in at {name} from {CHECK_IN:%H:%M}: {_length(wait)} to fill, "
        f"counting the way from the {via}, or ask about checking in early",
        (flight.id, hotel.id),
        start=at,
        end=CHECK_IN,
    )


def _length(span: timedelta) -> str:
    hours, minutes = divmod(int(span.total_seconds()) // 60, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def day_notes(arranged: Sequence[Booking], day: date, *, in_trip: bool = True) -> list[DayNote]:
    """What to watch out for on ``day``, given its entries in itinerary order. Free
    time is only looked for on the trip's own days."""
    notes: list[DayNote] = []
    timed = [(b, s) for b in arranged if (s := _span(b, day)) is not None]
    by_start = sorted(timed, key=lambda t: t[1][0])
    for (a, (a_start, a_end)), (b, (b_start, _)) in pairwise(by_start):
        if a_start == b_start:
            notes.append(
                DayNote(
                    NoteKind.CLASH,
                    f"{a.draft.title} and {b.draft.title} both start at {a_start:%H:%M}",
                    (a.id, b.id),
                )
            )
        elif a_end is not None and a_end > b_start:
            notes.append(
                DayNote(
                    NoteKind.CLASH,
                    f"{a.draft.title} ({a_start:%H:%M} to {a_end:%H:%M}) runs into "
                    f"{b.draft.title} at {b_start:%H:%M}",
                    (a.id, b.id),
                )
            )
    plans = [b for b in arranged if b.draft.kind is BookingKind.ACTIVITY and b.draft.at]
    for a, b in pairwise(plans):
        if a.draft.at and b.draft.at and b.draft.at < a.draft.at:
            notes.append(
                DayNote(
                    NoteKind.ORDER,
                    f"{b.draft.title} at {b.draft.at:%H:%M} comes after {a.draft.title} at "
                    f"{a.draft.at:%H:%M} in your order",
                    (a.id, b.id),
                )
            )
    arrival = _arrival(arranged, day)
    if arrival is not None:
        notes.append(arrival)  # the time before check-in is what's free that day
    elif in_trip:
        notes.extend(_free(timed, day))
    return notes[:MAX_NOTES]


def _free(timed: list[tuple[Booking, tuple[time, time | None]]], day: date) -> list[DayNote]:
    if not timed:
        return []  # a day with no times is all free; saying so helps nobody

    def at(t: time) -> datetime:
        return datetime.combine(day, t)

    busy = sorted(
        (at(start), at(end) if end else at(start) + USUAL_LENGTH) for _, (start, end) in timed
    )
    free: list[DayNote] = []
    cursor = at(DAY_STARTS)
    for start, end in [*busy, (at(DAY_ENDS), at(DAY_ENDS))]:
        start = min(max(start, at(DAY_STARTS)), at(DAY_ENDS))
        if start - cursor >= FREE_FOR:
            free.append(
                DayNote(
                    NoteKind.FREE,
                    f"Free {cursor:%H:%M} to {start:%H:%M}",
                    start=cursor.time(),
                    end=start.time(),
                )
            )
        cursor = max(cursor, min(end, at(DAY_ENDS)))
    return free


def renumber(plans: Sequence[Booking]) -> dict[UUID, int]:
    """Each plan's new place, 0 first, for the plans in the order given."""
    return {b.id: i for i, b in enumerate(plans)}
