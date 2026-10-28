"""Live prices through the web API: the portfolio, watchlist and stock page show a live
price while the market is open, refresh only the requester's own stocks, and fall back
to the stored quote or close when the provider fails. Every ticker and figure here is
made up."""

from datetime import date, timedelta
from typing import Any

import pytest

from nexus.application import market as market_cases
from nexus.application.limits import RateLimiter
from nexus.domain.market import MarketStatus
from tests.fakes import NOW, FakePrices, quote
from tests.integration import test_web_api
from tests.integration.test_web_api import MEMBER, OWNER, Browser, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

# NOW is Monday 28 Sep 2026, midnight in New York; the market is open from 9:30.
OPEN_AT = NOW + timedelta(hours=10, minutes=42)  # 10:42 in New York
QUOTED = OPEN_AT - timedelta(minutes=1)
OPEN = MarketStatus(True, "regular", None, OPEN_AT)
AFTER = NOW + timedelta(hours=16, minutes=30)  # 16:30 in New York
SHUT = MarketStatus(False, "post-market", None, AFTER)
LAST = date(2026, 9, 25)  # the Friday before
CLIMB = {LAST - timedelta(days=59 - i): f"{100 + i * 0.5:.2f}" for i in range(60)}  # to 129.50


async def hold(browser: Browser, symbol: str, quantity: str = "10") -> None:
    edit = {"quantity": quantity, "average_cost": "120.00", "currency": "USD"}
    sent = await browser.send("PUT", f"/api/investments/holdings/{symbol}", edit)
    assert sent.status_code == 204


async def watch(browser: Browser, symbol: str) -> None:
    sent = await browser.send("POST", "/api/investments/watchlist", {"symbol": symbol})
    assert sent.status_code == 200


async def with_prices(world: World, *symbols: str) -> None:
    await market_cases.refresh(
        world.app.state.web.uow, FakePrices({s: CLIMB for s in symbols}), now=NOW
    )


def open_market(world: World, *symbols: str, price: str = "131.50") -> None:
    world.clock.now = OPEN_AT
    world.quotes.status = OPEN
    world.quotes.quotes = {s: quote(s, price, "129.50", QUOTED) for s in symbols}
    world.quotes.asked.clear()


async def test_the_portfolio_the_watchlist_and_a_stock_page_show_the_live_price(
    world: World,
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await hold(owner, "NVDA")
    await watch(owner, "AMD")
    await with_prices(world, "NVDA", "AMD")
    shut = (await owner.get("/api/investments")).json()
    assert shut["holdings"][0]["price_kind"] == "close" and shut["holdings"][0]["price_at"] is None
    assert shut["totals"]["price_kind"] == "close" and shut["totals"]["as_of_at"] is None
    assert world.quotes.asked == []  # the market is shut: nothing asked

    open_market(world, "NVDA", "AMD", "ZZZ")
    page = (await owner.get("/api/investments")).json()
    nvda = page["holdings"][0]
    assert nvda["price"]["amount"] == "131.5000" and nvda["price_kind"] == "live"
    assert nvda["price_day"] == "2026-09-28" and nvda["price_at"].startswith("2026-09-28T14:41:00")
    assert nvda["day_percent"] == "1.54"  # against the quote's own previous close
    totals = page["totals"]
    assert totals["price_kind"] == "live" and totals["as_of"] == "2026-09-28"
    assert totals["as_of_at"].startswith("2026-09-28T14:41:00")
    assert world.quotes.asked == ["NVDA"]  # only the holdings, not the watched AMD

    stocks = (await owner.get("/api/investments/watchlist")).json()["stocks"]
    assert [(s["symbol"], s["price"], s["price_kind"], s["day_percent"]) for s in stocks] == [
        ("AMD", "131.50", "live", "1.54")
    ]
    assert stocks[0]["price_at"].startswith("2026-09-28T14:41:00")
    assert world.quotes.asked == ["NVDA", "AMD"]

    # Quotes under 6 minutes old (the job keeps them within that) are not fetched again.
    await owner.get("/api/investments")
    await owner.get("/api/investments/watchlist")
    assert world.quotes.asked == ["NVDA", "AMD"]

    amd = (await owner.get("/api/investments/stocks/amd")).json()
    assert (
        amd["price"] == "131.50"
        and amd["price_kind"] == "live"
        and amd["price_day"] == ("2026-09-28")
    )
    assert amd["levels"]["close"] == "129.50"  # levels stay on the closes
    assert amd["now_vs_levels"] and "50-day average" in " ".join(amd["now_vs_levels"])
    assert world.quotes.asked == ["NVDA", "AMD"]

    # A minute and a bit on, the stored quote is still shown; past 6 minutes it is asked
    # again, and a price may have moved.
    world.quotes.quotes["NVDA"] = quote("NVDA", "132", "129.50", QUOTED + timedelta(seconds=70))
    world.clock.now = OPEN_AT + timedelta(seconds=75)
    still = (await owner.get("/api/investments")).json()["holdings"][0]
    assert still["price"]["amount"] == "131.5000"
    assert world.quotes.asked == ["NVDA", "AMD"]
    world.clock.now = OPEN_AT + timedelta(minutes=6, seconds=15)
    again = (await owner.get("/api/investments")).json()["holdings"][0]
    assert again["price"]["amount"] == "132.0000"

    # After the close, the last quote is a provisional close; nothing is asked.
    world.clock.now = AFTER
    world.quotes.status = SHUT
    world.quotes.asked.clear()
    evening = (await owner.get("/api/investments")).json()
    assert evening["holdings"][0]["price_kind"] == "provisional_close"
    assert evening["totals"]["price_kind"] == "provisional_close"
    assert world.quotes.asked == []


async def test_a_provider_that_is_down_changes_nothing_for_the_page(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await hold(owner, "NVDA")
    await with_prices(world, "NVDA")
    open_market(world, "NVDA")
    world.quotes.failing = {"NVDA"}
    page = await owner.get("/api/investments")
    assert page.status_code == 200
    assert page.json()["holdings"][0]["price_kind"] == "close"
    assert world.quotes.asked == ["NVDA"]
    # The status call failing too: the usual hours say it is open, and the page still loads.
    world.clock.now = OPEN_AT + timedelta(minutes=10)
    world.quotes.status = None
    again = await owner.get("/api/investments")
    assert again.status_code == 200 and again.json()["holdings"][0]["price_kind"] == "close"
    assert world.quotes.asked == ["NVDA", "NVDA"]


async def seen_by_two(world: World) -> tuple[Browser, Browser]:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite)).status_code == 200
    await hold(owner, "NVDA")
    await watch(owner, "AMD")
    await hold(member, "TSLA")
    await watch(member, "PLTR")
    return owner, member


