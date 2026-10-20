"""Company news and earnings dates from Finnhub (free tier: North American
companies, 60 calls a minute). Quotes and market status are in ``finnhub_quotes``.

``GET /company-news?symbol=…&from=…&to=…`` and ``GET /calendar/earnings?symbol=…``.
The key goes in a header, never the URL. Everything that comes back is someone
else's text: it's cleaned, links must be plain http(s), and rows that don't parse
are dropped.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

from nexus.application.research import NewsRateLimited, NewsSourceError
from nexus.domain.news import (
    MAX_HEADLINE,
    MAX_SOURCE,
    MAX_SUMMARY,
    EarningsDate,
    NewsItem,
    clean_text,
    safe_url,
)

log = logging.getLogger(__name__)

BASE_URL = "https://finnhub.io/api/v1"
MAX_ITEMS = 50  # per stock per fetch: the newest
_TIMING = {"bmo": "before open", "amc": "after close"}


async def get_json(
    http: httpx.AsyncClient,
    base_url: str,
    key: str,
    path: str,
    params: dict[str, str],
    *,
    error: type[Exception],
    rate_limited: type[Exception],
    seconds: float = 15.0,
) -> Any:
    """One Finnhub GET, the answer as JSON. The key goes in a header, never the URL.
    Failures are raised as ``error``, and a 429 as ``rate_limited``."""
    try:
        response = await http.get(
            f"{base_url.rstrip('/')}{path}",
            params=params,
            headers={"X-Finnhub-Token": key},
            timeout=seconds,
        )
    except httpx.HTTPError as exc:
        raise error(f"request failed: {type(exc).__name__}") from exc
    if response.status_code == 429:
        raise rate_limited("HTTP 429")
    if response.status_code != 200:
        raise error(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise error("unexpected response") from exc


class FinnhubNews:
    def __init__(self, http: httpx.AsyncClient, api_key: str, *, base_url: str = BASE_URL) -> None:
        self._http = http
        self._key = api_key
        self._base_url = base_url.rstrip("/")

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        return await get_json(
            self._http,
            self._base_url,
            self._key,
            path,
            params,
            error=NewsSourceError,
            rate_limited=NewsRateLimited,
        )

    async def news(self, symbol: str, start: date, end: date) -> list[NewsItem]:
        rows = await self._get(
            "/company-news", {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()}
        )
        if not isinstance(rows, list):
            raise NewsSourceError("unexpected response")
        items = [i for i in (_item(symbol, row) for row in rows) if i is not None]
        items.sort(key=lambda i: i.published_at, reverse=True)
        return items[:MAX_ITEMS]

    async def earnings(self, symbol: str, start: date, end: date) -> list[EarningsDate]:
        body = await self._get(
            "/calendar/earnings",
            {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()},
        )
        rows = body.get("earningsCalendar") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise NewsSourceError("unexpected response")
        found = []
        for row in rows:
            try:
                if str(row.get("symbol", symbol)).upper() != symbol.upper():
                    continue
                day = date.fromisoformat(str(row["date"]))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if start <= day <= end:
                found.append(EarningsDate(symbol, day, _TIMING.get(str(row.get("hour") or ""))))
        return sorted(set(found), key=lambda d: d.day)


def _item(symbol: str, row: Any) -> NewsItem | None:
    try:
        url = safe_url(row.get("url"))
        headline = clean_text(row.get("headline"), MAX_HEADLINE)
        published = datetime.fromtimestamp(int(row["datetime"]), UTC)
        external_id = str(row.get("id") or url or "")[:200]
    except (KeyError, TypeError, ValueError, OverflowError, OSError, AttributeError):
        return None
    if url is None or not headline or not external_id:
        return None
    return NewsItem(
        symbol=symbol,
        external_id=external_id,
        headline=headline,
        source=clean_text(row.get("source"), MAX_SOURCE) or "unknown",
        url=url,
        summary=clean_text(row.get("summary"), MAX_SUMMARY),
        published_at=published,
    )
