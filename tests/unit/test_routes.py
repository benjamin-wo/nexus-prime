"""Travel times between a trip day's stops: which stops a day has and in what order,
how each hop is travelled by default, when one is too tight, and Google's Routes
API. Every place, hotel and time here is made up."""

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from uuid import uuid4

import httpx
import pytest

from nexus.application.routes import Routes, RoutesError
from nexus.domain.bookings import Booking, BookingDraft, BookingKind, Segment
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.places import Point, metres_between, point
from nexus.domain.routes import (
    Hop,
    Mode,
    Stop,
    beside_airport,
    day_hops,
    default_mode,
    directions_url,
    station_query,
    tight,
)
from nexus.domain.trips import GettingAround
from nexus.infra.places.google import parse_place
from nexus.infra.places.routes import GoogleRoutes, parse_leg
from tests.fakes import NOW, FakeRoutes

USER = UserId(uuid4())
DAY = date(2026, 11, 12)


def entry(draft: BookingDraft) -> Booking:
    return Booking(uuid4(), USER, uuid4(), None, draft, None, None, NOW)


def plan(name: str, at: time | None, place: str | None, day: date = DAY) -> Booking:
    return entry(
        BookingDraft(
            BookingKind.ACTIVITY, None, (), None, None, None, None,
            name=name, day=day, at=at, place_id=place,
        )
    )  # fmt: skip


def hotel(name: str, check_in: date, check_out: date, place: str | None) -> Booking:
    return entry(
        BookingDraft(BookingKind.HOTEL, None, (), name, None, check_in, check_out, place_id=place)
    )


def flight(departs: datetime) -> Booking:
    leg = Segment("ZZ12", "Exampleton", "Otherville", departs, None)
    return entry(BookingDraft(BookingKind.FLIGHT, "Acme Air", (leg,), None, None, None, None))


def names(hops: list[Hop]) -> list[tuple[str, str]]:
    return [(h.start.title, h.end.title) for h in hops]


def test_a_day_runs_from_last_nights_hotel_through_its_plans_to_tonights() -> None:
    inn = hotel("Harbour Inn", date(2026, 11, 10), DAY, "fakePlaceInn00001")
    lodge = hotel("Hill Lodge", DAY, date(2026, 11, 14), "fakePlaceLodge001")
    later = plan("Night market", time(19), "fakePlaceMarket01")
    temple = plan("Old Temple", time(9), "fakePlaceTemple01")
    lunch = plan("Noodle lunch", time(12), "fakePlaceNoodle01")
    hops = day_hops([later, lodge, temple, inn, lunch], DAY)
    # Check-out from the inn, plans in time order, check in at the lodge (15:00),
    # out to the market, back to the lodge for the night.
    assert names(hops) == [
        ("Harbour Inn", "Old Temple"),
        ("Old Temple", "Noodle lunch"),
        ("Noodle lunch", "Hill Lodge"),
        ("Hill Lodge", "Night market"),
        ("Night market", "Hill Lodge"),
    ]
    # Another day of the lodge stay: only last night's and tonight's hotel, the same
    # place, so no hop at all.
    assert day_hops([lodge], date(2026, 11, 13)) == []


def test_a_flight_or_an_unplaced_plan_breaks_the_chain() -> None:
    a = plan("Old Temple", time(9), "fakePlaceTemple01")
    unknown = plan("Walk somewhere", time(11), None)
    b = plan("Noodle lunch", time(12), "fakePlaceNoodle01")
    c = plan("Museum", time(14), "fakePlaceMuseum01")
    away = flight(datetime(2026, 11, 12, 16, 30))
    d = plan("Dinner", time(20), "fakePlaceDinner01")
    other_day = plan("Tomorrow", time(9), "fakePlaceOther001", date(2026, 11, 13))
    hops = day_hops([a, unknown, b, c, away, d, other_day], DAY)
    assert names(hops) == [("Noodle lunch", "Museum")]


