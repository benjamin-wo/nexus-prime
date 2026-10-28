"""Live prices for the stocks people hold or watch.

While the US market is open, a job fetches a quote for every held or watched stock
every few minutes (and once more just after the close, for the closing price), and a
page a user opens refreshes the quotes for that user's own stocks when they are more
than a minute old. Quotes are market data shared by every user (``market_quotes``).
The exchange's open/closed status is remembered for a few minutes in this process.

Finnhub's free tier allows 60 calls a minute: a run fetches at most 50, a page at most
15, and a 429 stops either. A failure never reaches the user: what is stored is shown.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from nexus.application.market import PRICE_CURRENCY
from nexus.application.ports import UnitOfWork
from nexus.domain.history import MARKET
from nexus.domain.investments import clean_symbol
from nexus.domain.ledger import UserId
from nexus.domain.market import (
    US_MARKET,
    MarketStatus,
    Quote,
    just_closed,
    regular_hours,
    regular_open,
)

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

REFRESH_JOB = "quotes.refresh"
# Quotes fetched per run, and the time after which no new fetch is started (the job's
# own limit is longer); the rest wait for the next run.
MAX_PER_RUN = 50
RUN_BUDGET_SECONDS = 40.0
# After the regular close, the closing price is fetched once within this long.
CLOSE_WINDOW = timedelta(minutes=20)
# The market's status is asked again after this long. A run asks a little sooner, so a
# status kept at one run is never the next run's.
STATUS_TTL = timedelta(minutes=5)
RUN_STATUS_AGE = timedelta(minutes=4)
# A page refreshes a user's quote when it is older than this, for at most this many
# stocks, and gives up after this long (what is stored is shown). The job keeps quotes
# within about 5 minutes 40 seconds (every 5 minutes, up to 40 seconds a run), so a page
# nearly always shows what is stored instead of waiting on the provider.
PAGE_FRESH_FOR = timedelta(minutes=6)
MAX_ON_REQUEST = 15
REQUEST_BUDGET_SECONDS = 3.0
# A plan run sets zones and stops from the price, so it refreshes a quote older than this.
FRESH_FOR = timedelta(seconds=60)
_NEVER = datetime.min.replace(tzinfo=UTC)


class QuoteSourceError(Exception):
    """The provider couldn't answer right now; try again later."""


class QuoteRateLimited(QuoteSourceError):
    """Over the provider's rate limit: stop for now."""


class QuoteSource(Protocol):
    async def quote(self, symbol: str) -> Quote | None:
        """The latest trade; None if the provider has none. Raises QuoteSourceError
        when it can't answer, and QuoteRateLimited when over its limit."""
        ...

    async def market_status(self) -> MarketStatus:
        """Whether the US market is open. Raises QuoteSourceError when it can't answer."""
        ...


class Quotes:
    """A quote source, and the market status it last gave, kept for a few minutes."""

    def __init__(self, source: QuoteSource) -> None:
        self.source = source
        self._status: tuple[MarketStatus, datetime] | None = None

    async def status(
        self, now: datetime, *, max_age: timedelta = STATUS_TTL
    ) -> MarketStatus | None:
        """The market's status, from memory if asked within ``max_age``; None when it
        can't be fetched (the usual hours stand in for it)."""
        kept = self._status
        if kept is not None and timedelta(0) <= now - kept[1] < max_age:
            return kept[0]
        try:
            status = await self.source.market_status()
        except QuoteSourceError as exc:
            log.warning("the market's status couldn't be fetched: %s", exc)
            return None
        except Exception:
            log.exception("the market's status couldn't be fetched")
            return None
        self._status = (status, now)
        return status


async def refresh(uow: UowFactory, quotes: Quotes, *, now: datetime) -> int:
    """The job: fetch quotes for held and watched stocks (and the market, SPY) while the
    regular session is on, and once for each in the 20 minutes after the close. Oldest
    first, at most 50 and 40 seconds a run. Does nothing when the market is shut.
    Returns how many quotes were stored."""
    status = await quotes.status(now, max_age=RUN_STATUS_AGE)
    since = None  # fetch only quotes older than this
    if not regular_open(status, now):
        since = just_closed(status, now, CLOSE_WINDOW)
        if since is None:
            return 0
    async with uow() as tx:
        symbols = await tx.investments.tracked_symbols()
        if symbols and MARKET not in symbols:
            symbols.append(MARKET)
        unlisted = await tx.investments.unlisted(symbols)
        fetched = await tx.investments.quotes_fetched(symbols)
    wanted = [
        s
        for s in symbols
        if s not in unlisted and (since is None or fetched.get(s, _NEVER) < since)
    ]
    wanted.sort(key=lambda s: (fetched.get(s, _NEVER), s))
    got: list[Quote] = []
    started = time.monotonic()
    for symbol in wanted[:MAX_PER_RUN]:
        if time.monotonic() - started > RUN_BUDGET_SECONDS:
            break
        try:
            quote = await quotes.source.quote(symbol)
        except QuoteRateLimited:
            log.warning("over the quote provider's rate limit; the rest wait for the next run")
            break
        except QuoteSourceError as exc:
            log.warning("a quote couldn't be fetched: %s", exc)
            continue
        except Exception:
            log.exception("a quote couldn't be fetched")
            continue
        if quote is not None:
            got.append(quote)
    await _keep(uow, got, now)
    return len(got)


