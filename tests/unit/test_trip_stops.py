"""A trip's stops: cleaned when set, and suggested from its hotel stays. Every place and
booking here is made up."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from nexus.domain.bookings import Booking, BookingDraft
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.stops import address_place, suggest_stops
from nexus.domain.trips import Stop, Trip, clean_stops

USER = UserId(uuid4())
MADE = datetime(2026, 9, 28, tzinfo=UTC)


def trip(start: date = date(2026, 12, 10), end: date = date(2026, 12, 20)) -> Trip:
    return Trip(uuid4(), USER, "Exampleland", start, end, "JPY", None, (), None, {}, MADE, MADE)


def stay(
    check_in: str,
    check_out: str | None,
    *,
    address: str | None = None,
    place_id: str | None = None,
    name: str = "Hotel Sakura",
) -> Booking:
    draft = BookingDraft.from_dict(
        {"kind": "hotel", "hotel": name, "check_in": check_in, "check_out": check_out,
         "address": address, "place_id": place_id}
    )  # fmt: skip
    assert draft is not None
    return Booking(uuid4(), USER, None, None, draft, None, None, MADE)


def d(day: int) -> date:
    return date(2026, 12, day)


def shown(stops: tuple[Stop, ...]) -> list[tuple[str, int, int]]:
    return [(s.name, s.start.day, s.end.day) for s in stops]


# --- clean_stops --------------------------------------------------------------------


def test_stops_are_named_dated_inside_the_trip_and_kept_in_order() -> None:
    cleaned = clean_stops(
        trip(), [Stop(" Kyoto  ", d(14), d(20)), Stop("Tokyo", d(10), d(14))]
    )  # the travel day, the 14th, is shared
    assert shown(cleaned) == [("Tokyo", 10, 14), ("Kyoto", 14, 20)]
    assert [s.nights for s in cleaned] == [4, 6]
    assert clean_stops(trip(), []) == ()  # none: back to the hotels'
    assert clean_stops(trip(), [Stop("Day trip", d(12), d(12))]) == (
        Stop("Day trip", d(12), d(12)),
    )


@pytest.mark.parametrize(
    ("stops", "message"),
    [
        ([Stop("Tokyo", d(10), d(15)), Stop("Kyoto", d(14), d(20))], "overlap"),
        ([Stop("Tokyo", d(10), d(15)), Stop("Kyoto", d(10), d(20))], "overlap"),
        ([Stop("Tokyo", d(9), d(15))], "outside the trip's dates"),
        ([Stop("Tokyo", d(15), d(21))], "outside the trip's dates"),
        ([Stop("Tokyo", d(15), d(12))], "ends before it starts"),
        ([Stop("  ", d(10), d(12))], "needs a name"),
        ([Stop("x" * 41, d(10), d(12))], "at most 40 characters"),
        ([Stop(f"S{n}", d(10), d(10)) for n in range(11)], "at most 10 stops"),
    ],
)
def test_stops_that_overlap_or_leave_the_trip_are_refused(stops: list[Stop], message: str) -> None:
    with pytest.raises(InvalidInput, match=message):
        clean_stops(trip(), stops)


def test_ten_stops_are_allowed() -> None:
    stops = [Stop(f"S{n}", d(10 + n), d(11 + n)) for n in range(10)]
    assert len(clean_stops(trip(), stops)) == 10


# --- suggest_stops --------------------------------------------------------------------


def test_one_city_is_one_stop_named_by_its_hotels_city() -> None:
    stays = [
        stay("2026-12-10", "2026-12-14", place_id="fakePlaceHotel1"),
        stay("2026-12-14", "2026-12-19", place_id="fakePlaceHotel2", name="Hotel Maple"),
    ]
    # Hotels in different neighbourhoods of one city (the areas never reach here).
    found = suggest_stops(trip(), stays, {"fakePlaceHotel1": "Tokyo", "fakePlaceHotel2": "tokyo"})
    assert shown(found) == [("Tokyo", 10, 20)]  # a run in one place; the trip's own ends


def test_two_cities_with_a_travel_day_between() -> None:
    stays = [
        stay("2026-12-14", "2026-12-19", address="5 Example Lane, Kyoto 605-0001"),
        stay("2026-12-10", "2026-12-14", address="1 Example Street, Tokyo"),
    ]
    found = suggest_stops(trip(), stays, {})
    # The 14th is the day one ends and the other starts; the trip's first and last days
    # belong to the first and last stop (the flight out, the late check-out).
    assert shown(found) == [("Tokyo", 10, 14), ("Kyoto", 14, 20)]
    assert clean_stops(trip(), found) == found  # what's suggested is always valid


def test_the_name_falls_back_from_city_to_address_to_the_destination() -> None:
    stays = [
        stay("2026-12-10", "2026-12-12", place_id="fakePlaceHotel1", address="9 Example St, Osaka"),
        stay("2026-12-12", "2026-12-15", address="9 Example St, Nara 630-8213"),
        stay("2026-12-15", "2026-12-18"),
    ]
    found = suggest_stops(trip(), stays, {"fakePlaceHotel1": "Namba"})
    assert [s.name for s in found] == ["Namba", "Nara", "Exampleland"]
    # A linked place Google Maps couldn't give a city for falls back to the address.
    assert suggest_stops(trip(), stays[:1], {})[0].name == "Osaka"


def test_a_trip_with_no_stays_is_one_stop_the_destination() -> None:
    assert shown(suggest_stops(trip(), [], {})) == [("Exampleland", 10, 20)]
    # Stays wholly outside the trip say nothing about it.
    early = stay("2026-12-01", "2026-12-05", address="Somewhere, Elsewhere")
    assert shown(suggest_stops(trip(), [early], {})) == [("Exampleland", 10, 20)]


def test_stays_are_cut_to_the_trip_and_overlaps_start_as_the_last_ends() -> None:
    stays = [
        stay("2026-12-08", "2026-12-13", address="1 A St, Tokyo"),  # arrived early
        stay("2026-12-12", "2026-12-18", address="2 B St, Kyoto"),  # booked a night early
        stay("2026-12-18", None, address="3 C St, Osaka"),  # no check-out: one night
    ]
    found = suggest_stops(trip(), stays, {})
    assert shown(found) == [("Tokyo", 10, 13), ("Kyoto", 13, 18), ("Osaka", 18, 20)]
    assert clean_stops(trip(), found) == found


def test_a_stay_with_no_nights_in_the_trip_does_not_make_a_stop() -> None:
    # Checking out on the trip's first day, or in on its last: nothing to show for the
    # first; the second is an arrival.
    stays = [
        stay("2026-12-08", "2026-12-10", address="1 A St, Tokyo"),
        stay("2026-12-12", "2026-12-20", address="2 B St, Kyoto"),
        stay("2026-12-20", None, address="3 C St, Osaka"),
    ]
    found = suggest_stops(trip(), stays, {})
    assert shown(found) == [("Kyoto", 10, 20), ("Osaka", 20, 20)]
    assert clean_stops(trip(), found) == found


def test_more_than_ten_places_are_cut_to_ten() -> None:
    stays = [
        stay(f"2026-12-{10 + n:02d}", f"2026-12-{11 + n:02d}", address=f"x, Place{chr(97 + n)}")
        for n in range(11)
    ]
    found = suggest_stops(trip(), stays, {})
    assert len(found) == 10 and found[-1].end == date(2026, 12, 20)
    assert clean_stops(trip(), found) == found


def test_the_place_in_an_address() -> None:
    assert address_place("12 Example-ro, Jung-gu, Seoul 04524") == "Seoul"
    assert address_place("3-4-5 Example, 605-0001") == "Example"
    assert address_place("1234") is None
    assert address_place(None) is None
