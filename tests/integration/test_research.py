"""The watchlist, news and earnings dates, and one stock's levels. Every ticker,
price and headline here is made up."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from nexus.application import market as market_cases
from nexus.application import research as research_cases
from nexus.domain.errors import InvalidInput, NotFound
from tests.fakes import NOW, FakeNews, FakePrices, call, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_email import person
from tests.integration.test_investments import trade

pytestmark = pytest.mark.integration


def history(days: int, start: float = 100.0) -> dict[date, str]:
    """A steady climb, one close a day, ending the Friday before NOW."""
    last = date(2026, 9, 25)
    return {last - timedelta(days=days - 1 - i): f"{start + i * 0.5:.2f}" for i in range(days)}


async def test_the_watchlist(uow: UowFactory) -> None:
    user = await person(uow)
    assert await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    assert not await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    assert await research_cases.watchlist(uow(), user.id) == ["AMD"]
    await research_cases.unwatch(uow(), user.id, "AMD")
    with pytest.raises(NotFound):
        await research_cases.unwatch(uow(), user.id, "AMD")
    for i in range(research_cases.MAX_WATCH):
        await research_cases.watch(uow(), user.id, f"W{i}", now=NOW)
    with pytest.raises(InvalidInput, match="full"):
        await research_cases.watch(uow(), user.id, "ONEMORE", now=NOW)


async def test_watched_stocks_get_prices_news_and_levels(uow: UowFactory) -> None:
    user = await person(uow)
    await trade(uow, user.id, "buy", "NVDA", "10", "118.40")
    await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    prices = FakePrices({"AMD": history(60), "NVDA": history(5)})
    assert await market_cases.refresh(uow, prices, now=NOW) == 2
    news = FakeNews(
        headlines={
            "AMD": [
                (NOW - timedelta(days=1), "Acme rival opens a plant"),
                (NOW - timedelta(days=1, hours=2), "ACME rival opens a plant!"),
                (NOW - timedelta(days=20), "Too old to fetch"),
            ]
        },
        earnings_days={"AMD": [date(2026, 10, 29), date(2027, 3, 1)]},
        failing={"NVDA"},
    )
    assert await research_cases.refresh_news(uow, news, now=NOW) == 1  # NVDA's provider fails
    # Fetched lately: not again for six hours; the failure is retried.
    news.asked.clear()
    await research_cases.refresh_news(uow, news, now=NOW + timedelta(hours=1))
    assert news.asked == ["NVDA"]

    view = await research_cases.stock(uow(), user, "AMD", today=NOW.date())
    assert view.watching and view.held is None
    assert view.levels is not None and view.levels.close == Decimal("129.50")
    assert view.levels.averages[20] == Decimal("124.75")
    assert view.levels.averages[50] == Decimal("117.25")
    assert view.earnings is not None and view.earnings.day == date(2026, 10, 29)
    assert [n.headline for n in view.news] == ["ACME rival opens a plant!"]  # once, earliest
    held = await research_cases.stock(uow(), user, "NVDA", today=NOW.date())
    assert held.held is not None and held.levels is None  # five days isn't enough
    rows = await research_cases.watched(uow(), user.id, today=NOW.date())
    assert [(r.symbol, r.latest.close if r.latest else None) for r in rows] == [
        ("AMD", Decimal("129.50"))
    ]
    # News a month old is dropped.
    await research_cases.refresh_news(uow, FakeNews(), now=NOW + timedelta(days=31))
    async with uow() as tx:
        assert await tx.investments.recent_news("AMD", 10) == []


async def test_levels_and_watching_in_chat(uow: UowFactory) -> None:
    user = await person(uow)
    await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    await market_cases.refresh(uow, FakePrices({"AMD": history(60)}), now=NOW)
    model = scripted(
        call("stock_levels", symbol="amd"),
        AIMessage(content="AMD closed at 129.50."),
        call("watch_stock", symbol="tsla"),
        AIMessage(content="Watching TSLA."),
    )
    agent = build(uow, model)
    reply = only(await agent.handle_text(user.id, "levels for AMD", "m1"))
    assert reply.text == "AMD closed at 129.50."
    tool_output = str(model.seen[-1][-1].content)
    assert tool_output.startswith("AMD (USD, daily closes; levels worked out in code")
    assert "On the user's watchlist." in tool_output
    assert "Moving averages: 20-day 124.75, 50-day 117.25" in tool_output
    assert "Likely closes" not in tool_output  # under three months of moves: no ranges
    ask = only(await agent.handle_text(user.id, "watch TSLA", "m2"))
    assert ask.text == "Add TSLA to your watchlist?"
    done = only(await agent.resolve(user.id, ask.buttons[0][0].data.split(":")[1], True))
    assert "Watching TSLA" in done.text
    assert await research_cases.watchlist(uow(), user.id) == ["AMD", "TSLA"]


async def test_likely_ranges_in_chat(uow: UowFactory) -> None:
    user = await person(uow)
    await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    await market_cases.refresh(uow, FakePrices({"AMD": history(90)}), now=NOW)
    model = scripted(call("stock_levels", symbol="amd"), AIMessage(content="About that."))
    only(await build(uow, model).handle_text(user.id, "where could AMD be in a month?", "m1"))
    tool_output = str(model.seen[-1][-1].content)
    assert "Likely closes from its own past volatility (not a forecast" in tool_output
    assert "\nIn 1 month: " in tool_output and "two times in three" in tool_output
