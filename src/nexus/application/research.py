"""What the research team reads besides prices: levels worked out in code, news
and upcoming earnings dates, and the user's watchlist.

News and earnings dates are fetched for every held or watched stock every few
hours, kept a month, and shared by all users (they're public). A stock is shown
with whatever has arrived; nothing here asks a model anything.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

from nexus.application.market import queue_refresh
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.history import MARKET, History, history
from nexus.domain.investments import Position
from nexus.domain.ledger import User, UserId
from nexus.domain.levels import YEAR_DAYS, Levels, compute
from nexus.domain.market import Bar
from nexus.domain.news import EarningsDate, NewsItem, dedupe
from nexus.domain.odds import Range, ranges, returns

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

# News and earnings dates are fetched again after this long.
NEWS_EVERY = timedelta(hours=6)
NEWS_DAYS = 7  # how far back each fetch looks
KEEP_NEWS = timedelta(days=30)
EARNINGS_DAYS = 90  # how far ahead earnings dates are looked for
PAST_EARNINGS_DAYS = 366  # and back, for how the stock moved on them
MAX_PER_REFRESH = 25  # two calls each, inside the free tier's 60 a minute
REFRESH_BUDGET_SECONDS = 50.0
MAX_WATCH = 50
# Bars read to work out levels: a year, plus room for the 200-day average.
LEVEL_BARS = YEAR_DAYS + 30
NEWS_SHOWN = 8


class NewsSourceError(Exception):
    """The provider couldn't answer right now; try again later."""


class NewsRateLimited(NewsSourceError):
    """Over the provider's rate limit: stop for now."""


class NewsSource(Protocol):
    async def news(self, symbol: str, start: date, end: date) -> list[NewsItem]:
        """Headlines about the stock published between the two days."""
        ...

    async def earnings(self, symbol: str, start: date, end: date) -> list[EarningsDate]:
        """Earnings dates between the two days."""
        ...


async def refresh_news(uow: UowFactory, source: NewsSource, *, now: datetime) -> int:
    """Fetch news and earnings dates for tracked stocks not fetched lately, and drop
    news older than a month. Returns how many stocks were fetched."""
    async with uow() as tx:
        symbols = await tx.investments.tracked_symbols()
        fetched = await tx.investments.news_fetched(symbols)
        await tx.investments.purge_news(now - KEEP_NEWS)
        await tx.commit()
    wanted = [s for s in symbols if (f := fetched.get(s)) is None or now - f >= NEWS_EVERY]
    done = 0
    started = time.monotonic()
    for symbol in wanted[:MAX_PER_REFRESH]:
        if time.monotonic() - started > REFRESH_BUDGET_SECONDS:
            break
        try:
            today = now.date()
            items = await source.news(symbol, today - timedelta(days=NEWS_DAYS), today)
            dates = await source.earnings(
                symbol,
                today - timedelta(days=PAST_EARNINGS_DAYS),
                today + timedelta(days=EARNINGS_DAYS),
            )
        except NewsRateLimited:
            log.warning("over the news provider's rate limit; the rest wait for the next refresh")
            break
        except NewsSourceError as exc:
            log.warning("news for a stock couldn't be fetched: %s", exc)
            continue
        except Exception:
            log.exception("news for a stock couldn't be fetched")
            continue
        async with uow() as tx:
            await tx.investments.save_news(symbol, dedupe(items), dates, at=now)
            await tx.commit()
        done += 1
    return done


async def watchlist(uow: UnitOfWork, user_id: UserId) -> list[str]:
    async with uow:
        return await uow.investments.list_watch(user_id)


async def watch(uow: UnitOfWork, user_id: UserId, symbol: str, *, now: datetime) -> bool:
    """Follow a stock. False if it was already on the list."""
    async with uow:
        watched = await uow.investments.list_watch(user_id)
        if symbol not in watched and len(watched) >= MAX_WATCH:
            raise InvalidInput(f"your watchlist is full ({MAX_WATCH} stocks); remove one first")
        added = await uow.investments.add_watch(user_id, symbol, now)
        if added:
            await queue_refresh(uow, now)
        await uow.commit()
    return added


async def unwatch(uow: UnitOfWork, user_id: UserId, symbol: str) -> None:
    async with uow:
        if not await uow.investments.remove_watch(user_id, symbol):
            raise NotFound(f"{symbol} isn't on your watchlist")
        await uow.commit()


@dataclass(frozen=True, slots=True)
class StockView:
    """Everything known about one stock, for the user who asked."""

    symbol: str
    held: Position | None
    watching: bool
    levels: Levels | None  # None until there's a month of prices
    earnings: EarningsDate | None  # the next one
    news: list[NewsItem]
    # Where the price ends up in a week, a month and three months, from its own
    # volatility; empty until there are a few months of prices.
    ranges: list[Range] = field(default_factory=list)
    moves: list[float] = field(default_factory=list)  # the last year's daily log returns
    # Its last year in numbers (see domain.history); None until a month of prices.
    history: History | None = None


async def stock(uow: UnitOfWork, user: User, symbol: str, *, today: date) -> StockView:
    async with uow:
        held = {h.position.symbol: h.position for h in await uow.investments.list_holdings(user.id)}
        watching = symbol in await uow.investments.list_watch(user.id)
        bars = await uow.investments.bars(symbol, LEVEL_BARS)
        earnings = await uow.investments.upcoming_earnings([symbol], today)
        # Twice as many as shown: the same story fetched on two days has two ids.
        news = await uow.investments.recent_news(symbol, NEWS_SHOWN * 2)
        market = await uow.investments.bars(MARKET, LEVEL_BARS) if symbol != MARKET else bars
        past = await uow.investments.past_earnings(
            symbol, today - timedelta(days=PAST_EARNINGS_DAYS), today
        )
    levels = compute(bars)
    moves = returns(bars)
    return StockView(
        symbol=symbol,
        held=held.get(symbol),
        watching=watching,
        levels=levels,
        earnings=earnings.get(symbol),
        news=dedupe(news)[:NEWS_SHOWN],
        ranges=ranges(levels.close, moves) if levels else [],
        moves=moves,
        history=history(bars, market, past),
    )


async def next_earnings(
    uow: UnitOfWork, symbols: list[str], *, today: date
) -> dict[str, EarningsDate]:
    async with uow:
        return await uow.investments.upcoming_earnings(symbols, today)


@dataclass(frozen=True, slots=True)
class Watched:
    symbol: str
    latest: Bar | None
    previous: Bar | None
    earnings: EarningsDate | None


async def watched(uow: UnitOfWork, user_id: UserId, *, today: date) -> list[Watched]:
    """The user's watchlist with each stock's last two closes and next earnings."""
    async with uow:
        symbols = await uow.investments.list_watch(user_id)
        bars = await uow.investments.latest_bars(symbols)
        earnings = await uow.investments.upcoming_earnings(symbols, today)
    rows = []
    for s in symbols:
        found = bars.get(s, [])
        rows.append(
            Watched(
                s,
                found[0] if found else None,
                found[1] if len(found) > 1 else None,
                earnings.get(s),
            )
        )
    return rows