async def test_a_request_never_fetches_another_users_symbols(world: World) -> None:
    owner, member = await seen_by_two(world)
    open_market(world, "NVDA", "AMD", "TSLA", "PLTR", "ZZZ")
    quotes = world.quotes

    await owner.get("/api/investments")
    assert quotes.asked == ["NVDA"]
    await owner.get("/api/investments/watchlist")
    assert quotes.asked == ["NVDA", "AMD"]
    quotes.asked.clear()
    await member.get("/api/investments")
    await member.get("/api/investments/watchlist")
    assert quotes.asked == ["TSLA", "PLTR"]
    quotes.asked.clear()

    # A stock page asks about its own stock, and that alone, held by anyone or not.
    world.clock.now = OPEN_AT + timedelta(minutes=10)
    await owner.get("/api/investments/stocks/tsla")
    assert quotes.asked == ["TSLA"]
    quotes.asked.clear()
    await owner.get("/api/investments/stocks/zzz")
    assert quotes.asked == ["ZZZ"]
    # The quote for TSLA is shared market data; the member's holding is not.
    owner_page = (await owner.get("/api/investments")).json()
    assert [h["symbol"] for h in owner_page["holdings"]] == ["NVDA"]
    assert set(quotes.asked) <= {"NVDA", "AMD", "TSLA", "ZZZ"} and "PLTR" not in quotes.asked


async def test_a_stock_pages_symbol_is_checked_before_anything_is_asked(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    open_market(world, "NVDA")
    for bad in ("NOT A TICKER", "AB%24CD", "THISISFAR2LONGATICKER", "..%2F..%2Fx"):
        got = await owner.get(f"/api/investments/stocks/{bad}")
        assert got.status_code in (404, 422), bad
    assert world.quotes.asked == []


async def test_a_member_cannot_use_up_the_providers_allowance_with_stock_pages(
    world: World,
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    open_market(world)
    web: Any = world.app.state.web
    object.__setattr__(web, "limits", RateLimiter({"quote": ((2, timedelta(minutes=5)),)}))
    for symbol in ("AAA", "BBB", "CCC", "DDD"):
        got = await owner.get(f"/api/investments/stocks/{symbol}")
        assert got.status_code == 200  # the page still loads
    assert world.quotes.asked == ["AAA", "BBB"]
