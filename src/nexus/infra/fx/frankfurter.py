"""Dated reference rates from Frankfurter (European Central Bank data).

``GET /v1/{date}?base=USD&symbols=SGD`` answers with the rate published on
that date or, on weekends and holidays, the last business day before it.
Rates for past days never change, so they are cached in memory; today's
answer is not, because the day's rate may not be published yet.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from nexus.application.fx import Rate

log = logging.getLogger(__name__)

BASE_URL = "https://api.frankfurter.dev/v1"
_CACHE_LIMIT = 4096


def _utc_today() -> date:
    return datetime.now(UTC).date()


class FrankfurterRates:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str = BASE_URL,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._today = today
        self._cache: dict[tuple[str, str, date], Rate | None] = {}

    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        key = (base, quote, on)
        if key in self._cache:
            return self._cache[key]
        try:
            response = await self._http.get(
                f"{self._base_url}/{on.isoformat()}",
                params={"base": base, "symbols": quote},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            log.warning("fx lookup %s->%s on %s failed: %s", base, quote, on, type(exc).__name__)
            return None
        if response.status_code == 404:
            found = None  # currency or date not covered
        elif response.status_code != 200:
            log.warning("fx lookup %s->%s on %s: HTTP %s", base, quote, on, response.status_code)
            return None
        else:
            found = self._parse(response, base, quote, on)
            if found is None:
                return None
        if on < self._today():
            if len(self._cache) >= _CACHE_LIMIT:
                self._cache.clear()
            self._cache[key] = found
        return found

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