def test_short_hops_are_walked_and_tight_ones_flagged() -> None:
    assert default_mode(900) is Mode.WALK and default_mode(1500) is Mode.WALK
    assert default_mode(1501) is Mode.TRANSIT and default_mode(None) is Mode.TRANSIT
    first = Stop(uuid4(), "fakePlaceTemple01", "Old Temple", time(10))
    second = Stop(uuid4(), "fakePlaceNoodle01", "Noodle lunch", time(10, 20))
    hop = Hop(first, second)
    assert tight(hop, 25) and not tight(hop, 20)
    assert not tight(Hop(first, Stop(uuid4(), "fakePlaceInn00001", "Inn", None)), 90)
    url = directions_url(hop, Mode.TRANSIT)
    assert url.startswith("https://www.google.com/maps/dir/?api=1&origin=Old+Temple")
    assert "origin_place_id=fakePlaceTemple01" in url and url.endswith("travelmode=transit")


def test_coordinates_are_read_checked_and_measured() -> None:
    assert point(35.0116, 135.7681) == Point(35.0116, 135.7681)
    assert point(91, 0) is None and point("35", 1) is None and point(True, 1) is None
    assert point(float("nan"), 1) is None
    # About 1.1 km between two made-up points a hundredth of a degree of latitude apart.
    assert 1100 < metres_between(Point(35.0, 135.0), Point(35.01, 135.0)) < 1120
    row = {
        "id": "fakePlaceTemple01",
        "displayName": {"text": "Old Temple"},
        "location": {"latitude": 35.0116, "longitude": 135.7681},
    }
    found = parse_place(row)
    assert found is not None and found.location == Point(35.0116, 135.7681)
    parsed = parse_place({**row, "location": {"latitude": "x"}})
    assert parsed is not None and parsed.location is None


