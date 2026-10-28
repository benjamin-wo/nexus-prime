"""Weather kept in the database across restarts, for as long as the
in-memory caches keep them, and never in the way of a lookup."""

import asyncio
from datetime import timedelta
from types import TracebackType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import external_cache
from nexus.application.external_cache import KeptAnswers
from nexus.application.weather import Weather
from nexus.domain.weather import WeatherKind
from tests.fakes import FakeWeather
from tests.integration.conftest import UowFactory
from tests.unit.test_trip_extras import NOW, USER, trip

HOUR = timedelta(hours=1)


class Broken:
    """A unit of work that can't be had: the database is down."""

    async def __aenter__(self) -> "Broken":
        raise ConnectionError("database is down")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class Slow(Broken):
    async def __aenter__(self) -> "Slow":
        await asyncio.sleep(10)
        return self


async def rows(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as db:
        found = await db.execute(text("SELECT key, kind, value FROM external_cache ORDER BY kind"))
        return list(found.all())


# --- the store itself --------------------------------------------------------------------


async def test_a_slow_database_is_given_up_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_cache, "TIMEOUT", 0.05)
    kept = KeptAnswers(Slow)  # type: ignore[arg-type]
    assert await kept.get("forecast", "1,2", NOW) is None
    await kept.put("forecast", "1,2", {"x": 1}, NOW + HOUR, NOW)  # gives up quietly too


async def test_answers_gone_stale_are_removed_when_another_is_kept(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    kept = KeptAnswers(uow)
    await kept.put("forecast", "a", {"x": 1}, NOW + HOUR, NOW)
    await kept.put("forecast", "b", {"x": 2}, NOW + HOUR, NOW)
    assert len(await rows(engine)) == 2
    later = NOW + 2 * HOUR
    assert await kept.get("forecast", "a", later) is None  # stale answers are never read
    await kept.put("forecast", "c", {"x": 3}, later + HOUR, later)
    assert len(await rows(engine)) == 1


async def test_the_app_role_may_use_the_table_without_a_user_named(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    # The unit of work runs as the restricted role; this is the same through a user's own
    # web request, which names the user for the transaction.
    from nexus.application.acting import acting_as

    kept = KeptAnswers(uow)
    with acting_as(USER):
        await kept.put("forecast", "a", {"x": 1}, NOW + HOUR, NOW)
        found = await kept.get("forecast", "a", NOW)
    assert found is not None and found[0] == {"x": 1} and len(await rows(engine)) == 1


# --- weather ---------------------------------------------------------------------------


def weather_at(uow: UowFactory, source: FakeWeather, now: list[Any]) -> Weather:
    return Weather(source, clock=lambda: now[0], kept=KeptAnswers(uow))


async def test_a_forecast_and_its_place_are_kept_across_a_restart(uow: UowFactory) -> None:
    now = [NOW]
    today = NOW.date()
    near = trip(today + timedelta(days=10))
    first = FakeWeather()
    found = await weather_at(uow, first, now).for_trip(near, today)
    assert found is not None and found.kind is WeatherKind.FORECAST
    assert [a.split(":")[0] for a in first.asked] == ["find", "forecast"]

    second = FakeWeather()
    again = await weather_at(uow, second, now).for_trip(near, today)
    assert again == found and second.asked == []  # place and forecast both kept


async def test_typical_weather_is_kept_across_a_restart(uow: UowFactory) -> None:
    now = [NOW]
    today = NOW.date()
    far = trip(today + timedelta(days=40))
    found = await weather_at(uow, FakeWeather(), now).for_trip(far, today)
    assert found is not None and found.kind is WeatherKind.TYPICAL
    second = FakeWeather()
    assert await weather_at(uow, second, now).for_trip(far, today) == found
    assert second.asked == []


async def test_each_kind_of_weather_is_kept_for_as_long_as_it_is_in_memory(
    uow: UowFactory,
) -> None:
    now = [NOW]
    today = NOW.date()
    near, far = trip(today + timedelta(days=10)), trip(today + timedelta(days=40))
    first = weather_at(uow, FakeWeather(), now)
    await first.for_trip(near, today)
    await first.for_trip(far, today)

    now[0] = NOW + timedelta(hours=4)  # a forecast is kept 3 hours; the rest longer
    source = FakeWeather()
    restarted = weather_at(uow, source, now)
    await restarted.for_trip(near, today)
    assert [a.split(":")[0] for a in source.asked] == ["forecast"]
    source.asked.clear()
    await restarted.for_trip(far, today)
    assert source.asked == []

    now[0] = NOW + timedelta(days=8)  # past years are kept 7 days; places 30
    source = FakeWeather()
    restarted = weather_at(uow, source, now)
    await restarted.for_trip(far, today)
    assert sorted({a.split(":")[0] for a in source.asked}) == ["past"]

    now[0] = NOW + timedelta(days=31)
    source = FakeWeather()
    await weather_at(uow, source, now).spot("Tokyo, Kyoto")
    assert source.asked == ["find:Tokyo"]


async def test_a_place_that_was_not_found_is_kept_too(uow: UowFactory) -> None:
    now = [NOW]
    assert await weather_at(uow, FakeWeather(), now).spot("Nowhere") is None
    source = FakeWeather()
    assert await weather_at(uow, source, now).spot("nowhere") is None  # however it's written
    assert source.asked == []


async def test_the_time_zone_of_a_place_survives_a_restart(uow: UowFactory) -> None:
    now = [NOW]
    zones = {"Madrid": "Europe/Madrid"}
    assert await weather_at(uow, FakeWeather(zones=zones), now).zone_of("Madrid") == "Europe/Madrid"
    source = FakeWeather(finding_fails=True)  # the geocoder is down, but the answer is kept
    assert await weather_at(uow, source, now).zone_of("Madrid") == "Europe/Madrid"


async def test_kept_weather_holds_no_name_or_user(uow: UowFactory, engine: AsyncEngine) -> None:
    today = NOW.date()
    await weather_at(uow, FakeWeather(), [NOW]).for_trip(trip(today + timedelta(days=10)), today)
    found = await rows(engine)
    assert {r.kind for r in found} == {"spot", "forecast"}
    assert all(len(r.key) == 64 for r in found)
    assert all(str(USER) not in str(r) for r in found)


async def test_a_database_that_fails_never_breaks_the_weather(
    caplog: pytest.LogCaptureFixture,
) -> None:
    today = NOW.date()
    source = FakeWeather()
    weather = Weather(source, clock=lambda: NOW, kept=KeptAnswers(Broken))  # type: ignore[arg-type]
    with caplog.at_level("WARNING"):
        found = await weather.for_trip(trip(today + timedelta(days=10)), today)
        zone = await weather.zone_of("Madrid")
    assert found is not None and len(found.days) == 5 and zone is None
    assert "couldn't read a kept spot answer" in caplog.text
    assert "couldn't keep a forecast answer" in caplog.text


async def test_an_unreadable_kept_forecast_is_asked_again(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    today = NOW.date()
    near = trip(today + timedelta(days=10))
    await weather_at(uow, FakeWeather(), [NOW]).for_trip(near, today)
    async with engine.begin() as db:
        await db.execute(
            text("""UPDATE external_cache SET value = '{"days": [1]}'
                                 WHERE kind = 'forecast'""")
        )
    source = FakeWeather()
    found = await weather_at(uow, source, [NOW]).for_trip(near, today)
    assert found is not None and len(found.days) == 5
    assert [a.split(":")[0] for a in source.asked] == ["forecast"]
