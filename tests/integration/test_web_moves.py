"""What moved today and why, and the market alert settings, through the web API. Every
ticker, price and headline here is made up."""

from datetime import timedelta
from typing import Any

import pytest

from nexus.application import research as research_cases
from nexus.application.limits import RateLimiter
from tests.fakes import NOW, FakeNews, say
from tests.integration import test_web_api
from tests.integration.test_web_api import MEMBER, OWNER, World, owner_and_invite
from tests.integration.test_web_quotes import (
    AFTER,
    OPEN_AT,
    SHUT,
    hold,
    open_market,
    watch,
    with_prices,
)

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

TEN_AM = NOW + timedelta(hours=10)  # 10:00 in New York, after the 9:30 open
EIGHT_AM = NOW + timedelta(hours=8)  # before it


async def news(world: World, **found: list[Any]) -> None:
    web: Any = world.app.state.web
    await research_cases.refresh_news(web.uow, FakeNews(headlines=found), now=OPEN_AT)


async def ready(world: World) -> Any:
    owner = world.browser()
    await owner.login(OWNER)
    await hold(owner, "NVDA")
    await watch(owner, "AMD")
    await with_prices(world, "NVDA", "AMD")
    open_market(world, "NVDA", "AMD")
    await news(
        world,
        NVDA=[(EIGHT_AM, "Before the open"), (TEN_AM, "Nvidia wins a big order")],
    )
    return owner


# --- today --------------------------------------------------------------------------------


async def test_today_needs_a_signed_in_user(world: World) -> None:
    anonymous = world.browser()
    assert (await anonymous.get("/api/investments/today")).status_code == 401
    assert (await anonymous.send("POST", "/api/investments/today/NVDA/why")).status_code == 401


async def test_today_gives_the_change_and_the_movers_with_a_headline(world: World) -> None:
    owner = await ready(world)
    got = (await owner.get("/api/investments/today")).json()
    assert got["session"] == "live" and got["day"] == "2026-09-28"
    assert got["price_kind"] == "live" and got["holds"] is True and got["prices"] is True
    assert got["percent"] == "1.54"  # against the quote's own previous close
    assert got["change"]["currency"] == "SGD" and got["change"]["amount"] != "0.0000"
    assert got["as_of_at"].startswith("2026-09-28T14:41:00")
    (nvda,) = got["movers"]  # the watched AMD is left out while something is held
    assert (nvda["symbol"], nvda["held"], nvda["price"], nvda["day_percent"]) == (
        "NVDA",
        True,
        "131.50",
        "1.54",
    )
    assert nvda["price_kind"] == "live" and nvda["price_day"] == "2026-09-28"
    assert nvda["headline"]["headline"] == "Nvidia wins a big order"
    assert nvda["headline"]["source"] == "Wire" and nvda["headline"]["url"].startswith("https://")
    assert world.quotes.asked == ["NVDA", "AMD"]  # the user's own stocks only


async def test_today_after_the_close_and_before_the_open(world: World) -> None:
    owner = await ready(world)
    await owner.get("/api/investments/today")  # while open: the quotes are fetched and kept
    world.clock.now = AFTER
    world.quotes.status = SHUT
    after = (await owner.get("/api/investments/today")).json()
    assert after["session"] == "closed_today" and after["price_kind"] == "provisional_close"
    world.clock.now = NOW + timedelta(days=1, hours=4)  # Tuesday 04:00 in New York
    before = (await owner.get("/api/investments/today")).json()
    assert before["session"] == "previous" and before["day"] == "2026-09-28"


async def test_today_without_holdings_shows_the_watchlist(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await watch(owner, "AMD")
    await with_prices(world, "AMD")
    open_market(world, "AMD")
    got = (await owner.get("/api/investments/today")).json()
    assert got["holds"] is False and got["change"] is None and got["percent"] is None
    assert [(m["symbol"], m["held"]) for m in got["movers"]] == [("AMD", False)]


async def test_today_never_shows_another_users_stocks(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite)).status_code == 200
    await hold(owner, "NVDA")
    await hold(member, "TSLA")
    await with_prices(world, "NVDA", "TSLA")
    open_market(world, "NVDA", "TSLA")
    mine = (await owner.get("/api/investments/today")).json()
    theirs = (await member.get("/api/investments/today")).json()
    assert [m["symbol"] for m in mine["movers"]] == ["NVDA"]
    assert [m["symbol"] for m in theirs["movers"]] == ["TSLA"]


# --- why ----------------------------------------------------------------------------------


async def test_why_reads_the_headlines_once_per_half_hour(world: World) -> None:
    owner = await ready(world)
    world.model.script.extend([say("Nvidia won a big order. That may explain the rise.")] * 2)
    first = await owner.send("POST", "/api/investments/today/nvda/why")
    assert first.status_code == 200
    body = first.json()
    assert body["symbol"] == "NVDA" and body["day"] == "2026-09-28" and not body["cached"]
    assert body["day_percent"] == "1.54"
    assert body["text"] == "Nvidia won a big order. That may explain the rise."
    assert [h["headline"] for h in body["headlines"]] == ["Nvidia wins a big order"]
    again = await owner.send("POST", "/api/investments/today/NVDA/why")
    assert again.json()["cached"] is True and again.json()["text"] == body["text"]
    assert len(world.model.seen) == 1
    # Half an hour on it is asked again.
    world.clock.now = OPEN_AT + timedelta(minutes=31)
    world.quotes.quotes = {}
    third = await owner.send("POST", "/api/investments/today/NVDA/why")
    assert third.json()["cached"] is False and len(world.model.seen) == 2


