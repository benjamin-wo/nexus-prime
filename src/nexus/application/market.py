"""Keeping daily prices for the stocks people hold. End-of-day data only.

A refresh fetches each held stock once its trading day's prices are due (after
the US close), a few days back so a corrected close replaces the old one. A
stock fetched for the first time gets a long history, which M13b's moving
averages need. One stock's failure doesn't stop the others.
"""

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Protocol

from nexus.application.ports import UnitOfWork
from nexus.domain.market import Bar, due

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

REFRESH_JOB = "prices.refresh"
# Enough trading days for a 200-day average, with room to spare.
HISTORY_DAYS = 450
# Days re-fetched before the last one stored, for corrections.
OVERLAP_DAYS = 7
# Fetches per refresh, well inside free-tier hourly limits; the rest wait for the
# next refresh.
MAX_PER_REFRESH = 40
# Stop starting new fetches after this long, well inside the job's time limit;
# what's left is still due at the next refresh.
REFRESH_BUDGET_SECONDS = 50.0
# The currency the provider's prices are in (US stocks).
PRICE_CURRENCY = "USD"


class PriceSourceError(Exception):
    """The provider couldn't answer right now; try again later."""


class PriceSource(Protocol):
    async def daily(self, symbol: str, start: date, end: date) -> list[Bar] | None:
        """Daily prices from ``start`` to ``end``, oldest first; None if the provider
        doesn't know the stock. Raises PriceSourceError when it can't answer."""
        ...


async def queue_refresh(uow: UnitOfWork, now: datetime) -> None:
    """Fetch prices soon (a stock was just added), inside the caller's transaction.
    One job per minute, however many saves."""
    minute = now.replace(second=0, microsecond=0)
    await uow.jobs.enqueue(
        REFRESH_JOB, {}, dedupe_key=f"{REFRESH_JOB}@{minute.isoformat()}", run_at=now
    )


async def refresh(uow: UowFactory, source: PriceSource, *, now: datetime) -> int:
    """Fetch prices for held stocks that are due. Returns how many were fetched."""
    async with uow() as tx:
        symbols = await tx.investments.held_symbols()
        fetched = await tx.investments.fetched(symbols)
    wanted = [s for s in symbols if due(fetched.get(s), now)][:MAX_PER_REFRESH]
    done = 0
    started = time.monotonic()
    for symbol in wanted:
        if time.monotonic() - started > REFRESH_BUDGET_SECONDS:
            break
        try:
            await _fetch(uow, source, symbol, now)
            done += 1
        except PriceSourceError as exc:
            log.warning("prices for a stock couldn't be fetched: %s", exc)
        except Exception:
            log.exception("prices for a stock couldn't be fetched")
    return done


async def _fetch(uow: UowFactory, source: PriceSource, symbol: str, now: datetime) -> None:
    async with uow() as tx:
        last = await tx.investments.last_bar_day(symbol)
    today = now.date()
    start = last - timedelta(days=OVERLAP_DAYS) if last else today - timedelta(days=HISTORY_DAYS)
    bars = await source.daily(symbol, start, today)
    async with uow() as tx:
        await tx.investments.save_bars(symbol, bars or [], known=bars is not None, at=now)
        await tx.commit()
    if bars is None:
        log.info("the price provider doesn't know one of the held stocks")
