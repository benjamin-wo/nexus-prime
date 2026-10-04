"""Company news and earnings dates from Finnhub (free tier: North American
companies, 60 calls a minute).

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


class FinnhubNews:
    def __init__(self, http: httpx.AsyncClient, api_key: str, *, base_url: str = BASE_URL) -> None:
        self._http = http
        self._key = api_key
        self._base_url = base_url.rstrip("/")

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        try:
            response = await self._http.get(
                f"{self._base_url}{path}",
                params=params,
                headers={"X-Finnhub-Token": self._key},
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            raise NewsSourceError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code == 429:
            raise NewsRateLimited("HTTP 429")
        if response.status_code != 200:
            raise NewsSourceError(f"HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise NewsSourceError("unexpected response") from exc

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