async def test_google_routes_sends_only_the_two_places() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        mode = json.loads(request.content)["travelMode"]
        if mode == "TRANSIT":
            return httpx.Response(200, json={})  # no public transport that way
        return httpx.Response(200, json={"routes": [{"duration": "754s", "distanceMeters": 980}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        google = GoogleRoutes(http, "maps-test-key")
        walked = await google.route("fakePlaceTemple01", "fakePlaceNoodle01", Mode.WALK)
        assert walked is not None and (walked.seconds, walked.metres) == (754, 980)
        assert await google.route("fakePlaceTemple01", "fakePlaceNoodle01", Mode.TRANSIT) is None
        await google.route("fakePlaceTemple01", "fakePlaceNoodle01", Mode.DRIVE)
        with pytest.raises(RoutesError, match="not a place id"):
            await google.route("../x", "fakePlaceNoodle01", Mode.WALK)
    first = seen[0]
    assert first.headers["X-Goog-Api-Key"] == "maps-test-key" and "key" not in str(first.url)
    assert first.headers["X-Goog-FieldMask"] == "routes.duration,routes.distanceMeters"
    assert json.loads(first.content) == {
        "origin": {"placeId": "fakePlaceTemple01"},
        "destination": {"placeId": "fakePlaceNoodle01"},
        "travelMode": "WALK",
        "languageCode": "en",
        "units": "METRIC",
    }
    assert json.loads(seen[2].content)["routingPreference"] == "TRAFFIC_UNAWARE"


@pytest.mark.parametrize(
    "data",
    [{}, {"routes": []}, {"routes": [{"duration": "abc"}]}, {"routes": [{"duration": "999999s"}]}],
)
def test_odd_route_answers_are_no_route(data: object) -> None:
    assert parse_leg(data) is None


async def test_google_routes_failures_are_errors() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(403, json={"error": "key"}))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(RoutesError, match=r"^HTTP 403$"):
            await GoogleRoutes(http, "k").route("fakePlaceA0001", "fakePlaceB0001", Mode.WALK)


async def test_routes_are_kept_a_while_and_capped_per_person() -> None:
    clock = [NOW]
    source = FakeRoutes()
    routes = Routes(source, clock=lambda: clock[0], limits=((2, timedelta(minutes=1)),))
    a, b, c = "fakePlaceA0001", "fakePlaceB0001", "fakePlaceC0001"
    assert (await routes.leg(USER, a, b, Mode.WALK)) is not None
    await routes.leg(USER, a, b, Mode.WALK)  # kept: not asked again
    await routes.leg(USER, a, c, Mode.WALK)
    assert len(source.asked) == 2
    with pytest.raises(InvalidInput, match="a lot of travel times"):
        await routes.leg(USER, b, c, Mode.WALK)
    # Half an hour later the kept answer is asked afresh.
    clock[0] = NOW + timedelta(minutes=31)
    await routes.leg(USER, a, b, Mode.WALK)
    assert len(source.asked) == 3


def overnight(stations: tuple[tuple[str, str], ...]) -> Booking:
    """A made-up overnight flight into DAY, and back out of it later that week."""
    there = Segment(
        "ZZ378", "SIN", "BCN", datetime(2026, 11, 11, 23, 30), datetime(2026, 11, 12, 9, 15)
    )
    back = Segment(
        "ZZ379", "BCN", "SIN", datetime(2026, 11, 15, 11, 0), datetime(2026, 11, 16, 7, 0)
    )
    draft = BookingDraft(BookingKind.FLIGHT, "Acme Air", (there, back), None, None, None, None)
    return entry(replace(draft, stations=stations))


def test_a_flight_starts_the_day_at_the_airport_it_lands_at() -> None:
    away = overnight((("BCN airport", "fakePlaceAirport1"),))
    lodge = hotel("Hill Lodge", DAY, date(2026, 11, 15), "fakePlaceLodge001")
    hops = day_hops([away, lodge], DAY)
    assert names(hops) == [("BCN airport", "Hill Lodge")]
    assert (hops[0].start.booking_id, hops[0].start.at) == (away.id, time(9, 15))
    # The way home: from the hotel to the airport the return leaves from.
    assert names(day_hops([away, lodge], date(2026, 11, 15))) == [("Hill Lodge", "BCN airport")]
    # Before the airport is found on Google Maps (or when it isn't), nothing joins it.
    assert day_hops([overnight(()), lodge], DAY) == []
    assert day_hops([overnight((("BCN airport", ""),)), lodge], DAY) == []


def test_what_to_search_for_an_airport_or_station() -> None:
    assert station_query(BookingKind.FLIGHT, "BCN") == "BCN airport"
    assert station_query(BookingKind.FLIGHT, "Changi Airport") == "Changi Airport"
    assert station_query(BookingKind.RAIL, " Kyoto ") == "Kyoto station"
    assert station_query(BookingKind.RAIL, None) is None


def test_a_trip_with_a_car_drives_the_longer_hops() -> None:
    assert default_mode(900, GettingAround.CAR) is Mode.WALK
    assert default_mode(120_000, GettingAround.CAR) is Mode.DRIVE
    assert default_mode(None, GettingAround.CAR) is Mode.DRIVE
    assert default_mode(120_000) is Mode.TRANSIT


def test_a_place_right_by_the_airport_is_part_of_being_there() -> None:
    away = overnight((("BCN airport", "fakePlaceAirport1"),))
    desk = plan("Car pickup", time(9, 45), "fakePlaceCarDesk1")
    (hop,) = day_hops([away, desk], DAY)
    flights = {away.id}
    assert beside_airport(hop, 1_200, flights)
    assert not beside_airport(hop, 25_000, flights)  # a drive away
    assert not beside_airport(hop, None, flights)  # distance unknown
    # Between two plans, however close, it's an ordinary hop.
    assert not beside_airport(hop, 1_200, set())
