"""Live US stock quotes and the market's open/closed status from Finnhub (free tier:
60 calls a minute).

``GET /quote?symbol=…`` answers with the latest trade (``c`` price, ``pc`` previous
close, ``h``/``l``/``o`` the day's range and open, ``t`` when, in Unix seconds), and
``GET /stock/market-status?exchange=US`` with ``isOpen``, ``session`` and ``holiday``.
The key goes in a header, never the URL (see ``finnhub.get_json``). A symbol Finnhub
doesn't know answers with zeros: that is "no quote", not an error.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from nexus.application.quotes import QuoteRateLimited, QuoteSourceError
from nexus.domain.market import MarketStatus, Quote
from nexus.domain.news import clean_text
from nexus.infra.market.finnhub import BASE_URL, get_json

log = logging.getLogger(__name__)

SESSIONS = ("pre-market", "regular", "post-market")
MAX_HOLIDAY = 80
_PRICE = Decimal("0.0001")


class FinnhubQuotes:
    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 10.0,
    ) -> None:
        self._http = http
        self._key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        return await get_json(
            self._http,
            self._base_url,
            self._key,
            path,
            params,
            error=QuoteSourceError,
            rate_limited=QuoteRateLimited,
            seconds=self._timeout,
        )

    async def quote(self, symbol: str) -> Quote | None:
        """The latest trade, or None when Finnhub has none (an unknown symbol)."""
        body = await self._get("/quote", {"symbol": symbol})
        if not isinstance(body, dict):
            raise QuoteSourceError("unexpected response")
        try:
            price, prev_close = _price(body["c"]), _price(body.get("pc") or 0)
            stamp = int(body["t"])
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise QuoteSourceError("unexpected response") from None
        if price == 0 or stamp == 0:
            return None
        try:
            quoted_at = datetime.fromtimestamp(stamp, UTC)
        except (OverflowError, OSError, ValueError):
            raise QuoteSourceError("unexpected response") from None
        return Quote(
            symbol=symbol,
            price=price,
            prev_close=prev_close,
            high=_optional(body.get("h")),
            low=_optional(body.get("l")),
            open=_optional(body.get("o")),
            quoted_at=quoted_at,
        )

    async def market_status(self) -> MarketStatus:
        body = await self._get("/stock/market-status", {"exchange": "US"})
        if not isinstance(body, dict) or not isinstance(body.get("isOpen"), bool):
            raise QuoteSourceError("unexpected response")
        session = body.get("session")
        holiday = clean_text(body.get("holiday"), MAX_HOLIDAY) if body.get("holiday") else ""
        return MarketStatus(
            is_open=body["isOpen"],
            session=session if session in SESSIONS else None,
            holiday=holiday or None,
            checked_at=_checked_at(body.get("t")),
        )


def _price(value: Any) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("not a price")
    return number.quantize(_PRICE)


def _optional(value: Any) -> Decimal | None:
    """A day's high, low or open: None when absent, zero or not a price."""
    try:
        number = _price(value) if value is not None else Decimal(0)
    except (ValueError, InvalidOperation):
        return None
    return number or None


def _checked_at(stamp: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(stamp), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return datetime.now(UTC)
