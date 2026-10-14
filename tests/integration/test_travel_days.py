"""Travel days: an overnight flight's airport found on Google Maps and joined to the
hotel, the trip's way of getting around, a way picked for a hop kept, and a hire car
collected at the airport on the way. Every place, flight and time here is made up."""

from dataclasses import replace
from datetime import date

import pytest

from nexus.application import bookings as booking_cases
from nexus.application import places as place_cases
from nexus.application import trips as trip_cases
from nexus.application.places import Places
from nexus.application.routes import Routes, hop_time, hop_times
from nexus.domain import itinerary
from nexus.domain.places import Point
from nexus.domain.routes import Mode
from nexus.domain.trips import GettingAround
from tests.fakes import NOW, FakePlaces, FakeRoutes, fake_place
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

AIRPORT = replace(
    fake_place("fakePlaceAirport1", "Exampleton El Prat Airport", location=Point(41.29, 2.07)),
    kind="International airport",
)
LODGE = fake_place("fakePlaceLodge001", "Hill Lodge", location=Point(41.93, 3.21))
# A hire-car desk about a kilometre from the airport's pin.
DESK = fake_place("fakePlaceCarDesk1", "Example Car Hire T1", location=Point(41.285, 2.08))
ARRIVAL = date(2026, 10, 21)


async def test_from_the_airport_to_the_hotel_by_the_trips_way_of_getting_around(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(), user,
        trip_cases.TripDraft("Exampleland", ARRIVAL, date(2026, 10, 24), "EUR", None),
        now=NOW,
    )  # fmt: skip
    flight = await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "flight", "provider": "Acme Air",
         "segments": [{"number": "ZZ378", "from": "SIN", "to": "BCN",
                       "departs": "2026-10-20T23:30", "arrives": "2026-10-21T09:15"}]},
        None, now=NOW,
    )  # fmt: skip
    lodge = await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "hotel", "hotel": "Hill Lodge", "check_in": "2026-10-21",
         "check_out": "2026-10-24", "place_id": LODGE.id},
        None, now=NOW,
    )  # fmt: skip
    source = FakePlaces([AIRPORT, LODGE])
    places, routes = Places(source, clock=lambda: NOW), Routes(FakeRoutes(), clock=lambda: NOW)

    # The airport it lands at is looked up once, its id kept on the flight; by public
    # transport by default.
    hops = await hop_times(uow, places, routes, user.id, trip.id, ARRIVAL)
    assert [(h.hop.start.title, h.hop.end.title, h.mode, h.minutes) for h in hops] == [
        ("BCN airport", "Hill Lodge", Mode.TRANSIT, 25)
    ]
    assert (hops[0].hop.start.booking_id, hops[0].hop.end.booking_id) == (flight.id, lodge.id)
    assert source.searches == ["BCN airport"]
    async with uow() as tx:
        kept = await tx.trips.get_booking(user.id, flight.id)
    assert kept is not None and kept.draft.station("BCN airport") == AIRPORT.id
    await hop_times(uow, places, routes, user.id, trip.id, ARRIVAL)
    assert source.searches == ["BCN airport"]  # not looked up again

    # Edits that don't mention them keep the airports.
    await booking_cases.edit_booking(
        uow(), user.id, flight.id,
        {"kind": "flight", "provider": "Acme Air", "note": "Aisle seat",
         "segments": [{"number": "ZZ378", "from": "SIN", "to": "BCN",
                       "departs": "2026-10-20T23:30", "arrives": "2026-10-21T09:15"}]},
        None,
    )  # fmt: skip
    async with uow() as tx:
        edited = await tx.trips.get_booking(user.id, flight.id)
    assert edited is not None and edited.draft.station("BCN airport") == AIRPORT.id

    # A hire car: longer hops drive.
    await trip_cases.set_getting_around(uow(), user, trip.id, GettingAround.CAR, now=NOW)
    hops = await hop_times(uow, places, routes, user.id, trip.id, ARRIVAL)
    assert [(h.mode, h.minutes) for h in hops] == [(Mode.DRIVE, 15)]

    # A way picked for one hop is kept, whatever the trip's usual way.
    picked = await hop_time(
        uow, routes, user.id, trip.id, ARRIVAL, flight.id, lodge.id, Mode.TRANSIT
    )
    assert picked.mode is Mode.TRANSIT
    hops = await hop_times(uow, places, routes, user.id, trip.id, ARRIVAL)
    assert [h.mode for h in hops] == [Mode.TRANSIT]
    # Editing the trip keeps both.
    again = await trip_cases.get_trip(uow(), user.id, trip.id)
    await trip_cases.update_trip(uow(), user, trip.id, trip_cases.draft_of(again), now=NOW)
    again = await trip_cases.get_trip(uow(), user.id, trip.id)
    assert again.getting_around is GettingAround.CAR
    assert again.hop_modes == {f"{flight.id}:{lodge.id}": "transit"}

    # The map gets the airport too, with the day it's landed at.
    linked = await place_cases.trip_places(uow(), places, user.id, trip.id)
    assert [(x.place.id, x.station, x.stops) for x in linked] == [
        (LODGE.id, None, ()),
        (AIRPORT.id, "BCN airport", ((ARRIVAL, "to"),)),
    ]


