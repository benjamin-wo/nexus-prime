"""Weather from Open-Meteo (open-meteo.com): no key, free for non-commercial use, data
under CC BY 4.0 (the page credits it).

``GET geocoding-api.open-meteo.com/v1/search?name=`` finds a place;
``GET api.open-meteo.com/v1/forecast`` gives up to 16 days ahead;
``GET archive-api.open-meteo.com/v1/archive`` gives recorded days.
"""

import logging
from datetime import date
from typing import Any

import httpx

from nexus.application.weather import WeatherError
from nexus.domain.places import quoted
from nexus.domain.weather import DayWeather, Spot

log = logging.getLogger(__name__)

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


class OpenMeteo:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        geocode_url: str = GEOCODE,
        forecast_url: str = FORECAST,
        archive_url: str = ARCHIVE,
    ) -> None:
        self._http = http
        self._geocode = geocode_url
        self._forecast = forecast_url
        self._archive = archive_url

    async def _get(self, url: str, params: dict[str, str]) -> Any:
        try:
            response = await self._http.get(url, params=params, timeout=15.0)
        except httpx.HTTPError as exc:
            raise WeatherError(type(exc).__name__) from exc
        if response.status_code != 200:
            raise WeatherError(f"Open-Meteo answered {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise WeatherError("Open-Meteo's answer wasn't JSON") from exc

    async def find(self, name: str) -> Spot | None:
        if not name.strip():
            return None
        data = await self._get(
            self._geocode, {"name": name.strip()[:80], "count": "1", "language": "en"}
        )
        rows = data.get("results") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None
        row = rows[0]
        lat, lon = row.get("latitude"), row.get("longitude")
        if not isinstance(lat, int | float) or not isinstance(lon, int | float):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return Spot(
            name=quoted(row.get("name"), 80) or name,
            country=quoted(row.get("country"), 80),
            latitude=float(lat),
            longitude=float(lon),
        )

    async def forecast(self, spot: Spot, start: date, end: date) -> list[DayWeather]:
        data = await self._get(
            self._forecast,
            {
                **_where(spot, start, end),
                "daily": "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,weather_code",
            },
        )
        return _days(data, "precipitation_probability_max")

    async def past(self, spot: Spot, start: date, end: date) -> list[DayWeather]:
        data = await self._get(
            self._archive,
            {
                **_where(spot, start, end),
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
            },
        )
        return _days(data, "precipitation_sum")


def _where(spot: Spot, start: date, end: date) -> dict[str, str]:
    return {
        "latitude": f"{spot.latitude:.4f}",
        "longitude": f"{spot.longitude:.4f}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "auto",
    }


def _number(values: Any, i: int) -> float | None:
    if not isinstance(values, list) or i >= len(values):
        return None
    value = values[i]
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _days(data: Any, rain_field: str) -> list[DayWeather]:
    daily = data.get("daily") if isinstance(data, dict) else None
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        raise WeatherError("Open-Meteo's answer had no days")
    out = []
    for i, raw in enumerate(daily["time"]):
        try:
            day = date.fromisoformat(str(raw))
        except ValueError:
            continue
        rain = _number(daily.get(rain_field), i)
        code = _number(daily.get("weather_code"), i)
        out.append(
            DayWeather(
                day=day,
                high=_number(daily.get("temperature_2m_max"), i),
                low=_number(daily.get("temperature_2m_min"), i),
                rain=round(rain) if rain is not None else None,
                code=int(code) if code is not None else None,
            )
        )
    return out