async def test_why_is_refused_for_stocks_that_are_not_the_users(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite)).status_code == 200
    await hold(member, "TSLA")
    await watch(member, "PLTR")
    await with_prices(world, "TSLA", "PLTR")
    open_market(world, "TSLA", "PLTR")
    await news(world, TSLA=[(TEN_AM, "Tesla recalls some cars")])
    world.model.script.append(say("Tesla recalled some cars. That may explain the move."))
    for symbol in ("TSLA", "PLTR", "ZZZZ"):
        got = await owner.send("POST", f"/api/investments/today/{symbol}/why")
        assert got.status_code == 404, symbol
    assert world.model.seen == []
    ok = await member.send("POST", "/api/investments/today/TSLA/why")
    assert ok.status_code == 200 and len(world.model.seen) == 1


async def test_why_needs_a_ticker_and_a_price_move(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await hold(owner, "NVDA")
    for bad in ("NOT A TICKER", "THISISFAR2LONGATICKER"):
        got = await owner.send("POST", f"/api/investments/today/{bad}/why")
        assert got.status_code in (404, 422), bad
    # No prices yet for a held stock: nothing to explain, and no model asked.
    got = await owner.send("POST", "/api/investments/today/NVDA/why")
    assert got.status_code == 422 and "no price move" in got.json()["detail"]
    assert world.model.seen == []


async def test_why_is_rate_limited_like_other_model_endpoints(world: World) -> None:
    owner = await ready(world)
    web: Any = world.app.state.web
    object.__setattr__(web, "limits", RateLimiter({"why": ((2, timedelta(minutes=5)),)}))
    world.model.script.append(say("It may be the order."))
    statuses = [
        (await owner.send("POST", "/api/investments/today/NVDA/why")).status_code for _ in range(3)
    ]
    assert statuses == [200, 200, 429]
    assert len(world.model.seen) == 1  # the second was kept; the third never got that far


async def test_a_model_that_fails_is_a_polite_error_not_a_crash(world: World) -> None:
    owner = await ready(world)
    world.model.script.append(RuntimeError("provider down"))
    got = await owner.send("POST", "/api/investments/today/NVDA/why")
    assert got.status_code == 422 and "can't read the headlines" in got.json()["detail"]


# --- the settings -------------------------------------------------------------------------


async def test_the_market_alert_settings_default_and_change(world: World) -> None:
    owner, _ = await owner_and_invite(world)
    current = (await owner.get("/api/notifications")).json()
    assert (current["quiet_start"], current["quiet_end"]) == ("23:00", "08:00")
    assert current["move_alert_percent"] == "5.0" and current["market_summary"] is True
    changed = await owner.send(
        "PUT",
        "/api/notifications",
        {
            "quiet_start": "22:30",
            "quiet_end": "07:00",
            "move_alert_percent": "3",
            "market_summary": False,
        },
    )
    assert changed.status_code == 200
    again = (await owner.get("/api/notifications")).json()
    assert (again["quiet_start"], again["quiet_end"]) == ("22:30", "07:00")
    assert again["move_alert_percent"] == "3.0" and again["market_summary"] is False
    assert again["frequency"] == "daily"  # not touched


async def test_changing_how_often_leaves_the_market_alerts_alone(world: World) -> None:
    owner, _ = await owner_and_invite(world)
    await owner.send(
        "PUT", "/api/notifications", {"move_alert_percent": 10, "market_summary": False}
    )
    await owner.send("PUT", "/api/notifications", {"frequency": "hourly"})
    got = (await owner.get("/api/notifications")).json()
    assert got["frequency"] == "hourly"
    assert got["move_alert_percent"] == "10.0" and got["market_summary"] is False


async def test_equal_quiet_times_mean_no_quiet_hours(world: World) -> None:
    owner, _ = await owner_and_invite(world)
    sent = await owner.send(
        "PUT", "/api/notifications", {"quiet_start": "00:00", "quiet_end": "00:00"}
    )
    assert sent.status_code == 200 and sent.json()["quiet_start"] == sent.json()["quiet_end"]


@pytest.mark.parametrize(
    "body",
    [
        {"move_alert_percent": 0},
        {"move_alert_percent": "0.9"},
        {"move_alert_percent": 20.5},
        {"move_alert_percent": 100},
        {"move_alert_percent": -3},
        {"move_alert_percent": "lots"},
        {"quiet_start": "25:00"},
        {"quiet_end": "late"},
        {"market_summary": "sometimes"},
        {"daily_at": "21:00", "frequency": "hourly"},
        {"surprise": 1},
    ],
)
async def test_bad_settings_are_refused_and_change_nothing(
    world: World, body: dict[str, Any]
) -> None:
    owner, _ = await owner_and_invite(world)
    before = (await owner.get("/api/notifications")).json()
    refused = await owner.send("PUT", "/api/notifications", body)
    assert refused.status_code == 422
    assert (await owner.get("/api/notifications")).json() == before
