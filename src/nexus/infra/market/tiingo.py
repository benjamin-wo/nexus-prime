"""Daily US stock prices from Tiingo's end-of-day API.

``GET /tiingo/daily/{ticker}/prices?startDate=…&endDate=…`` answers with one row
per trading day. The key goes in a header, never the URL, so it can't end up in
request logs.
"""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from nexus.application.market import PriceSourceError
from nexus.domain.market import Bar

log = logging.getLogger(__name__)

BASE_URL = "https://api.tiingo.com"


def tiingo_symbol(symbol: str) -> str:
    """Tiingo writes share classes with a dash: BRK.B is "BRK-B"."""
    return symbol.replace(".", "-").lower()


class TiingoPrices:
    def __init__(self, http: httpx.AsyncClient, api_key: str, *, base_url: str = BASE_URL) -> None:
        self._http = http
        self._key = api_key
        self._base_url = base_url.rstrip("/")

    async def daily(self, symbol: str, start: date, end: date) -> list[Bar] | None:
        try:
            response = await self._http.get(
                f"{self._base_url}/tiingo/daily/{tiingo_symbol(symbol)}/prices",
                params={"startDate": start.isoformat(), "endDate": end.isoformat()},
                headers={"Authorization": f"Token {self._key}"},
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            raise PriceSourceError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PriceSourceError(f"HTTP {response.status_code}")
        try:
            rows = response.json()
        except ValueError as exc:
            raise PriceSourceError("unexpected response") from exc
        if not isinstance(rows, list):
            raise PriceSourceError("unexpected response")
        bars = [b for b in (_bar(symbol, row) for row in rows) if b is not None]
        if len(bars) < len(rows):
            log.warning("skipped %d price rows that didn't parse", len(rows) - len(bars))
        return sorted(bars, key=lambda b: b.day)


def _decimal(value: Any) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("not a price")
    return number.quantize(Decimal("0.000001"))


def _bar(symbol: str, row: Any) -> Bar | None:
    try:
        close = _decimal(row["close"])
        if close == 0:
            return None
        return Bar(
            symbol=symbol,
            day=datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00")).date(),
            open=_decimal(row.get("open", close)),
            high=_decimal(row.get("high", close)),
            low=_decimal(row.get("low", close)),
            close=close,
            adj_close=_decimal(row.get("adjClose", close)),
            volume=int(row.get("volume") or 0),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        return None