async def test_a_search_that_finds_no_airport_is_kept_as_none_found(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(), user, trip_cases.TripDraft("Exampleland", ARRIVAL, ARRIVAL, "EUR", None), now=NOW
    )
    flight = await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "flight", "segments": [{"number": "ZZ1", "from": "SIN", "to": "XYZ",
                                         "departs": "2026-10-21T08:00",
                                         "arrives": "2026-10-21T10:00"}]},
        None, now=NOW,
    )  # fmt: skip
    source = FakePlaces([LODGE])  # no airport among the results
    places, routes = Places(source, clock=lambda: NOW), Routes(FakeRoutes(), clock=lambda: NOW)
    assert await hop_times(uow, places, routes, user.id, trip.id, ARRIVAL) == []
    async with uow() as tx:
        kept = await tx.trips.get_booking(user.id, flight.id)
    assert kept is not None
    assert (kept.draft.station("SIN airport"), kept.draft.station("XYZ airport")) == ("", "")
    await hop_times(uow, places, routes, user.id, trip.id, ARRIVAL)
    assert source.searches == ["SIN airport", "XYZ airport"]  # each asked once


async def test_a_hire_car_collected_at_the_airport_is_part_of_arriving(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(), user,
        trip_cases.TripDraft("Exampleland", ARRIVAL, date(2026, 10, 24), "EUR", None),
        now=NOW,
    )  # fmt: skip
    await trip_cases.set_getting_around(uow(), user, trip.id, GettingAround.CAR, now=NOW)
    flight = await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "flight", "provider": "Acme Air",
         "segments": [{"number": "ZZ378", "from": "SIN", "to": "BCN",
                       "departs": "2026-10-20T23:30", "arrives": "2026-10-21T09:15"}]},
        None, now=NOW,
    )  # fmt: skip
    lodge = await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "hotel", "hotel": "Hill Lodge", "check_in": "2026-10-21",
         "check_out": "2026-10-24", "place_id": LODGE.id},
        None, now=NOW,
    )  # fmt: skip
    desk = await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "activity", "name": "Car pickup", "day": "2026-10-21", "place_id": DESK.id},
        None, now=NOW,
    )  # fmt: skip

    async def day() -> list[str]:
        async with uow() as tx:
            bookings = await tx.trips.list_bookings(user.id, trip_id=trip.id)
        names = {flight.id: "flight", lodge.id: "lodge", desk.id: "car"}
        return [names[b.id] for b in itinerary.on_day(bookings, ARRIVAL)]

    # Put right after landing, the pickup (no time of its own) stays there: the 15:00
    # check-in doesn't jump ahead of it.
    await booking_cases.move_entry(uow(), user.id, desk.id, ARRIVAL, lodge.id)
    assert await day() == ["flight", "lodge", "car"]
    moved = await booking_cases.move_entry(uow(), user.id, desk.id, ARRIVAL, flight.id)
    assert moved.draft.follows is not None
    assert await day() == ["flight", "car", "lodge"]

    # Airport to desk is part of arriving: marked, not timed. Then the drive.
    source = FakePlaces([AIRPORT, LODGE, DESK])
    places, routes = Places(source, clock=lambda: NOW), Routes(FakeRoutes(), clock=lambda: NOW)
    hops = await hop_times(uow, places, routes, user.id, trip.id, ARRIVAL)
    assert [(h.hop.start.title, h.hop.end.title, h.beside_airport, h.minutes) for h in hops] == [
        ("BCN airport", "Car pickup", True, None),
        ("Car pickup", "Hill Lodge", False, 15),
    ]
    assert hops[1].mode is Mode.DRIVE

    # Given a time, it goes by that instead.
    timed = await booking_cases.edit_booking(
        uow(), user.id, desk.id,
        {"kind": "activity", "name": "Car pickup", "day": "2026-10-21", "at": "16:00"},
        None,
    )  # fmt: skip
    assert timed.draft.follows is None
    assert await day() == ["flight", "lodge", "car"]


async def test_after_the_car_goes_back_the_way_on_is_public_transport(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(), user,
        trip_cases.TripDraft("Exampleland", ARRIVAL, date(2026, 10, 24), "EUR", None),
        now=NOW,
    )  # fmt: skip
    await trip_cases.set_getting_around(uow(), user, trip.id, GettingAround.CAR, now=NOW)
    await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "hotel", "hotel": "Hill Lodge", "check_in": "2026-10-21",
         "check_out": "2026-10-24", "place_id": LODGE.id},
        None, now=NOW,
    )  # fmt: skip
    await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "activity", "name": "Car return", "day": "2026-10-21", "at": "17:00",
         "place_id": DESK.id},
        None, now=NOW,
    )  # fmt: skip
    source = FakePlaces([AIRPORT, LODGE, DESK])
    places, routes = Places(source, clock=lambda: NOW), Routes(FakeRoutes(), clock=lambda: NOW)
    hops = await hop_times(uow, places, routes, user.id, trip.id, ARRIVAL)
    # Driven to the car return; back to the hotel without it.
    assert [(h.hop.start.title, h.hop.end.title, h.mode) for h in hops] == [
        ("Hill Lodge", "Car return", Mode.DRIVE),
        ("Car return", "Hill Lodge", Mode.TRANSIT),
    ]
