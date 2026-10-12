"""A trip day's itinerary in order, and what to watch out for on it. Pure rules, no I/O.

Until the user rearranges a day, it runs by time, as it always has: each entry at its
time (a hotel check-in at 15:00, a plan with no time first). Once a plan has been
moved, the day's plans keep the user's order and flights, trains and hotel check-ins
slot in by their times; a plan added later without a place in that order goes where
its time fits (one with no time goes last).

Each day can carry notes, worked out here and shown on the trip page and in chat:
two things that overlap, a plan that comes after a later one in the user's order, and
three hours or more of free time between 09:00 and 21:00.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from itertools import pairwise
from uuid import UUID

from nexus.domain.bookings import Booking, BookingKind

CHECK_IN = time(15, 0)
# Free time worth saying, and the part of the day it's looked for in.
FREE_FOR = timedelta(hours=3)
DAY_STARTS, DAY_ENDS = time(9, 0), time(21, 0)
# A plan with a start and no end is taken to last this long when looking for free time.
USUAL_LENGTH = timedelta(hours=1)
MAX_NOTES = 5


class NoteKind(StrEnum):
    CLASH = "clash"  # two entries overlap
    ORDER = "order"  # a plan comes after a later one in the user's order
    FREE = "free"  # three hours or more with nothing planned


@dataclass(frozen=True, slots=True)
class DayNote:
    kind: NoteKind
    text: str
    ids: tuple[UUID, ...] = ()  # the entries it's about
    start: time | None = None  # free time: from
    end: time | None = None  # free time: until


def _time(b: Booking) -> time | None:
    """When an entry happens on its first day: a plan's time, a flight or train's
    departure, a hotel's check-in."""
    d = b.draft
    if d.kind is BookingKind.ACTIVITY:
        return d.at
    if d.kind is BookingKind.HOTEL:
        return CHECK_IN
    departs = next((s.departs for s in d.segments if s.departs), None)
    return departs.time() if isinstance(departs, datetime) else None


def _by_time(b: Booking) -> str:
    return f"{b.draft.starts}T{(_time(b) or time(0)).isoformat()}"


def on_day(bookings: Sequence[Booking], day: date) -> list[Booking]:
    """Everything that starts on ``day``, in itinerary order."""
    entries = [b for b in bookings if b.draft.starts == day]
    plans = [b for b in entries if b.draft.kind is BookingKind.ACTIVITY]
    ordered = sorted((p for p in plans if p.draft.order is not None), key=_order_key)
    if not ordered:
        return sorted(entries, key=_by_time)
    arranged = list(ordered)
    unordered = (p for p in plans if p.draft.order is None)
    for b in sorted(unordered, key=lambda p: (p.draft.at is None, _by_time(p))):
        _fit(arranged, b, end_if_untimed=True)
    for b in sorted((e for e in entries if e.draft.kind is not BookingKind.ACTIVITY), key=_by_time):
        _fit(arranged, b, end_if_untimed=False)
    return arranged


def places_to_visit(bookings: Sequence[Booking]) -> list[Booking]:
    """Plans with no day yet, in the user's order (then oldest first)."""
    places = [b for b in bookings if b.draft.kind is BookingKind.ACTIVITY and b.draft.day is None]
    return sorted(places, key=lambda b: (b.draft.order is None, b.draft.order or 0, b.created_at))


def _order_key(b: Booking) -> tuple[int, str]:
    return (b.draft.order or 0, _by_time(b))


def _fit(arranged: list[Booking], b: Booking, *, end_if_untimed: bool) -> None:
    """Puts ``b`` right after the last entry with a time no later than its own."""
    at = _time(b)
    if at is None:
        if end_if_untimed:
            arranged.append(b)
        else:
            arranged.insert(0, b)
        return
    after = -1
    for i, e in enumerate(arranged):
        when = _time(e)
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
    leg = next((s for s in d.segments if s.departs and s.departs.date() == day), None)
    if leg is None or leg.departs is None:
        return None
    arrives = leg.arrives
    ends = arrives.time() if arrives and arrives.date() == day else time(23, 59)
    return leg.departs.time(), ends


def day_notes(arranged: Sequence[Booking], day: date) -> list[DayNote]:
    """What to watch out for on ``day``, given its entries in itinerary order."""
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
