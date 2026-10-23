"""Dated reference rates from Frankfurter (European Central Bank data).

``GET /v1/{date}?base=USD&symbols=SGD`` answers with the rate published on
that date or, on weekends and holidays, the last business day before it.
Rates for past days never change, so they are cached in memory. Today's answer
is cached only briefly, because the day's rate may not be published yet. A lookup
that fails is waited for only ``LOOKUP_SECONDS`` and then not retried for a while,
so a slow provider costs a chat turn one short wait, not one per turn.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from nexus.application.fx import Rate

log = logging.getLogger(__name__)

BASE_URL = "https://api.frankfurter.dev/v1"
_CACHE_LIMIT = 4096
# A rate is on the path of every chat turn, so the whole lookup (connecting and reading)
# gets this long. Background jobs use the same: they fall back on a kept rate too.
LOOKUP_SECONDS = 2.0
# How long a failed lookup, and today's rate once found, are remembered per pair and day.
FAILURE_MEMORY_SECONDS = 600.0
TODAY_MEMORY_SECONDS = 600.0


def _utc_today() -> date:
    return datetime.now(UTC).date()


class FrankfurterRates:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str = BASE_URL,
        today: Callable[[], date] = _utc_today,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._today = today
        self._monotonic = monotonic
        # Answers by (base, quote, day), with when each lapses (None: never, a past day).
        self._cache: dict[tuple[str, str, date], tuple[Rate | None, float | None]] = {}
        self._failed: dict[tuple[str, str, date], float] = {}  # key -> when to try again

    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        key = (base, quote, on)
        now = self._monotonic()
        if key in self._cache:
            found, until = self._cache[key]
            if until is None or now < until:
                return found
            del self._cache[key]
        if now < self._failed.get(key, 0.0):
            return None
        try:
            async with asyncio.timeout(LOOKUP_SECONDS):
                response = await self._http.get(
                    f"{self._base_url}/{on.isoformat()}",
                    params={"base": base, "symbols": quote},
                    timeout=LOOKUP_SECONDS,
                )
        except (httpx.HTTPError, TimeoutError) as exc:
            log.warning("fx lookup %s->%s on %s failed: %s", base, quote, on, type(exc).__name__)
            self._failure(key, now)
            return None
        if response.status_code == 404:
            found = None  # currency or date not covered
        elif response.status_code != 200:
            log.warning("fx lookup %s->%s on %s: HTTP %s", base, quote, on, response.status_code)
            self._failure(key, now)
            return None
        else:
            found = self._parse(response, base, quote, on)
            if found is None:
                self._failure(key, now)
                return None
        self._failed.pop(key, None)
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        # Today's rate may not be published yet, or may be revised: kept only briefly.
        today = on >= self._today()
        self._cache[key] = (found, now + TODAY_MEMORY_SECONDS if today else None)
        return found

    def _failure(self, key: tuple[str, str, date], now: float) -> None:
        """Remember the failure so the pair isn't asked again for a while."""
        if len(self._failed) >= _CACHE_LIMIT:
            self._failed.clear()
        self._failed[key] = now + FAILURE_MEMORY_SECONDS

    @staticmethod
    def _parse(response: httpx.Response, base: str, quote: str, on: date) -> Rate | None:
        try:
            body = response.json()
            value = Decimal(str(body["rates"][quote]))
            effective = date.fromisoformat(body["date"])
        except (ValueError, KeyError, TypeError, InvalidOperation):
            log.warning("fx lookup %s->%s on %s: unexpected response", base, quote, on)
            return None
        if body.get("base") != base or effective > on or not value.is_finite() or value <= 0:
            log.warning("fx lookup %s->%s on %s: rejected response", base, quote, on)
            return None
        return Rate(base, quote, value, effective)