async def _keep(uow: UowFactory, quotes: list[Quote], now: datetime) -> None:
    if quotes:
        async with uow() as tx:
            await tx.investments.upsert_quotes(quotes, at=now)
            await tx.commit()
        _note_extended(quotes)


def _note_extended(quotes: list[Quote]) -> None:
    """Say how many of the quotes just stored were stamped outside the regular session, to
    learn from the logs whether the provider's quote includes extended-hours trades."""
    outside = [q.quoted_at for q in quotes if not regular_hours(q.quoted_at)]
    if outside:
        latest = max(outside).astimezone(US_MARKET)
        log.info(
            "quotes: %d of %d stamped outside regular hours (latest %s ET)",
            len(outside),
            len(quotes),
            f"{latest:%H:%M}",
        )


async def refresh_own(
    uow: UowFactory,
    quotes: Quotes | None,
    user_id: UserId,
    *,
    now: datetime,
    held: bool = False,
    watched: bool = False,
    symbol: str | None = None,
) -> MarketStatus | None:
    """On a user's request: refresh the quotes of the user's own held and/or watched stocks,
    and ``symbol`` (a stock page's own), when the market is open and the stored quote is
    more than 6 minutes old. At most 15 stocks and 3 seconds; any failure is ignored, as
    what is stored is shown. Never asks for a stock that isn't the user's or ``symbol``.
    Returns the market's status as known (None if unknown), to price with."""
    if quotes is None:
        return None
    status: MarketStatus | None = None
    got: list[Quote] = []
    try:
        async with asyncio.timeout(REQUEST_BUDGET_SECONDS):
            wanted = await _own_symbols(uow, user_id, held=held, watched=watched, symbol=symbol)
            status = await quotes.status(now)
            if wanted and regular_open(status, now):
                async with uow() as tx:
                    fetched = await tx.investments.quotes_fetched(wanted)
                stale = [s for s in wanted if now - fetched.get(s, _NEVER) > PAGE_FRESH_FOR]
                stale.sort(key=lambda s: fetched.get(s, _NEVER))
                await asyncio.gather(*(_ask(quotes.source, s, got) for s in stale[:MAX_ON_REQUEST]))
    except TimeoutError:
        log.info("quotes for a page took too long; showing what is stored")
    except Exception:
        log.exception("quotes for a page couldn't be refreshed")
    try:
        await _keep(uow, got, now)
    except Exception:
        log.exception("quotes for a page couldn't be stored")
    return status


async def refresh_symbol(
    uow: UowFactory, quotes: Quotes | None, symbol: str, *, now: datetime
) -> MarketStatus | None:
    """For a plan run: refresh one stock's quote when the regular session is on, or in the
    20 minutes after the close (for the closing price), and the stored quote is more than a
    minute old. Gives up after 3 seconds and ignores any failure: what is stored is used.
    Returns the market's status as known (None if unknown), to price with."""
    if quotes is None:
        return None
    status: MarketStatus | None = None
    got: list[Quote] = []
    try:
        async with asyncio.timeout(REQUEST_BUDGET_SECONDS):
            status = await quotes.status(now)
            if regular_open(status, now) or just_closed(status, now, CLOSE_WINDOW) is not None:
                async with uow() as tx:
                    fetched = (await tx.investments.quotes_fetched([symbol])).get(symbol, _NEVER)
                if now - fetched > FRESH_FOR:
                    await _ask(quotes.source, symbol, got)
    except TimeoutError:
        log.info("a quote for a plan took too long; using what is stored")
    except Exception:
        log.exception("a quote for a plan couldn't be refreshed")
    try:
        await _keep(uow, got, now)
    except Exception:
        log.exception("a quote for a plan couldn't be stored")
    return status


async def _own_symbols(
    uow: UowFactory, user_id: UserId, *, held: bool, watched: bool, symbol: str | None
) -> list[str]:
    """The user's own stocks to ask about, each once. Only prices in USD are quoted."""
    found: list[str] = []
    async with uow() as tx:
        if held:
            found += [
                h.position.symbol
                for h in await tx.investments.list_holdings(user_id)
                if h.position.average_cost.currency == PRICE_CURRENCY
            ]
        if watched:
            found += await tx.investments.list_watch(user_id)
    if symbol is not None:
        found.append(clean_symbol(symbol))
    return list(dict.fromkeys(found))


async def _ask(source: QuoteSource, symbol: str, got: list[Quote]) -> None:
    try:
        quote = await source.quote(symbol)
    except QuoteSourceError as exc:
        log.info("a quote couldn't be fetched for a page: %s", exc)
        return
    except Exception:
        log.exception("a quote couldn't be fetched for a page")
        return
    if quote is not None:
        got.append(quote)
