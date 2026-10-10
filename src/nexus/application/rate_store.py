"""Exchange rates kept once looked up. A past day's reference rate never changes, so
it's fetched from the provider once and read from the database after that, across
restarts. Today's isn't kept: the day's rate may not be published yet."""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

from nexus.application.fx import Rate, RateSource
from nexus.application.ports import UnitOfWork

log = logging.getLogger(__name__)

_MEMORY_LIMIT = 4096


def _utc_today() -> date:
    return datetime.now(UTC).date()


class StoredRates:
    """A ``RateSource`` that asks ``source`` only for rates it hasn't kept yet. If the
    database can't be reached, it still answers from ``source``."""

    def __init__(
        self,
        source: RateSource,
        uow: Callable[[], UnitOfWork],
        *,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self._source = source
        self._uow = uow
        self._today = today
        self._memory: dict[tuple[str, str, date], Rate] = {}

    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        if on >= self._today():
            return await self._source.rate(base, quote, on)
        key = (base, quote, on)
        if key in self._memory:
            return self._memory[key]
        kept = await self._kept(base, quote, on)
        if kept is not None:
            self._remember(key, kept)
            return kept
        found = await self._source.rate(base, quote, on)
        if found is not None and found.effective <= on and found.value > 0:
            await self._keep(on, found)
            self._remember(key, found)
        return found

    def _remember(self, key: tuple[str, str, date], rate: Rate) -> None:
        if len(self._memory) >= _MEMORY_LIMIT:
            self._memory.clear()
        self._memory[key] = rate

    async def _kept(self, base: str, quote: str, on: date) -> Rate | None:
        try:
            async with self._uow() as db:
                return await db.rates.stored_rate(base, quote, on)
        except Exception:
            log.warning("couldn't read a kept rate %s->%s on %s", base, quote, on, exc_info=True)
            return None

    async def _keep(self, on: date, rate: Rate) -> None:
        try:
            async with self._uow() as db:
                await db.rates.save_rate(on, rate)
                await db.commit()
        except Exception:
            log.warning(
                "couldn't keep a rate %s->%s on %s", rate.base, rate.quote, on, exc_info=True
            )
