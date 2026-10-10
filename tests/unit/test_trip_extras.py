"""Packing suggestions, trip weather (forecast or the same dates in recent years) and
Google Maps place photos, against made-up answers."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from nexus.application.places import Places, PlacesError
from nexus.application.weather import Weather, WeatherError
from nexus.domain.destination_photos import Season
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.packing import Outlook, PackItem, clean_list, from_rows, suggestions
from nexus.domain.trips import Trip
from nexus.domain.weather import DayWeather, WeatherKind, describe, shifted, typical
from nexus.infra.places.google import GooglePlaces, parse_place
from nexus.infra.weather.open_meteo import OpenMeteo
from tests.fakes import FakePlaces, FakeWeather, fake_place

USER = UserId(uuid4())
NOW = datetime(2026, 10, 6, 9, tzinfo=UTC)


def trip(start: date, days: int = 5, destination: str = "Tokyo, Kyoto") -> Trip:
    return Trip(
        id=uuid4(),
        user_id=USER,
        destination=destination,
        start=start,
        end=start + timedelta(days=days - 1),
        currency="JPY",
        budget=None,
        companions=(),
        set_aside=None,
        planned={},
        created_at=NOW,
        updated_at=NOW,
    )


# --- packing ---------------------------------------------------------------------------


def test_suggestions_follow_the_trip() -> None:
    abroad_winter = suggestions(
        abroad=True, nights=4, season=Season.WINTER, outlook=Outlook(low=-3, high=4, rain=True)
    )
    assert abroad_winter[0] == "Passport"
    assert {"Warm jacket", "Gloves and a hat", "Umbrella or rain jacket"} <= set(abroad_winter)
    assert "Sunscreen" not in abroad_winter
    home_summer = suggestions(abroad=False, nights=12, season=Season.SUMMER, outlook=None)
    assert "Passport" not in home_summer and "Sunscreen" in home_summer
    assert "Clothes for 7 days" in home_summer and "Laundry bag" in home_summer
    tropics = suggestions(abroad=True, nights=3, season=Season.ANY, outlook=None)
    assert "Sunscreen" in tropics and "Umbrella or rain jacket" in tropics


def test_lists_are_cleaned_and_capped() -> None:
    items = [PackItem(" Socks "), PackItem("socks", True), PackItem(""), PackItem("Hat\x00")]
    assert clean_list(items) == (PackItem("Socks"), PackItem("Hat"))
    with pytest.raises(InvalidInput):
        clean_list([PackItem(f"thing {n}") for n in range(81)])
    assert from_rows([{"text": "Hat", "done": 1}, {"text": 3}, "x", {"text": " "}]) == (
        PackItem("Hat", True),
    )


# --- weather ---------------------------------------------------------------------------


def test_typical_weather_averages_recent_years() -> None:
    days = [date(2026, 11, 10), date(2026, 11, 11)]
    years = [
        [DayWeather(days[0], 18, 8, 100, 61), DayWeather(days[1], 16, 6, 0, 1)],
        [DayWeather(days[0], 20, 10, 0, 61), DayWeather(days[1], 14, 4, 0, 3)],
        [DayWeather(days[0], 19, 9, 0, 3), DayWeather(days[1], None, None, None, 1)],
    ]
    first, second = typical(days, years)
    assert (first.high, first.low, first.rain, first.code) == (19, 9, 33, 61)
    assert (second.high, second.low, second.rain, second.code) == (15, 5, 0, 1)
    assert describe(61) == "Light rain" and describe(None) is None
    assert shifted(date(2028, 2, 29), 1) == date(2027, 2, 28)


async def test_a_near_trip_gets_the_forecast_and_a_far_one_typical_weather() -> None:
    source = FakeWeather()
    weather = Weather(source, clock=lambda: NOW)
    today = NOW.date()
    near = await weather.for_trip(trip(today + timedelta(days=10)), today)
    assert near is not None and near.kind is WeatherKind.FORECAST
    # The forecast reaches 16 days: the trip's last day (day 14 from now) is in.
    assert len(near.days) == 5 and near.place.name == "Tokyo"
    assert near.outlook() == Outlook(low=9.0, high=22.0, rain=True)
    far = await weather.for_trip(trip(today + timedelta(days=40)), today)
    assert far is not None and far.kind is WeatherKind.TYPICAL and len(far.days) == 5
    assert [a for a in source.asked if a.startswith("past")] == [
        "past:2025-11-15:2025-11-19",
        "past:2024-11-15:2024-11-19",
        "past:2023-11-15:2023-11-19",
    ]
    assert far.days[0].rain == 100 and far.days[1].rain == 0
    # Asked once: the place and both answers come from memory the second time.
    before = len(source.asked)
    await weather.for_trip(trip(today + timedelta(days=40)), today)
    await weather.for_trip(trip(today + timedelta(days=10)), today)
    assert len(source.asked) == before
    assert await weather.for_trip(trip(today - timedelta(days=9)), today) is None  # over
    source.failing = True
    with pytest.raises(WeatherError):
        await Weather(source, clock=lambda: NOW).for_trip(trip(today + timedelta(days=3)), today)


def meteo(handler: Any) -> OpenMeteo:
    return OpenMeteo(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_open_meteo_answers_are_read() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if "geocoding" in request.url.host:
            assert request.url.params["name"] == "Tokyo"
            row = {
                "name": "Tokyo",
                "country": "Japan",
                "country_code": "JP",
                "latitude": 35.69,
                "longitude": 139.69,
            }
            return httpx.Response(200, json={"results": [row]})
        assert request.url.params["start_date"] == "2026-11-10"
        daily = {
            "time": ["2026-11-10", "2026-11-11", "bad"],
            "temperature_2m_max": [18.2, None, 1],
            "temperature_2m_min": [9.1, 8.0, 1],
            "precipitation_probability_max": [20, 70, 1],
            "weather_code": [1, 61, 1],
        }
        return httpx.Response(200, json={"daily": daily})

    source = meteo(answer)
    spot = await source.find("Tokyo")
    assert spot is not None and (spot.name, spot.country, spot.country_code) == (
        "Tokyo",
        "Japan",
        "JP",
    )
    days = await source.forecast(spot, date(2026, 11, 10), date(2026, 11, 11))
    assert days == [
        DayWeather(date(2026, 11, 10), 18.2, 9.1, 20, 1),
        DayWeather(date(2026, 11, 11), None, 8.0, 70, 61),
    ]
    nowhere = meteo(lambda r: httpx.Response(200, json={"generationtime_ms": 1}))
    assert await nowhere.find("Atlantis") is None
    busy = meteo(lambda r: httpx.Response(429, json={"error": True}))
    with pytest.raises(WeatherError):
        await busy.find("Tokyo")


# --- Google Maps place photos ------------------------------------------------------------


def test_a_places_first_photo_and_its_author_are_read() -> None:
    row = {
        "id": "fakePlaceTemple01",
        "displayName": {"text": "Sensō-ji"},
        "photos": [
            {
                "name": "places/fakePlaceTemple01/photos/ref-1",
                "authorAttributions": [
                    {"displayName": "A. Visitor", "uri": "https://maps.example/a"}
                ],
            }
        ],
    }
    place = parse_place(row, detailed=True)
    assert place is not None and place.photo is not None
    assert (place.photo.name, place.photo.author) == (
        "places/fakePlaceTemple01/photos/ref-1",
        "A. Visitor",
    )
    row["photos"] = [{"name": "../../etc/passwd"}]
    bad = parse_place(row, detailed=True)
    assert bad is not None and bad.photo is None


async def test_google_photos_are_fetched_without_the_key_on_the_image() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "places.example":
            assert request.url.params["skipHttpRedirect"] == "true"
            return httpx.Response(200, json={"photoUri": "https://images.example/p.jpg"})
        return httpx.Response(200, content=b"\xff\xd8jpg", headers={"content-type": "image/jpeg"})

    google = GooglePlaces(
        httpx.AsyncClient(transport=httpx.MockTransport(answer)),
        "made-up-key",
        base_url="https://places.example/v1",
    )
    assert await google.photo("places/fakePlaceTemple01/photos/ref-1") == (
        b"\xff\xd8jpg",
        "image/jpeg",
    )
    assert seen[0].headers["X-Goog-Api-Key"] == "made-up-key"
    assert "X-Goog-Api-Key" not in seen[1].headers and "made-up-key" not in str(seen[1].url)
    with pytest.raises(PlacesError):
        await google.photo("not a photo")


async def test_place_photos_are_cached_and_capped() -> None:
    source = FakePlaces([fake_place("fakePlaceTemple01", "Noodle Bar")])
    places = Places(source, clock=lambda: NOW, photo_limits=((2, timedelta(days=1)),))
    data, mime, credit = await places.photo(USER, "fakePlaceTemple01")
    assert (data[:2], mime, credit.author) == (b"\xff\xd8", "image/jpeg", "A. Photographer")
    await places.photo(USER, "fakePlaceTemple01")
    assert source.photos == ["places/fakePlaceTemple01/photos/ref1"]  # the second came from memory
    source2 = FakePlaces([fake_place(f"fakePlaceSpot{n:02d}", f"Place {n}") for n in range(3)])
    capped = Places(source2, clock=lambda: NOW, photo_limits=((2, timedelta(days=1)),))
    await capped.photo(USER, "fakePlaceSpot00")
    await capped.photo(USER, "fakePlaceSpot01")
    with pytest.raises(InvalidInput):
        await capped.photo(USER, "fakePlaceSpot02")


def test_a_country_suggests_its_currency() -> None:
    from nexus.domain.currencies import currency_of

    assert currency_of("JP") == "JPY"
    assert currency_of("fr") == "EUR"  # any case
    assert currency_of("GB") == "GBP"
    assert currency_of("ZZ") is None  # not one we know: the user picks
    assert currency_of(None) is None
