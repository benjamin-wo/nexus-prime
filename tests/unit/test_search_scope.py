"""Where a search for a trip looks: the whole trip, one of its stops, or near a day of
plans. Every place and booking here is made up."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from nexus.application.places import SearchScope, scope_of_day
from nexus.domain.bookings import Booking, BookingDraft
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.places import Circle, Point
from nexus.domain.trips import Stop, Trip
from tests.fakes import fake_place

USER = UserId(uuid4())
MADE = datetime(2026, 9, 28, tzinfo=UTC)
TRIP = Trip(
    uuid4(), USER, "Exampleland", date(2026, 12, 10), date(2026, 12, 20), "JPY", None, (), None, {},
    MADE, MADE,
)  # fmt: skip
STOPS = (
    Stop("Kyoto", date(2026, 12, 10), date(2026, 12, 14)),
    Stop("Tokyo", date(2026, 12, 14), date(2026, 12, 20)),
)

GION = fake_place("fakePlaceGion0001", "Gion Corner", location=Point(35.0, 135.0), area="Gion")
SHRINE = fake_place(
    "fakePlaceShrine01", "Yasaka Shrine", location=Point(35.002, 135.004), area="Gion"
)
CAFE = fake_place(
    "fakePlaceCafe00001", "Hill Cafe", location=Point(35.1, 135.2), area="Higashiyama"
)
FOUND = {p.id: p for p in (GION, SHRINE, CAFE)}


def plan(day: str, name: str, **extra: object) -> Booking:
    draft = BookingDraft.from_dict({"kind": "activity", "name": name, "day": day, **extra})
    assert draft is not None
    return Booking(uuid4(), USER, TRIP.id, None, draft, None, None, MADE)


def scope(bookings: Sequence[Booking] = (), **ask: object) -> SearchScope:
    return scope_of_day(TRIP, STOPS, bookings, FOUND, **ask)  # type: ignore[arg-type]


def test_the_whole_trip_is_its_destination_with_no_circle() -> None:
    assert scope() == SearchScope("Exampleland", None)


def test_a_stop_swaps_in_its_name_whatever_the_case() -> None:
    assert scope(stop="  tokyo ") == SearchScope("Tokyo", None)
    with pytest.raises(InvalidInput, match=r"isn't one of the trip's stops \(Kyoto, Tokyo\)"):
        scope(stop="Osaka")


def test_a_day_leans_towards_the_mean_of_its_places_and_own_pins() -> None:
    bookings = [
        plan("2026-12-12", "Gion Corner", place_id=GION.id),
        plan("2026-12-12", "Yasaka Shrine", place_id=SHRINE.id),
        plan("2026-12-12", "My pin", lat=35.004, lng=135.002),  # the user's own, unlinked
        plan("2026-12-13", "Hill Cafe", place_id=CAFE.id),  # another day
        plan("2026-12-12", "Gone", place_id="fakePlaceGone0001"),  # Google couldn't be asked
    ]
    found = scope(bookings, day=date(2026, 12, 12))
    # The day's stop, with the area most of its places are in.
    assert found.place == "Gion, Kyoto"
    assert found.near == Circle(Point(35.002, 135.002), 2000)


def test_a_day_with_nothing_planned_is_searched_by_its_stop_alone() -> None:
    assert scope(day=date(2026, 12, 11)) == SearchScope("Kyoto", None)
    # No Google Maps details to say where its places are: the same.
    assert scope_of_day(
        TRIP, STOPS, [plan("2026-12-11", "Gion Corner", place_id=GION.id)], {},
        day=date(2026, 12, 11),
    ) == SearchScope("Kyoto", None)  # fmt: skip


def test_a_travel_day_is_in_the_stop_arrived_at() -> None:
    assert scope(day=date(2026, 12, 14)).place == "Tokyo"


def test_a_stop_and_a_day_must_agree_and_the_day_be_on_the_trip() -> None:
    assert scope(stop="Kyoto", day=date(2026, 12, 12)).place == "Kyoto"
    assert scope(stop="Tokyo", day=date(2026, 12, 14)).place == "Tokyo"  # the travel day
    with pytest.raises(InvalidInput, match="isn't in Kyoto"):
        scope(stop="Kyoto", day=date(2026, 12, 18))
    with pytest.raises(InvalidInput, match="outside the trip"):
        scope(day=date(2026, 12, 21))
    with pytest.raises(InvalidInput, match="outside the trip"):
        scope(day=date(2026, 12, 9))


def test_an_area_named_like_the_stop_is_not_repeated() -> None:
    bookings = [plan("2026-12-12", "Hill Cafe", place_id=CAFE.id)]
    in_kyoto = {
        CAFE.id: fake_place(CAFE.id, "Hill Cafe", location=Point(35.1, 135.2), area="Kyoto")
    }
    found = scope_of_day(TRIP, STOPS, bookings, in_kyoto, day=date(2026, 12, 12))
    assert found.place == "Kyoto"
