"""Live prices: the job that fetches quotes while the US market is open, the refresh a
page does for its user's own stocks, and what holdings, watchlists and stock pages are
worth at them. Every ticker and figure here is made up. October 2026 is still daylight
time in New York (UTC-4)."""

import asyncio
import logging
import types
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import investments as investment_cases
from nexus.application import market as market_cases
from nexus.application import quotes as quote_cases
from nexus.application import research as research_cases
from nexus.application.quotes import Quotes
from nexus.domain.investments import Position
from nexus.domain.ledger import User
from nexus.domain.market import MarketStatus, PriceKind, Quote
from nexus.domain.money import Money
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import jobs
from nexus.jobs.handlers import SCHEDULES, build_handlers
from nexus.jobs.runner import JobRunner, Schedule
from tests.fakes import FakePrices, FakeQuotes, FakeRates, FakeTelegram, quote
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

NEW_YORK = ZoneInfo("America/New_York")


def ny(text: str) -> datetime:
    """A New York wall-clock time such as "2026-10-19 10:42", as an instant."""
    return datetime.fromisoformat(text).replace(tzinfo=NEW_YORK)


MON_OPEN = ny("2026-10-19 10:42")  # a Monday, mid-morning
OPEN = MarketStatus(True, "regular", None, MON_OPEN)
CLOSED = MarketStatus(False, "post-market", None, MON_OPEN)


