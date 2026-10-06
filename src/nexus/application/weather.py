"""The weather on a trip page: the forecast for the trip's days once a forecast reaches
them, and before that what the same dates were like over the last three years.

Nothing is stored. Answers are kept in memory for a while (forecasts a few hours,
past years a week), so pages don't ask again on every visit.
"""

import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Protocol

from nexus.application.clock import utcnow
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
    def __init__(self, source: WeatherSource, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._source = source
        self._clock = clock
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

    async def spot(self, destination: str) -> Spot | None:
        place = first_place(destination)
        key = f"spot:{place_key(place)}"
        if key in self._cache and (hit := self._cached(key)) is not None:
            return hit if isinstance(hit, Spot) else None
        found = await self._source.find(place)
        self._keep(key, found or "none", PLACE_FOR)
        return found

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
            key = f"forecast:{spot.latitude},{spot.longitude}:{start}:{end}"
            days = self._cached(key)
            if not isinstance(days, tuple):
                days = tuple(await self._source.forecast(spot, start, end))
                self._keep(key, days, FORECAST_FOR)
            return TripWeather(spot, WeatherKind.FORECAST, days)
        key = f"past:{spot.latitude},{spot.longitude}:{trip.start}:{trip.end}"
        days = self._cached(key)
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
        return TripWeather(spot, WeatherKind.TYPICAL, days)


def _wet(millimetres: int | None) -> int | None:
    """A recorded day's rain as 100 (rained) or 0, for averaging into a chance."""
    if millimetres is None:
        return None
    return 100 if millimetres >= RAINY_MM else 0
