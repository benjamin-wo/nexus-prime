"""A trip day in order, and what to watch out for on it: clashes, plans out of time
order and free time. Every place, flight and time here is made up."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest

from nexus.domain.bookings import Booking, BookingDraft, BookingKind, Segment
from nexus.domain.errors import NotFound
from nexus.domain.itinerary import (
    NoteKind,
    day_notes,
    days_of,
    finish,
    match_entry,
    on_day,
    pick_slot,
    places_to_visit,
    usual_minutes,
)
from nexus.domain.ledger import UserId
from tests.fakes import NOW

USER = UserId(uuid4())
DAY = date(2026, 11, 12)


def entry(draft: BookingDraft, made: int = 0) -> Booking:
    return Booking(uuid4(), USER, uuid4(), None, draft, None, None, NOW + timedelta(minutes=made))


def plan(
    name: str,
    at: str | None = None,
    *,
    ends: str | None = None,
    order: int | None = None,
    follows: str | None = None,
    day: date | None = DAY,
    made: int = 0,
) -> Booking:
    draft = BookingDraft.from_dict(
        {"kind": "activity", "name": name, "day": day.isoformat() if day else None,
         "at": at, "ends_at": ends, "order": order, "follows": follows}
    )  # fmt: skip
    assert draft is not None
    return entry(draft, made)


def flight(departs: str, arrives: str) -> Booking:
    leg = Segment(
        "ZZ12", "Exampleton", "Otherville",
        datetime.fromisoformat(f"{DAY}T{departs}"), datetime.fromisoformat(f"{DAY}T{arrives}"),
    )  # fmt: skip
    return entry(BookingDraft(BookingKind.FLIGHT, "Acme Air", (leg,), None, None, None, None))


def hotel(name: str) -> Booking:
    draft = BookingDraft(BookingKind.HOTEL, None, (), name, None, DAY, DAY + timedelta(days=2))
    return entry(draft)


def titles(items: list[Booking]) -> list[str]:
    return [b.draft.title.split(",")[0] for b in items]


def test_a_day_nobody_rearranged_runs_by_time_as_before() -> None:
    day = [plan("Dinner", "19:00"), hotel("Hill Lodge"), plan("Walk"), flight("08:00", "09:30")]
    assert titles(on_day(day, DAY)) == [
        "Walk",
        "ZZ12 Exampleton → Otherville",
        "Hill Lodge",
        "Dinner",
    ]


def test_a_plan_with_no_time_stays_where_it_was_put_among_timed_entries() -> None:
    lands, lodge = flight("07:00", "09:15"), hotel("Hill Lodge")
    # Put right after landing: the 15:00 check-in comes after it.
    pickup = plan("Car pickup", order=0, follows="09:15")
    assert titles(on_day([lodge, pickup, lands], DAY)) == [
        "ZZ12 Exampleton → Otherville",
        "Car pickup",
        "Hill Lodge",
    ]
    # Put after the check-in: after it, though that's at the same 15:00.
    dinner = plan("Dinner", order=0, follows="15:00")
    assert titles(on_day([lodge, dinner, lands], DAY))[-1] == "Dinner"
    # Without the hint, as before: after the last timed entry.
    old = plan("Car pickup", order=0)
    assert titles(on_day([lodge, old, lands], DAY))[-1] == "Car pickup"
    # A time of its own wins: the hint isn't kept.
    assert plan("Car pickup", "16:00", follows="09:15").draft.follows is None


def test_once_rearranged_plans_keep_their_order_and_the_rest_slot_in_by_time() -> None:
    temple = plan("Old Temple", "09:00", order=1)
    market = plan("Night market", "18:00", order=0)  # put first by hand, though later
    lunch = plan("Noodle lunch", "12:00")  # added after the day was rearranged
    stroll = plan("A stroll")  # no time, no place in the order: last
    day = [temple, market, lunch, stroll, hotel("Hill Lodge"), flight("07:00", "08:00")]
    assert titles(on_day(day, DAY)) == [
        "ZZ12 Exampleton → Otherville",
        "Night market",
        "Old Temple",
        "Noodle lunch",
        "Hill Lodge",
        "A stroll",
    ]


def test_clashes_out_of_order_plans_and_free_time() -> None:
    tea = plan("Tea ceremony", "14:00", ends="15:30", order=0)
    museum = plan("Museum", "15:00", order=1)
    same = plan("Boat ride", "15:00", order=2)
    early = plan("Breakfast", "08:30", order=3)
    notes = day_notes(on_day([tea, museum, same, early], DAY), DAY)
    assert [(n.kind, n.text) for n in notes] == [
        (NoteKind.CLASH, "Tea ceremony (14:00 to 15:30) runs into Museum at 15:00"),
        (NoteKind.CLASH, "Museum and Boat ride both start at 15:00"),
        (NoteKind.ORDER, "Breakfast at 08:30 comes after Boat ride at 15:00 in your order"),
        (NoteKind.FREE, "Free 09:30 to 14:00"),
        (NoteKind.FREE, "Free 16:00 to 21:00"),
    ]
    free = notes[3]
    assert (free.start, free.end, free.ids) == (time(9, 30), time(14), ())
    # A day with nothing timed says nothing about free time.
    assert day_notes([plan("A stroll")], DAY) == []


def test_a_flight_takes_up_its_time() -> None:
    notes = day_notes(on_day([flight("10:00", "12:00"), plan("Lunch", "11:00")], DAY), DAY)
    assert notes[0].text == (
        "ZZ12 Exampleton → Otherville (10:00 to 12:00) runs into Lunch at 11:00"
    )


def test_new_fields_are_checked_as_they_are_read() -> None:
    kept = BookingDraft.from_dict(
        {"kind": "activity", "name": "Dinner", "day": "2026-11-12", "at": "19:00",
         "ends_at": "21:30", "link": "https://food.example.com/book", "list_name": "  Eat ",
         "order": 2}
    )  # fmt: skip
    assert kept is not None
    assert (kept.ends_at, kept.link, kept.list_name, kept.order) == (
        time(21, 30), "https://food.example.com/book", "Eat", 2,
    )  # fmt: skip
    assert kept.describe() == "plan (Dinner, Thu 12 Nov 19:00 to 21:30)"
    odd = BookingDraft.from_dict(
        {"kind": "activity", "name": "Dinner", "at": "19:00", "ends_at": "18:00",
         "link": "http://10.0.0.1/x", "order": -1}
    )  # fmt: skip
    assert odd is not None and (odd.ends_at, odd.link, odd.order) == (None, None, None)
    assert BookingDraft.from_dict(kept.as_dict()) == kept


def test_places_to_visit_keep_their_order_then_oldest_first() -> None:
    a = plan("Arcade", day=None, made=1)
    b = plan("Bakery", day=None, order=0, made=2)
    c = plan("Castle", day=None, made=0)
    assert titles(places_to_visit([a, b, c, plan("On a day")])) == ["Bakery", "Castle", "Arcade"]


def overnight(stations: tuple[tuple[str, str], ...] = ()) -> Booking:
    """A made-up overnight flight: leaves the evening before DAY, lands that morning."""
    leg = Segment(
        "ZZ378", "SIN", "BCN",
        datetime.fromisoformat(f"{DAY - timedelta(days=1)}T23:30"),
        datetime.fromisoformat(f"{DAY}T09:15"),
    )  # fmt: skip
    draft = BookingDraft(BookingKind.FLIGHT, "Acme Air", (leg,), None, None, None, None)
    return entry(replace(draft, stations=stations))


def test_an_overnight_flight_is_on_the_day_it_leaves_and_the_day_it_lands() -> None:
    away, lodge = overnight(), hotel("Hill Lodge")
    eve = DAY - timedelta(days=1)
    assert days_of([away, lodge]) == [eve, DAY]
    assert on_day([away, lodge], eve) == [away]
    assert on_day([away, lodge], DAY) == [away, lodge]  # lands 09:15, check-in 15:00


def test_landing_well_before_check_in_says_so_in_place_of_free_time() -> None:
    away, lodge = overnight(), hotel("Hill Lodge")
    notes = day_notes(on_day([away, lodge], DAY), DAY)
    assert [(n.kind, n.text) for n in notes] == [
        (
            NoteKind.ARRIVAL,
            "Land 09:15, check-in at Hill Lodge from 15:00: 5 h 45 min to fill, counting "
            "the way from the airport, or ask about checking in early",
        )
    ]
    assert (notes[0].ids, notes[0].start, notes[0].end) == (
        (away.id, lodge.id),
        time(9, 15),
        time(15),
    )
    # Landing after lunch: close enough to check-in for no arrival note; the evening
    # is free from landing.
    late = overnight()
    leg = replace(late.draft.segments[0], arrives=datetime.fromisoformat(f"{DAY}T13:30"))
    late = replace(late, draft=replace(late.draft, segments=(leg,)))
    later = day_notes(on_day([late, lodge], DAY), DAY)
    assert [(n.kind, n.text) for n in later] == [(NoteKind.FREE, "Free 13:30 to 21:00")]


def test_no_free_time_is_looked_for_outside_the_trips_days() -> None:
    eve = DAY - timedelta(days=1)
    day = on_day([overnight(), plan("Packing", "10:00", day=eve)], eve)
    assert [n.kind for n in day_notes(day, eve)] == [NoteKind.FREE]
    assert day_notes(day, eve, in_trip=False) == []


def test_airports_found_on_google_maps_are_kept_with_the_flight() -> None:
    away = overnight((("BCN airport", "fakePlaceAirport1"), ("SIN airport", "")))
    assert away.draft.station("BCN airport") == "fakePlaceAirport1"
    assert away.draft.station("SIN airport") == ""  # looked up, nothing found
    assert away.draft.station("LHR airport") is None  # not looked up
    assert BookingDraft.from_dict(away.draft.as_dict()) == away.draft
    odd = BookingDraft.from_dict({**away.draft.as_dict(), "stations": {"X": "not an id!", 3: "y"}})
    assert odd is not None and odd.stations == ()


# --- a time for a plan added without one ---------------------------------------------------


def slot_of(
    day: list[Booking],
    earliest: str = "09:00",
    minutes: int = 60,
    buffers: Mapping[UUID, int] | None = None,
    buffer: int = 15,
) -> tuple[str, str] | None:
    """The (start, end) picked on DAY, as 09:00-style text."""
    found = pick_slot(
        day,
        DAY,
        earliest=time.fromisoformat(earliest),
        minutes=minutes,
        buffers=buffers,
        buffer=buffer,
    )
    return None if found is None else (f"{found.start:%H:%M}", f"{found.end:%H:%M}")


def test_an_empty_day_takes_the_earliest_on_the_next_quarter_hour() -> None:
    assert slot_of([]) == ("09:00", "10:00")
    assert slot_of([], "09:01") == ("09:15", "10:15")
    assert slot_of([], "13:45", 20) == ("13:45", "14:05")
    # Seconds count: 14:00:30 is past 14:00.
    found = pick_slot([], DAY, earliest=time(14, 0, 30), minutes=30)
    assert found is not None and found.start == time(14, 15) and found.end == time(14, 45)
    assert found.previous is None and found.next is None


def test_the_first_gap_that_fits_with_room_either_side() -> None:
    museum, lunch = plan("Museum", "09:00", ends="10:00"), plan("Lunch", "13:00", ends="14:00")
    day = [lunch, museum]
    found = pick_slot(day, DAY, earliest=time(9), minutes=60)
    assert found is not None and (found.start, found.end) == (time(10, 15), time(11, 15))
    assert found.previous is museum and found.next is lunch
    # It must end 15 minutes before lunch, so 150 minutes is the longest that fits.
    assert slot_of(day, minutes=150) == ("10:15", "12:45")
    assert slot_of(day, minutes=165) == ("14:15", "17:00")  # after lunch instead


def test_now_in_the_middle_of_a_plan_starts_after_it() -> None:
    day = [plan("Tour", "10:00", ends="12:00")]
    assert slot_of(day, "10:30") == ("12:15", "13:15")
    assert slot_of(day, "09:00", 30) == ("09:00", "09:30")
    assert slot_of(day, "09:00", 45) == ("09:00", "09:45")  # ends 15 minutes before: just fits
    assert slot_of(day, "09:00", 50) == ("12:15", "13:05")  # too close to the tour


def test_after_an_entry_means_starting_at_its_end_plus_room() -> None:
    day = [plan("Castle", "10:00", ends="11:30")]
    assert slot_of(day, "11:30", 20) == ("11:45", "12:05")
    assert slot_of(day, "11:45", 20) == ("11:45", "12:05")


def test_travel_buffers_of_the_neighbours_are_kept() -> None:
    first, second = plan("Market", "09:00", ends="10:00"), plan("Dinner", "12:00", ends="13:00")
    day = [first, second]
    assert slot_of(day) == ("10:15", "11:15")
    assert slot_of(day, buffers={first.id: 45}) == ("10:45", "11:45")
    assert slot_of(day, buffer=30) == ("10:30", "11:30")
    # Dinner is 45 minutes away: 60 minutes still fits before it, 75 no longer does.
    assert slot_of(day, minutes=60, buffers={second.id: 45}) == ("10:15", "11:15")
    assert slot_of(day, minutes=75, buffers={second.id: 45}) == ("13:45", "15:00")


def test_flights_and_trains_block_but_hotels_and_untimed_plans_do_not() -> None:
    train = flight("13:30", "14:30")
    dinner, lodge, wander = plan("Dinner", "20:00"), hotel("Hill Lodge"), plan("Wander")
    day = [dinner, train, lodge, wander]
    found = pick_slot(day, DAY, earliest=time(9), minutes=90)
    assert found is not None and (found.start, found.end) == (time(9), time(10, 30))
    assert found.previous is None and found.next is train
    # From 12:00 there are no 90 minutes before the train: after it, before dinner.
    later = pick_slot(day, DAY, earliest=time(12), minutes=90)
    assert later is not None and (later.start, later.end) == (time(14, 45), time(16, 15))
    assert later.previous is train and later.next is dinner
    # The check-in at 15:00 is not an appointment.
    assert slot_of([lodge], "15:00") == ("15:00", "16:00")


def test_a_plan_with_no_end_takes_its_categorys_usual_time() -> None:
    usual = [usual_minutes(c) for c in ("Sight", "food", "Shopping", "Nature", "Nightlife")]
    assert usual == [90, 60, 60, 120, 90]
    assert usual_minutes(None) == usual_minutes("Spa") == 60
    draft = BookingDraft.from_dict(
        {"kind": "activity", "name": "Hill Fort", "day": DAY.isoformat(), "at": "10:00",
         "category": "Sight"}
    )  # fmt: skip
    assert draft is not None
    fort = entry(draft)
    assert finish(fort, DAY) == time(11, 30)
    assert finish(plan("Tea", "10:00", ends="10:40"), DAY) == time(10, 40)
    assert finish(plan("Tea", "10:00"), DAY) == time(11, 0)
    assert finish(hotel("Hill Lodge"), DAY) is None and finish(plan("Wander"), DAY) is None
    assert slot_of([fort], "10:00", 30) == ("11:45", "12:15")


def test_when_nothing_fits_before_eleven_at_night_there_is_no_slot() -> None:
    assert slot_of([], "21:45") == ("21:45", "22:45")
    assert slot_of([], "22:00") == ("22:00", "23:00")  # ending at 23:00 is fine
    assert slot_of([], "22:15") is None
    assert slot_of([], "23:50", 10) is None
    assert slot_of([], "09:00", 600) == ("09:00", "19:00")
    assert slot_of([plan("All day", "09:00", ends="23:00")]) is None
    gap = [plan("Early", "09:00", ends="12:00"), plan("Late", "12:30", ends="23:00")]
    assert slot_of(gap, minutes=10) is None  # 12:15 to 12:25 runs into the room before 12:30


def test_the_day_an_overnight_flight_lands_starts_when_it_lands() -> None:
    away = overnight()  # lands 09:15 on DAY, so it takes the day from midnight until then
    found = pick_slot([away], DAY, earliest=time(4), minutes=60)
    assert found is not None and (found.start, found.end) == (time(9, 30), time(10, 30))
    assert found.previous is away
    # The evening it leaves (23:30 to the end of the day) is free until the flight.
    eve = DAY - timedelta(days=1)
    leaves = pick_slot([away], eve, earliest=time(21), minutes=90)
    assert leaves is not None and (leaves.start, leaves.end) == (time(21), time(22, 30))
    assert leaves.next is away


def test_a_flight_that_lands_after_midnight_blocks_the_rest_of_its_day() -> None:
    leg = Segment(
        "ZZ99", "Exampleton", "Otherville",
        datetime.fromisoformat(f"{DAY}T22:00"),
        datetime.fromisoformat(f"{DAY + timedelta(days=1)}T06:00"),
    )  # fmt: skip
    out = entry(BookingDraft(BookingKind.FLIGHT, "Acme Air", (leg,), None, None, None, None))
    assert finish(out, DAY) == time(23, 59)
    assert slot_of([out], "19:00", 90) == ("19:00", "20:30")
    assert slot_of([out], "19:00", 180) is None  # nothing is left after it


def test_match_entry_finds_the_one_entry_or_says_what_there_is() -> None:
    fort, garden = plan("Hill Fort"), plan("Hill Garden")
    assert match_entry([fort, garden], "fort") is fort
    with pytest.raises(NotFound, match="matches 'hill'; the itinerary has: Hill Fort; Hill Garden"):
        match_entry([fort, garden], "hill")
    with pytest.raises(NotFound, match="Fri 13 Nov has: nothing yet"):
        match_entry([], "x", has="Fri 13 Nov has")
