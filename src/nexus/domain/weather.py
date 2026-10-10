"""The weather for a trip: the forecast once the trip is near, or what the same dates
were like in recent years before that. Pure rules, no I/O."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from statistics import mean

from nexus.domain.packing import Outlook

FORECAST_DAYS = 16  # how far ahead a forecast reaches
YEARS = 3  # recent years averaged for "typical"
RAINY_MM = 1.0  # a day with at least this much rain counts as rainy
LIKELY = 50  # a chance of rain from here on is "likely"


class WeatherKind(StrEnum):
    FORECAST = "forecast"
    TYPICAL = "typical"  # from the same dates in recent years


@dataclass(frozen=True, slots=True)
class DayWeather:
    day: date
    high: float | None  # °C
    low: float | None
    rain: int | None  # chance of rain, %
    code: int | None  # WMO weather code


@dataclass(frozen=True, slots=True)
class Spot:
    """Where the weather is for: a place found by name."""

    name: str
    country: str | None
    latitude: float
    longitude: float
    country_code: str | None = None  # ISO 3166, e.g. JP


@dataclass(frozen=True, slots=True)
class TripWeather:
    place: Spot
    kind: WeatherKind
    days: tuple[DayWeather, ...]

    def outlook(self) -> Outlook:
        lows = [d.low for d in self.days if d.low is not None]
        highs = [d.high for d in self.days if d.high is not None]
        return Outlook(
            low=min(lows) if lows else None,
            high=max(highs) if highs else None,
            rain=any(d.rain is not None and d.rain >= LIKELY for d in self.days),
        )


# WMO weather codes, as Open-Meteo reports them, in a few words.
_CODES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy",
    45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain", 63: "Rain",
    65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain", 71: "Light snow",
    73: "Snow", 75: "Heavy snow", 77: "Snow", 80: "Showers", 81: "Showers",
    82: "Heavy showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorms",
    96: "Thunderstorms", 99: "Thunderstorms",
}  # fmt: skip


def describe(code: int | None) -> str | None:
    return _CODES.get(code) if code is not None else None


def forecast_reaches(start: date, today: date) -> bool:
    """Whether a forecast reaches the trip's first day yet."""
    return (start - today).days < FORECAST_DAYS


def typical(trip_days: list[date], years: list[list[DayWeather]]) -> tuple[DayWeather, ...]:
    """Each trip day as it was on average in the years given (each a list of days
    in the trip's order): mean high and low, the share of years it rained as the
    chance of rain, and the most common weather."""
    out = []
    for i, day in enumerate(trip_days):
        same = [y[i] for y in years if i < len(y)]
        highs = [d.high for d in same if d.high is not None]
        lows = [d.low for d in same if d.low is not None]
        wet = [d.rain for d in same if d.rain is not None]
        codes = [d.code for d in same if d.code is not None]
        out.append(
            DayWeather(
                day=day,
                high=round(mean(highs), 1) if highs else None,
                low=round(mean(lows), 1) if lows else None,
                rain=round(100 * sum(1 for r in wet if r > 0) / len(wet)) if wet else None,
                code=Counter(codes).most_common(1)[0][0] if codes else None,
            )
        )
    return tuple(out)


def shifted(day: date, years: int) -> date:
    """The same day ``years`` earlier (29 February becomes the 28th)."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)