def usd(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


async def hold(uow: UowFactory, user: User, symbol: str, quantity: str = "10") -> None:
    position = Position(symbol, Decimal(quantity), usd("90"))
    await investment_cases.set_position(uow(), user.id, position, now=MON_OPEN)


async def stored(uow: UowFactory, *symbols: str) -> dict[str, Decimal]:
    async with uow() as tx:
        return {s: q.price for s, q in (await tx.investments.quotes(list(symbols))).items()}


async def keep(uow: UowFactory, quotes: list[Quote], *, at: datetime) -> None:
    async with uow() as tx:
        await tx.investments.upsert_quotes(quotes, at=at)
        await tx.commit()


async def fetched(uow: UowFactory, *symbols: str) -> dict[str, datetime]:
    async with uow() as tx:
        return await tx.investments.quotes_fetched(list(symbols))


def live(*symbols: str, price: str = "103") -> dict[str, Quote]:
    return {s: quote(s, price, "100", MON_OPEN - timedelta(minutes=1)) for s in symbols}


# --- the job ------------------------------------------------------------------------------


async def test_the_job_fetches_held_and_watched_stocks_and_the_market(uow: UowFactory) -> None:
    first, second = await person(uow), await person(uow, 4343)
    await hold(uow, first, "NVDA")
    await hold(uow, second, "NVDA")  # held twice, fetched once
    await research_cases.watch(uow(), second.id, "AMD", now=MON_OPEN)
    fake = FakeQuotes(live("NVDA", "AMD", "SPY", "TSLA"), status=OPEN)
    got = await quote_cases.refresh(uow, Quotes(fake), now=MON_OPEN)
    # Held and watched, and SPY for the market; nobody tracks TSLA.
    assert got == 3 and sorted(fake.asked) == ["AMD", "NVDA", "SPY"]
    assert await stored(uow, "NVDA", "AMD", "SPY", "TSLA") == {
        "NVDA": Decimal("103"),
        "AMD": Decimal("103"),
        "SPY": Decimal("103"),
    }
    assert set((await fetched(uow, "NVDA", "AMD", "SPY")).values()) == {MON_OPEN}


async def test_quotes_stamped_outside_regular_hours_are_counted_in_the_log(
    uow: UowFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    await hold(uow, user, "AMD")
    stamped = {
        "NVDA": quote("NVDA", "103", "100", ny("2026-10-19 10:41")),  # in the session
        "AMD": quote("AMD", "109", "100", ny("2026-10-19 07:30")),  # before the open
        "SPY": quote("SPY", "103", "100", ny("2026-10-18 19:42")),  # after hours
    }
    caplog.set_level(logging.INFO, logger="nexus.application.quotes")
    fake = FakeQuotes(stamped, status=OPEN)
    assert await quote_cases.refresh(uow, Quotes(fake), now=MON_OPEN) == 3
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("quotes:")]
    assert line == "quotes: 2 of 3 stamped outside regular hours (latest 07:30 ET)"
    # A page's refresh stores through the same step; closing prints are regular.
    caplog.clear()
    page = FakeQuotes({"NVDA": quote("NVDA", "104", "100", ny("2026-10-19 10:42"))}, status=OPEN)
    await quote_cases.refresh_own(uow, Quotes(page), user.id, now=MON_OPEN, held=True)
    assert not [r for r in caplog.records if r.getMessage().startswith("quotes:")]
    late = FakeQuotes({"NVDA": quote("NVDA", "104", "100", ny("2026-10-19 19:42"))}, status=OPEN)
    await quote_cases.refresh_own(
        uow, Quotes(late), user.id, now=MON_OPEN + timedelta(minutes=5), held=True
    )
    [page_line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("quotes:")]
    assert page_line == "quotes: 1 of 1 stamped outside regular hours (latest 19:42 ET)"


async def test_a_stock_the_provider_doesnt_list_is_not_asked_about(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    await hold(uow, user, "ZZZZ")
    # Prices have been tried for both; the provider knows only NVDA.
    bars = {date(2026, 10, 16): "100"}
    await market_cases.refresh(uow, FakePrices({"NVDA": bars, "SPY": bars}), now=MON_OPEN)
    fake = FakeQuotes(live("NVDA", "SPY"), status=OPEN)
    await quote_cases.refresh(uow, Quotes(fake), now=MON_OPEN)
    assert sorted(fake.asked) == ["NVDA", "SPY"]


async def test_the_job_does_nothing_while_the_market_is_shut(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    for when, status in [
        ("2026-10-19 08:00", MarketStatus(False, "pre-market", None, MON_OPEN)),
        ("2026-10-19 17:00", CLOSED),
        ("2026-10-17 11:00", MarketStatus(False, None, None, MON_OPEN)),  # a Saturday
        ("2026-10-19 10:42", MarketStatus(False, None, "Made-up Day", MON_OPEN)),  # a holiday
    ]:
        fake = FakeQuotes(live("NVDA", "SPY"), status=status)
        assert await quote_cases.refresh(uow, Quotes(fake), now=ny(when)) == 0, when
        assert fake.asked == [], when
    assert await stored(uow, "NVDA") == {}


async def test_the_usual_hours_stand_in_when_the_status_cant_be_fetched(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    fake = FakeQuotes(live("NVDA", "SPY"), status=None)  # the status call fails
    assert await quote_cases.refresh(uow, Quotes(fake), now=MON_OPEN) == 2
    shut = FakeQuotes(live("NVDA"), status=None)
    assert await quote_cases.refresh(uow, Quotes(shut), now=ny("2026-10-17 11:00")) == 0
    assert await quote_cases.refresh(uow, Quotes(shut), now=ny("2026-10-19 07:00")) == 0
    assert shut.asked == []


async def test_the_closing_price_is_fetched_once_just_after_the_close(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    fake = FakeQuotes(live("NVDA", "SPY"), status=OPEN)
    await quote_cases.refresh(uow, Quotes(fake), now=ny("2026-10-19 15:55"))
    assert sorted(fake.asked) == ["NVDA", "SPY"]
    fake.asked.clear()
    fake.status = CLOSED
    after = Quotes(fake)
    # Within 20 minutes of the close: whatever was fetched before the close is fetched again...
    assert await quote_cases.refresh(uow, after, now=ny("2026-10-19 16:02")) == 2
    assert sorted(fake.asked) == ["NVDA", "SPY"]
    fake.asked.clear()
    # ...once. Nor later, when the day is over.
    assert await quote_cases.refresh(uow, after, now=ny("2026-10-19 16:07")) == 0
    assert await quote_cases.refresh(uow, after, now=ny("2026-10-19 16:25")) == 0
    assert fake.asked == []


async def test_a_run_is_capped_and_takes_the_oldest_first(uow: UowFactory) -> None:
    user = await person(uow)
    for i in range(15):
        await hold(uow, user, f"H{i:02d}")
    for i in range(research_cases.MAX_WATCH):
        await research_cases.watch(uow(), user.id, f"W{i:02d}", now=MON_OPEN)
    names = [f"H{i:02d}" for i in range(15)] + [f"W{i:02d}" for i in range(50)]  # 65 and SPY
    fake = FakeQuotes(live(*names, "SPY"), status=OPEN)
    quotes = Quotes(fake)
    assert await quote_cases.refresh(uow, quotes, now=MON_OPEN) == 50
    assert len(set(fake.asked)) == 50
    # The next run, a few minutes on, starts with those never fetched (16 of them), then
    # the oldest of the rest.
    first = set(fake.asked)
    fake.asked.clear()
    later = MON_OPEN + timedelta(minutes=5)
    assert await quote_cases.refresh(uow, quotes, now=later) == 50
    assert set(fake.asked) >= {n for n in [*names, "SPY"] if n not in first}
    assert len(set(fake.asked) & first) == 50 - 16


async def test_a_429_stops_the_run_and_keeps_what_it_got(uow: UowFactory) -> None:
    user = await person(uow)
    for symbol in ("AAA", "BBB", "CCC", "DDD"):
        await hold(uow, user, symbol)
    fake = FakeQuotes(live("AAA", "BBB", "CCC", "DDD", "SPY"), status=OPEN, limit_after=2)
    assert await quote_cases.refresh(uow, Quotes(fake), now=MON_OPEN) == 2
    assert len(fake.asked) == 3  # the third was refused, and nothing was asked after it
    assert len(await stored(uow, "AAA", "BBB", "CCC", "DDD", "SPY")) == 2


async def test_one_stock_failing_doesnt_stop_the_others(uow: UowFactory) -> None:
    user = await person(uow)
    for symbol in ("AAA", "BBB"):
        await hold(uow, user, symbol)
    fake = FakeQuotes(live("AAA", "BBB", "SPY"), status=OPEN, failing={"AAA"})
    assert await quote_cases.refresh(uow, Quotes(fake), now=MON_OPEN) == 2
    assert sorted(await stored(uow, "AAA", "BBB", "SPY")) == ["BBB", "SPY"]


async def test_a_run_stops_starting_fetches_after_its_budget(
    uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await person(uow)
    for i in range(6):
        await hold(uow, user, f"S{i}")
    clock = {"now": 0.0}
    monkeypatch.setattr(quote_cases, "time", types.SimpleNamespace(monotonic=lambda: clock["now"]))

    def slow(_: str) -> None:
        clock["now"] += 15.0  # each call takes 15 s

    fake = FakeQuotes(live(*[f"S{i}" for i in range(6)], "SPY"), status=OPEN, on_quote=slow)
    assert await quote_cases.refresh(uow, Quotes(fake), now=MON_OPEN) == 3  # 0, 15, 30 s; not 45
    assert len(await stored(uow, *[f"S{i}" for i in range(6)], "SPY")) == 3


async def test_the_market_status_is_remembered_for_a_few_minutes(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    fake = FakeQuotes(live("NVDA", "SPY"), status=OPEN)
    quotes = Quotes(fake)
    await quote_cases.refresh(uow, quotes, now=MON_OPEN)
    await quote_cases.refresh(uow, quotes, now=MON_OPEN + timedelta(minutes=3))
    assert fake.status_asked == 1
    # A run a slot later asks again (it never reuses the last run's answer)...
    await quote_cases.refresh(uow, quotes, now=MON_OPEN + timedelta(minutes=5))
    assert fake.status_asked == 2
    # ...while a page, which can live with older, reuses it for up to five minutes.
    assert await quotes.status(MON_OPEN + timedelta(minutes=9)) == OPEN
    assert fake.status_asked == 2
    await quotes.status(MON_OPEN + timedelta(minutes=11))
    assert fake.status_asked == 3


async def test_the_job_is_scheduled_every_five_minutes_and_runs_from_the_runner(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    assert Schedule(quote_cases.REFRESH_JOB, timedelta(minutes=5)) in SCHEDULES
    user = await person(uow)
    await hold(uow, user, "NVDA")
    fake = FakeQuotes(live("NVDA", "SPY"), status=OPEN)
    now = [MON_OPEN.astimezone(UTC)]
    handlers = build_handlers(uow, FakeTelegram(), FakeRates(), lambda: now[0], quotes=Quotes(fake))
    runner = JobRunner(
        engine,
        {quote_cases.REFRESH_JOB: handlers[quote_cases.REFRESH_JOB]},
        schedules=[Schedule(quote_cases.REFRESH_JOB, timedelta(minutes=5))],
        clock=lambda: now[0],
    )
    await runner.tick()
    now[0] += timedelta(minutes=5)
    await runner.tick()
    async with engine.connect() as db:
        keys = [r.dedupe_key for r in await db.execute(select(jobs.c.dedupe_key))]
    assert len([k for k in keys if str(k).startswith("quotes.refresh@")]) == 2
    assert fake.asked.count("NVDA") == 2


async def test_without_a_key_the_job_does_nothing(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    handlers = build_handlers(uow, FakeTelegram(), FakeRates(), lambda: MON_OPEN)
    await handlers[quote_cases.REFRESH_JOB]({})
    assert await stored(uow, "NVDA") == {}


# --- a page refreshing its user's own stocks ----------------------------------------------


async def test_a_page_refreshes_only_its_users_own_stale_stocks(uow: UowFactory) -> None:
    mine, theirs = await person(uow), await person(uow, 4343)
    await hold(uow, mine, "NVDA")
    await hold(uow, mine, "AAPL")
    await research_cases.watch(uow(), mine.id, "AMD", now=MON_OPEN)
    await hold(uow, theirs, "TSLA")
    await research_cases.watch(uow(), theirs.id, "PLTR", now=MON_OPEN)
    fake = FakeQuotes(live("NVDA", "AAPL", "AMD", "TSLA", "PLTR"), status=OPEN)
    quotes = Quotes(fake)

    async def refresh(**scope: Any) -> MarketStatus | None:
        return await quote_cases.refresh_own(uow, quotes, mine.id, now=MON_OPEN, **scope)

    assert await refresh(held=True) == OPEN
    assert sorted(fake.asked) == ["AAPL", "NVDA"]  # not AMD (watched), not theirs
    fake.asked.clear()
    # Fresh (a minute or less old): not asked again. A stale one is.
    await refresh(held=True)
    assert fake.asked == []
    later = MON_OPEN + timedelta(seconds=61)
    await quote_cases.refresh_own(uow, quotes, mine.id, now=later, held=True, watched=True)
    assert sorted(fake.asked) == ["AAPL", "AMD", "NVDA"]
    fake.asked.clear()
    # The one stock a stock page is about, whoever holds it; nothing for another's.
    await quote_cases.refresh_own(uow, quotes, mine.id, now=later, symbol="tsla")
    assert fake.asked == ["TSLA"]
    assert await stored(uow, "PLTR", "TSLA") == {"TSLA": Decimal("103")}


async def test_a_page_asks_about_at_most_fifteen_stocks_oldest_first(uow: UowFactory) -> None:
    user = await person(uow)
    names = [f"N{i:02d}" for i in range(20)]
    for name in names:
        await hold(uow, user, name)
    fake = FakeQuotes(live(*names), status=OPEN)
    quotes = Quotes(fake)
    await quote_cases.refresh_own(uow, quotes, user.id, now=MON_OPEN, held=True)
    assert len(fake.asked) == 15
    first = set(fake.asked)
    fake.asked.clear()
    # The five not yet fetched go first the next time.
    later = MON_OPEN + timedelta(seconds=90)
    await quote_cases.refresh_own(uow, quotes, user.id, now=later, held=True)
    assert len(fake.asked) == 15 and set(names) - first <= set(fake.asked)


async def test_a_page_asks_nothing_while_the_market_is_shut_or_without_a_key(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    fake = FakeQuotes(live("NVDA"), status=CLOSED)
    got = await quote_cases.refresh_own(
        uow, Quotes(fake), user.id, now=ny("2026-10-19 17:00"), held=True
    )
    assert got == CLOSED and fake.asked == []
    assert await quote_cases.refresh_own(uow, None, user.id, now=MON_OPEN, held=True) is None


async def test_a_page_ignores_failures_and_bad_symbols(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    await hold(uow, user, "AMD")
    fake = FakeQuotes(live("NVDA", "AMD"), status=OPEN, failing={"NVDA"})
    got = await quote_cases.refresh_own(uow, Quotes(fake), user.id, now=MON_OPEN, held=True)
    assert got == OPEN and sorted(await stored(uow, "NVDA", "AMD")) == ["AMD"]
    # The provider being down altogether changes nothing for the user.
    down = FakeQuotes(status=None, failing={"NVDA", "AMD"})
    assert (
        await quote_cases.refresh_own(uow, Quotes(down), user.id, now=MON_OPEN, held=True) is None
    )
    # A symbol that isn't a ticker is never sent anywhere.
    odd = FakeQuotes(live("NVDA"), status=OPEN)
    await quote_cases.refresh_own(uow, Quotes(odd), user.id, now=MON_OPEN, symbol="NOT A TICKER")
    await quote_cases.refresh_own(uow, Quotes(odd), user.id, now=MON_OPEN, symbol="../etc")
    assert odd.asked == []


async def test_a_page_gives_up_after_its_budget_but_keeps_what_arrived(
    uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await person(uow)
    await hold(uow, user, "FAST")
    await hold(uow, user, "SLOW")
    monkeypatch.setattr(quote_cases, "REQUEST_BUDGET_SECONDS", 0.2)

    async def sometimes_slow(symbol: str) -> None:
        if symbol == "SLOW":
            await asyncio.sleep(5)

    fake = FakeQuotes(live("FAST", "SLOW"), status=OPEN, on_quote=sometimes_slow)
    got = await quote_cases.refresh_own(uow, Quotes(fake), user.id, now=MON_OPEN, held=True)
    assert got == OPEN
    assert sorted(await stored(uow, "FAST", "SLOW")) == ["FAST"]


# --- what holdings and stocks are worth at them -------------------------------------------

CLOSES = {date(2026, 10, 15): "98", date(2026, 10, 16): "100"}  # Thursday and Friday
RATES = {("USD", "SGD"): {date(2026, 10, 16): "1.30", date(2026, 10, 19): "1.40"}}


async def valued_user(uow: UowFactory) -> User:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    await hold(uow, user, "AAPL")
    await market_cases.refresh(
        uow, FakePrices({"NVDA": CLOSES, "AAPL": CLOSES}), now=ny("2026-10-19 07:00")
    )
    return user


async def test_holdings_are_worth_the_live_price_while_the_market_is_open(uow: UowFactory) -> None:
    user = await valued_user(uow)
    await keep(uow, [quote("NVDA", "104", "100", ny("2026-10-19 10:41"))], at=MON_OPEN)
    v = await investment_cases.valuation(uow(), FakeRates(RATES), user, now=MON_OPEN, status=OPEN)
    nvda = next(r for r in v.rows if r.holding.position.symbol == "NVDA").valued
    aapl = next(r for r in v.rows if r.holding.position.symbol == "AAPL").valued
    assert nvda is not None and aapl is not None
    assert (nvda.price, nvda.price_kind, nvda.price_at) == (
        usd("104"),
        PriceKind.LIVE,
        ny("2026-10-19 10:41"),
    )
    assert nvda.price_day == date(2026, 10, 19)
    # The day's change is against the quote's own previous close.
    assert nvda.day_change == usd("40.00") and nvda.day_percent == Decimal("4.00")
    # AAPL has no quote: its close, as before.
    assert (aapl.price, aapl.price_kind, aapl.price_at) == (usd("100"), PriceKind.CLOSE, None)
    # The rate is the quote's day's (Monday's 1.40), as for any price that day.
    assert next(r for r in v.rows if r.holding.position.symbol == "NVDA").value_home == Money(
        Decimal("1456.00"), "SGD"
    )
    assert v.as_of == date(2026, 10, 19) and v.as_of_at == ny("2026-10-19 10:41")
    assert v.price_kind is PriceKind.LIVE
    text = investment_cases.describe_valuation(v, ZoneInfo("Asia/Singapore"))
    assert "104.00 USD at 10:41pm (live), worth 1040.00 USD" in text
    assert "100.00 USD at the close on Fri 16 Oct" in text


async def test_after_the_close_the_last_price_is_provisional_until_the_bar_arrives(
    uow: UowFactory,
) -> None:
    user = await valued_user(uow)
    await keep(
        uow, [quote("NVDA", "105", "100", ny("2026-10-19 16:00"))], at=ny("2026-10-19 16:01")
    )
    evening = ny("2026-10-19 17:00")
    v = await investment_cases.valuation(uow(), FakeRates(RATES), user, now=evening, status=CLOSED)
    assert v.price_kind is PriceKind.PROVISIONAL_CLOSE and v.as_of_at == ny("2026-10-19 16:00")
    assert "at the close (provisional)" in investment_cases.describe_valuation(v, ZoneInfo("UTC"))
    # Tiingo's Monday bar arrives (and is a little different): it replaces the quote.
    closes = {**CLOSES, date(2026, 10, 19): "104.9"}
    await market_cases.refresh(
        uow, FakePrices({"NVDA": closes, "AAPL": CLOSES}), now=ny("2026-10-19 18:30")
    )
    official = await investment_cases.valuation(
        uow(), FakeRates(RATES), user, now=ny("2026-10-19 18:31"), status=CLOSED
    )
    nvda = next(r for r in official.rows if r.holding.position.symbol == "NVDA").valued
    assert nvda is not None and nvda.price == usd("104.9") and nvda.price_kind is PriceKind.CLOSE
    assert official.price_kind is PriceKind.CLOSE and official.as_of_at is None


async def test_the_watchlist_and_a_stock_page_use_the_same_price(uow: UowFactory) -> None:
    user = await person(uow)
    await research_cases.watch(uow(), user.id, "AMD", now=MON_OPEN)
    closes = {
        date(2026, 10, 16) - timedelta(days=59 - i): f"{100 + i * 0.5:.2f}" for i in range(60)
    }
    await market_cases.refresh(uow, FakePrices({"AMD": closes}), now=ny("2026-10-19 07:00"))
    await keep(uow, [quote("AMD", "131.75", "129.50", ny("2026-10-19 10:41"))], at=MON_OPEN)
    rows = await research_cases.watched(
        uow(), user.id, today=date(2026, 10, 19), now=MON_OPEN, status=OPEN
    )
    price = rows[0].price
    assert price is not None and price.kind is PriceKind.LIVE and price.price == Decimal("131.75")
    assert price.previous == Decimal("129.50")
    view = await research_cases.stock(
        uow(), user, "AMD", today=date(2026, 10, 19), now=MON_OPEN, status=OPEN
    )
    assert view.price == price
    assert view.levels is not None and view.levels.close == Decimal("129.50")
    assert view.now_vs_levels  # against the 50-day average at least
    assert any("50-day average" in line for line in view.now_vs_levels)
    # Closed: the same page shows the close.
    shut = await research_cases.stock(
        uow(), user, "AMD", today=date(2026, 10, 19), now=ny("2026-10-19 07:00"), status=None
    )
    assert shut.price is not None and shut.price.kind is PriceKind.CLOSE
    assert shut.price.price == Decimal("129.50")


# --- in chat ------------------------------------------------------------------------------


async def test_chat_says_when_each_price_is_from(uow: UowFactory) -> None:
    user = await valued_user(uow)
    await research_cases.watch(uow(), user.id, "AMD", now=MON_OPEN)
    await keep(
        uow,
        [
            quote("NVDA", "104", "100", ny("2026-10-19 10:41")),
            quote("AMD", "131.75", "129.50", ny("2026-10-19 10:41")),
        ],
        at=MON_OPEN,
    )
    tools = build_tools(lambda _: "")
    rates = FakeRates(RATES)

    async def say(name: str, now: datetime, args: dict[str, Any] | None = None) -> str:
        ctx = ToolContext(user, uow, now, rates)
        return (await run_tool(tools[name], ctx, args or {})).text

    # 10:42am in New York is 10:42pm in Singapore, where this user lives.
    text = await say("show_portfolio", MON_OPEN)
    assert "104.00 USD at 10:41pm (live)" in text
    assert "latest price" in text and "not live prices" not in text
    watching = await say("show_watchlist", MON_OPEN)
    assert "AMD: 131.75 at 10:41pm (live)" in watching
    stock = await say("stock_levels", MON_OPEN, {"symbol": "AMD"})
    assert "Price 131.75 at 10:41pm (live)" in stock
    # After the close the day's last quote reads as a provisional close, and a stock
    # with no quote still has its close.
    evening = await say("show_portfolio", ny("2026-10-19 21:00"))
    assert "104.00 USD at the close (provisional)" in evening
    assert "100.00 USD at the close on Fri 16 Oct" in evening


# --- the migration ------------------------------------------------------------------------


async def test_migration_0049_goes_down_and_up_again(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    await keep(uow, [quote("NVDA", "104", "100", MON_OPEN)], at=MON_OPEN)
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0048")
    async with engine.connect() as db:
        tables: set[str] = set(
            (await db.execute(text("SELECT tablename FROM pg_tables"))).scalars()
        )
    assert "market_quotes" not in tables
    await upgrade(empty_database_url)
    async with engine.connect() as db:
        assert (await db.execute(text("SELECT count(*) FROM market_quotes"))).scalar_one() == 0
