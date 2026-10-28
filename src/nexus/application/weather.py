"""The weather on a trip page: the forecast for the trip's days once a forecast reaches
them, and before that what the same dates were like over the last three years.

Answers are kept in memory for a while (places a month, forecasts a few hours, past years
a week), so pages don't ask again on every visit, and in the database for the same while
(``external_cache``: a hash of the place or of the coordinates and dates, and the answer),
so a deploy doesn't empty them.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from nexus.application.clock import utcnow
from nexus.application.external_cache import KeptAnswers
from nexus.domain.destination_photos import first_place, place_key
from nexus.domain.trips import Trip
from nexus.domain.weather import (
    FORECAST_DAYS,
    RAINY_MM,
    YEARS,
    DayWeather,
    Spot,
    TripWeather,
    WeatherKind,
    forecast_reaches,
    shifted,
    typical,
)

log = logging.getLogger(__name__)

FORECAST_FOR = timedelta(hours=3)
PAST_FOR = timedelta(days=7)
PLACE_FOR = timedelta(days=30)
CACHE_SIZE = 500
# Finding a place's time zone never holds anything up for longer than this.
ZONE_TIMEOUT = 3.0


class WeatherError(Exception):
    """The weather service couldn't answer right now."""


class WeatherSource(Protocol):
    async def find(self, name: str) -> Spot | None:
        """The place by name, or None when there's no such place."""
        ...

    async def forecast(self, spot: Spot, start: date, end: date) -> list[DayWeather]:
        """Forecast days, rain as a chance in %."""
        ...

    async def past(self, spot: Spot, start: date, end: date) -> list[DayWeather]:
        """Recorded days, rain as millimetres (not a chance)."""
        ...


class Weather:
    def __init__(
        self,
        source: WeatherSource,
        *,
        clock: Callable[[], datetime] = utcnow,
        kept: KeptAnswers | None = None,
    ) -> None:
        self._source = source
        self._clock = clock
        self._kept = kept
        self._cache: OrderedDict[str, tuple[datetime, timedelta, object]] = OrderedDict()

    def _cached(self, key: str) -> object | None:
        found = self._cache.get(key)
        if found is None:
            return None
        at, keep, value = found
        if self._clock() - at >= keep:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def _keep(self, key: str, value: object, keep: timedelta) -> None:
        self._cache[key] = (self._clock(), keep, value)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)

    async def _stored(self, kind: str, ask: str, decode: Callable[[Any], object]) -> object | None:
        """An answer kept in the database, put back in memory for the rest of its time;
        None when there is none or it can't be read."""
        if self._kept is None:
            return None
        now = self._clock()
        stored = await self._kept.get(kind, ask, now)
        if stored is None:
            return None
        value, expires_at = stored
        try:
            found = decode(value)
        except (KeyError, TypeError, ValueError):
            log.warning("a kept %s answer wasn't readable", kind, exc_info=True)
            return None
        self._keep(f"{kind}:{ask}", found, expires_at - now)
        return found

    async def _store(self, kind: str, ask: str, value: object, keep: timedelta) -> None:
        if self._kept is not None:
            now = self._clock()
            await self._kept.put(kind, ask, value, now + keep, now)

    async def spot(self, destination: str) -> Spot | None:
        place = first_place(destination)
        ask = place_key(place)
        key = f"spot:{ask}"
        hit = self._cached(key)
        if hit is None:
            hit = await self._stored("spot", ask, _read_spot)
        if hit is not None:
            return hit if isinstance(hit, Spot) else None
        found = await self._source.find(place)
        self._keep(key, found or "none", PLACE_FOR)
        await self._store("spot", ask, {"spot": _write_spot(found)}, PLACE_FOR)
        return found

    async def zone_of(self, place: str) -> str | None:
        """The IANA time zone of a place by name ("Madrid", "Spain"), from the same
        geocoding (and cache) as the weather. None when the place isn't found or the
        service is slow or down: it never raises."""
        if not place.strip():
            return None
        try:
            spot = await asyncio.wait_for(self.spot(place), ZONE_TIMEOUT)
        except TimeoutError:
            log.info("time zone lookup timed out")
            return None
        except Exception:
            log.info("time zone lookup failed", exc_info=True)
            return None
        return spot.timezone if spot is not None else None

    async def for_trip(self, trip: Trip, today: date) -> TripWeather | None:
        """The trip's weather, or None when it's over or the place isn't found.
        Raises WeatherError when the service can't answer."""
        if trip.end < today:
            return None
        spot = await self.spot(trip.destination)
        if spot is None:
            return None
        if forecast_reaches(trip.start, today):
            start = max(trip.start, today)
            end = min(trip.end, today + timedelta(days=FORECAST_DAYS - 1))
            ask = f"{spot.latitude},{spot.longitude}:{start}:{end}"
            key = f"forecast:{ask}"
            days = self._cached(key)
            if not isinstance(days, tuple):
                days = await self._stored("forecast", ask, _read_days)
            if not isinstance(days, tuple):
                days = tuple(await self._source.forecast(spot, start, end))
                self._keep(key, days, FORECAST_FOR)
                await self._store("forecast", ask, _write_days(days), FORECAST_FOR)
            return TripWeather(spot, WeatherKind.FORECAST, days)
        ask = f"{spot.latitude},{spot.longitude}:{trip.start}:{trip.end}"
        key = f"past:{ask}"
        days = self._cached(key)
        if not isinstance(days, tuple):
            days = await self._stored("past", ask, _read_days)
        if not isinstance(days, tuple):
            years = []
            for n in range(1, YEARS + 1):
                recorded = await self._source.past(
                    spot, shifted(trip.start, n), shifted(trip.end, n)
                )
                years.append(
                    [DayWeather(d.day, d.high, d.low, _wet(d.rain), d.code) for d in recorded]
                )
            trip_days = [trip.start + timedelta(days=i) for i in range(trip.days)]
            days = typical(trip_days, years)
            self._keep(key, days, PAST_FOR)
            await self._store("past", ask, _write_days(days), PAST_FOR)
        return TripWeather(spot, WeatherKind.TYPICAL, days)


def _write_spot(spot: Spot | None) -> dict[str, Any] | None:
    return None if spot is None else asdict(spot)


def _read_spot(value: Any) -> Spot | str:
    """A kept place, or the "none" a place that wasn't found is kept as in memory."""
    found = value["spot"]
    return "none" if found is None else Spot(**found)


def _write_days(days: tuple[DayWeather, ...]) -> dict[str, Any]:
    return {"days": [{**asdict(d), "day": d.day.isoformat()} for d in days]}


def _read_days(value: Any) -> tuple[DayWeather, ...]:
    return tuple(DayWeather(**{**d, "day": date.fromisoformat(d["day"])}) for d in value["days"])


def _wet(millimetres: int | None) -> int | None:
    """A recorded day's rain as 100 (rained) or 0, for averaging into a chance."""
    if millimetres is None:
        return None
    return 100 if millimetres >= RAINY_MM else 0
