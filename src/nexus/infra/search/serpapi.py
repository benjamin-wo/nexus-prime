"""Flight and hotel prices from Google Flights and Google Hotels, through SerpApi
(free tier: 250 searches a month).

``GET https://serpapi.com/search?engine=google_flights|google_hotels&…``. SerpApi
takes its key only as a query parameter, so request URLs are never logged (httpx
logs at WARNING) and errors name only the exception type. Each search links to
the Google page with the live prices; nothing is booked.
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from nexus.application.travel_research import (
    FlightQuote,
    HotelQuote,
    HotelSearch,
    WebSearchError,
)

log = logging.getLogger(__name__)

URL = "https://serpapi.com/search"
MAX_HOTELS = 8


def _decimal(value: Any) -> Decimal | None:
    try:
        found = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return found if found.is_finite() and found > 0 else None


class SerpApiTravel:
    def __init__(self, http: httpx.AsyncClient, api_key: str) -> None:
        self._http = http
        self._key = api_key

    async def _get(self, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._http.get(
                URL, params={**params, "hl": "en", "api_key": self._key}, timeout=40.0
            )
        except httpx.HTTPError as exc:
            raise WebSearchError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise WebSearchError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise WebSearchError("unexpected response") from exc
        if not isinstance(data, dict) or data.get("error"):
            raise WebSearchError("no results")
        return data

    async def flights(
        self, origin: str, destination: str, outbound: date, back: date, currency: str, adults: int
    ) -> FlightQuote | None:
        data = await self._get(
            {
                "engine": "google_flights",
                "departure_id": origin,
                "arrival_id": destination,
                "outbound_date": outbound.isoformat(),
                "return_date": back.isoformat(),
                "currency": currency,
                "adults": str(adults),
                "type": "1",  # return
            }
        )
        insights = data.get("price_insights") or {}
        prices = [
            p
            for f in [*(data.get("best_flights") or []), *(data.get("other_flights") or [])]
            if isinstance(f, dict) and (p := _decimal(f.get("price"))) is not None
        ]
        typical = insights.get("typical_price_range") or []
        low = _decimal(insights.get("lowest_price")) or (min(prices) if prices else None)
        if low is None:
            return None
        high = _decimal(typical[1]) if len(typical) == 2 else (max(prices) if prices else low)
        url = (data.get("search_metadata") or {}).get("google_flights_url")
        # Prices are for all the adults together: per person for the estimate.
        n = Decimal(max(adults, 1))
        return FlightQuote(
            low / n, (high or low) / n, currency, url if isinstance(url, str) else None
        )

    async def hotels(
        self, query: str, check_in: date, check_out: date, currency: str, adults: int
    ) -> HotelSearch | None:
        data = await self._get(
            {
                "engine": "google_hotels",
                "q": query,
                "check_in_date": check_in.isoformat(),
                "check_out_date": check_out.isoformat(),
                "currency": currency,
                "adults": str(min(adults, 2)),  # one room
            }
        )
        rates: list[HotelQuote] = []
        for prop in data.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            nightly = _decimal((prop.get("rate_per_night") or {}).get("extracted_lowest"))
            if nightly is not None and isinstance(prop.get("name"), str):
                rates.append(HotelQuote(prop["name"][:80], nightly, currency))
            if len(rates) >= MAX_HOTELS:
                break
        if not rates:
            return None
        url = (data.get("search_metadata") or {}).get("google_hotels_url")
        return HotelSearch(rates, url if isinstance(url, str) else None)
