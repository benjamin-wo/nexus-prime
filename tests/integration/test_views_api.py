"""``GET /api/views/{kind}`` (ADR 0005): the figures behind each view, read by the same use
case the surfacing tool uses. One parity test per view: the endpoint's figures are the ones the
tool's text states, for the same seed. Plus consent, numbers-free mode, a trip member, the
setting, and the chat endpoints that carry views (stream, history, plain and voice). Every name
and figure is made up."""

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import budgets as budget_cases
from nexus.application import health as health_cases
from nexus.application import investments as investment_cases
from nexus.application.users import find_telegram_user, get_user
from nexus.domain.health import SampleKind, SampleSource
from nexus.domain.money import Money
from nexus.evals import seed
from nexus.evals.runner import FixedRates
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.main import Overrides, create_app
from nexus.settings import Settings
from tests.fakes import FakeSpeech, FakeTelegram, ScriptedModel, call, models, say, scripted
from tests.integration.test_voice_notes import AUDIO
from tests.integration.test_web_api import ORIGIN, OWNER, TOKEN, Browser, Clock, sse

pytestmark = pytest.mark.integration

MEMBER = 4100  # a trip member who owns nothing of the Japan trip's money


class World:
    def __init__(self, app: Any, engine: AsyncEngine, model: ScriptedModel) -> None:
        self.app = app
        self.engine = engine
        self.model = model

    def uow(self) -> SqlUnitOfWork:
        return SqlUnitOfWork(self.engine)

    async def browser(self, telegram_id: int) -> Browser:
        found = await find_telegram_user(self.uow(), telegram_id)
        assert found is not None
        async with self.uow() as tx:  # seeded users have no web access until given
            await tx.ledger.grant_web_access(found.id, seed.NOW)
            await tx.commit()
        browser = Browser(self.app, Clock(seed.NOW))
        response = await browser.login(telegram_id)
        assert response.status_code == 200, response.text
        return browser

    async def tool(self, telegram_id: int, name: str, **args: Any) -> str:
        found = await find_telegram_user(self.uow(), telegram_id)
        assert found is not None
        ctx = ToolContext(
            await get_user(self.uow(), found.id), self.uow, seed.NOW, rates=FixedRates()
        )
        result = await run_tool(build_tools(lambda _: "")[name], ctx, args)
        assert result.error is None, result.text
        return result.text


def make_app(
    url: str, model: ScriptedModel, *, views: bool, speech: FakeSpeech | None = None
) -> Any:
    return create_app(
        Settings(
            _env_file=None,
            database_url=url,
            telegram_bot_token=TOKEN,
            telegram_webhook_secret="hook",
            admin_telegram_chat_id=OWNER,
            web_origin=ORIGIN,
            default_timezone="Asia/Singapore",
            openrouter_api_key=None,
            views_enabled=views,
        ),
        Overrides(
            models=models(model),
            speech=speech,
            telegram=FakeTelegram(),
            checkpointer=InMemorySaver(),
            clock=lambda: seed.NOW,
            rates=FixedRates(),
        ),
    )


async def seeded(world: World) -> None:
    """The owner: the eval seed with Health (a Push routine, lifts, lunch), a budget, two stocks
    and three weigh-ins. A second user was added to the owner's Japan trip as a member."""
    uow = world.uow
    owner = (await seed.seed_user(uow, OWNER, gym=True, food=True)).user
    await budget_cases.set_budget(uow(), owner, None, Money.of("1500", "SGD"), now=seed.NOW)
    for symbol, quantity, price in (("NVDA", "4", "100"), ("TSLA", "2", "250")):
        await investment_cases.record_trade(
            uow(), owner.id, investment_cases.Side.BUY, symbol, Decimal(quantity),
            Money.of(price, "USD"), now=seed.NOW,
        )  # fmt: skip
    for days, kg in (
        (13, "84.0"),
        (11, "83.8"),
        (9, "83.7"),
        (7, "83.5"),
        (4, "83.2"),
        (1, "83.0"),
    ):
        await health_cases.log_sample(
            uow(), owner.id, SampleKind.WEIGHT, Decimal(kg), source=SampleSource.MANUAL,
            start_at=seed.NOW - timedelta(days=days),
            now=seed.NOW,
        )  # fmt: skip
    await seed.seed_user(uow, MEMBER, shared=True)


@pytest.fixture
async def world(engine: AsyncEngine, empty_database_url: str) -> AsyncIterator[World]:
    model = scripted()
    app = make_app(empty_database_url, model, views=True)
    async with app.router.lifespan_context(app):
        w = World(app, engine, model)
        await seeded(w)
        yield w


def amount(money: dict[str, str] | None) -> str:
    """A figure as the tool's text writes it: thousands separated."""
    assert money is not None
    return f"{Decimal(money['amount']):,}"


async def get(world: World, who: int, kind: str, **params: str) -> Response:
    return await (await world.browser(who)).get(f"/api/views/{kind}", params=params)


# --- one parity test per view -----------------------------------------------------------------


async def test_month_outlook_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(OWNER, "month_outlook", month="2026-09")
    response = await get(world, OWNER, "finance.month_outlook", month="2026-09")
    assert response.status_code == 200
    body = response.json()
    assert body["caption"] == "Your outlook for September 2026"
    summary = body["summary"]
    assert amount(summary["received"]) in text and amount(summary["spent"]) in text
    assert amount(summary["overall"]) in text
    assert body["params"] == {"month": "2026-09"}


async def test_an_adjusted_outlook_shows_the_figures_of_the_reply(world: World) -> None:
    adjustments = [{"amount": "-2000", "label": "the sofa"}]
    text = await world.tool(OWNER, "month_outlook", month="2026-09", adjustments=adjustments)
    plain = await world.tool(OWNER, "month_outlook", month="2026-09")
    response = await get(
        world,
        OWNER,
        "finance.month_outlook",
        month="2026-09",
        adjustments=json.dumps(adjustments),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["caption"] == "Your outlook for September 2026, with 2,000 for the sofa"
    assert body["params"]["adjustments"] == adjustments
    summary = body["summary"]
    assert amount(summary["overall"]) in text and amount(summary["overall"]) not in plain
    assert amount(summary["received"]) in text and amount(summary["spent"]) in text


async def test_budgets_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(OWNER, "list_budgets")
    body = (await get(world, OWNER, "finance.budgets", month="2026-09")).json()
    rows = body["summary"]["budgets"]
    assert rows and body["summary"]["count"] == len(rows)
    for row in rows:
        assert (
            f"{row['name']}: {amount(row['spent'])} SGD of {amount(row['limit'])} SGD this "
            f"month ({row['percent']}%)"
        ) in text


async def test_spending_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(
        OWNER, "query_ledger", group_by="category", start_date="2026-09-01", end_date="2026-09-30"
    )
    body = (await get(world, OWNER, "finance.spending", month="2026-09")).json()
    assert amount(body["summary"]["spent"]) in text
    for row in body["summary"]["categories"]:
        assert row["name"] in text and amount(row["total"]) in text


async def owners_trip(world: World, telegram_id: int) -> str:
    found = await find_telegram_user(world.uow(), telegram_id)
    assert found is not None
    async with world.uow() as tx:
        [trip] = await tx.trips.list_trips(found.id)
    return str(trip.id)


async def test_trip_budget_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(OWNER, "trip_status", trip="Tokyo")
    trip_id = await owners_trip(world, OWNER)
    body = (await get(world, OWNER, "travel.trip_budget", trip_id=trip_id)).json()
    summary = body["summary"]
    assert amount(summary["budget"]) in text
    assert amount(summary["spent"]) in text and amount(summary["left"]) in text


async def test_a_trip_members_card_never_has_the_owners_money(world: World) -> None:
    trip_id = await owners_trip(world, MEMBER + seed.OWNER_OFFSET)
    refused = await get(world, MEMBER, "travel.trip_budget", trip_id=trip_id)
    assert refused.status_code == 404


async def test_portfolio_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(OWNER, "show_portfolio")
    body = (await get(world, OWNER, "invest.portfolio")).json()
    summary = body["summary"]
    assert summary["holdings"] == 2 and "NVDA" in text and "TSLA" in text
    for figure in ("value", "cost", "gain"):  # stated by the tool when it has them
        if summary[figure] is not None:
            assert amount(summary[figure]) in text


async def test_today_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(OWNER, "food_today")
    body = (await get(world, OWNER, "health.today")).json()
    summary = body["summary"]
    assert f"{summary['kcal']} kcal" in text
    assert summary["meals"] == 1
    assert summary["workout"]["state"] == "planned" and summary["workout"]["routine"] == "Push"
    assert body["caption"] == "Your day"


async def test_weight_trend_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(OWNER, "log_weight", value="82.4")
    body = (await get(world, OWNER, "health.weight_trend")).json()
    summary = body["summary"]
    assert f"Your trend is {summary['trend_words']}" in text
    assert summary["kg_a_week"] is not None and summary["kg_a_week"].lstrip("-") in text.replace(
        "about ", ""
    )


async def test_workout_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(OWNER, "todays_workout")
    body = (await get(world, OWNER, "health.workout")).json()
    assert body["summary"]["state"] == "planned"
    assert f"Today's routine from the plan: {body['summary']['routine']}." in text
    assert body["summary"]["exercises"] == 2


async def test_a_suggested_workout_needs_its_suggestion(world: World) -> None:
    missing = await get(world, OWNER, "health.workout", state="suggested")
    assert missing.status_code == 422 or missing.status_code == 400


async def test_records_figures_are_what_the_tool_states(world: World) -> None:
    text = await world.tool(OWNER, "personal_records")
    body = (await get(world, OWNER, "health.records")).json()
    rows = body["summary"]["records"]
    assert rows
    for row in rows:
        assert row["exercise"] in text
        assert row["heaviest_kg"] is not None and row["heaviest_kg"].rstrip("0").rstrip(".") in text


# --- who may see what -------------------------------------------------------------------------


async def test_a_health_view_needs_the_users_consent(world: World) -> None:
    # The member never agreed to Health.
    for kind in ("health.today", "health.weight_trend", "health.workout", "health.records"):
        assert (await get(world, MEMBER, kind)).status_code == 403, kind


async def test_numbers_free_mode_leaves_the_numbers_out_of_health_views(world: World) -> None:
    await world.tool(OWNER, "update_health_profile", numbers_free=True)
    today = (await get(world, OWNER, "health.today")).json()["summary"]
    assert today["kcal"] is None and today["protein_g"] is None and today["kcal_target"] is None
    weight = (await get(world, OWNER, "health.weight_trend")).json()["summary"]
    assert weight["hidden"] is True
    assert weight["trend_kg"] is None and weight["kg_a_week"] is None
    assert weight["trend_words"] in {"up", "down", "steady", "slowly up", "slowly down"}


async def test_the_endpoint_refuses_bad_params_planned_views_and_strangers(world: World) -> None:
    owner = await world.browser(OWNER)
    assert (await owner.get("/api/views/finance.month_outlook")).status_code == 422
    bad = await owner.get("/api/views/finance.month_outlook", params={"month": "2026-13"})
    assert bad.status_code == 422
    extra = await owner.get(
        "/api/views/finance.month_outlook", params={"month": "2026-09", "user_id": "x"}
    )
    assert extra.status_code == 422
    assert (await owner.get("/api/views/nothing.here")).status_code == 404
    assert (await owner.get("/api/views/finance.transactions")).status_code == 404  # planned
    stranger = Browser(world.app, Clock(seed.NOW))
    assert (await stranger.get("/api/views/invest.portfolio")).status_code == 401


# --- the setting ------------------------------------------------------------------------------


async def test_config_says_whether_views_are_on(world: World) -> None:
    config = await Browser(world.app, Clock(seed.NOW)).get("/api/config")
    assert config.json()["views_enabled"] is True


async def test_with_views_off_there_is_no_endpoint_and_config_says_so(
    engine: AsyncEngine, empty_database_url: str
) -> None:
    app = make_app(empty_database_url, scripted(), views=False)
    async with app.router.lifespan_context(app):
        browser = Browser(app, Clock(seed.NOW))
        assert (await browser.login(OWNER)).status_code == 200
        assert (await browser.get("/api/config")).json()["views_enabled"] is False
        assert (await browser.get("/api/views/invest.portfolio")).status_code == 404


# --- the chat carries the views ---------------------------------------------------------------


@pytest.fixture
async def chat(
    engine: AsyncEngine, empty_database_url: str
) -> AsyncIterator[tuple[Any, ScriptedModel, FakeSpeech]]:
    model, speech = scripted(), FakeSpeech()
    app = make_app(empty_database_url, model, views=True, speech=speech)
    async with app.router.lifespan_context(app):
        w = World(app, engine, model)
        await seeded(w)
        yield await w.browser(OWNER), model, speech


async def test_the_stream_sends_view_show_before_the_replies_and_history_keeps_the_refs(
    chat: tuple[Browser, ScriptedModel, FakeSpeech],
) -> None:
    owner, model, _ = chat
    model.script += [
        call("month_outlook", month="2026-09"),
        call("present", view="finance.spending", params={"month": "2026-09"}, focus=True),
        say("Here is your month."),
    ]
    streamed = await owner.send("POST", "/api/chat/stream", {"message": "how is my month"})
    events = sse(streamed)
    names = [e for e, _ in events]
    assert names[-3:] == ["view.show", "view.show", "replies"]
    first, second = (d for e, d in events if e == "view.show")
    assert first["kind"] == "finance.month_outlook" and first["focus"] is False
    assert second["kind"] == "finance.spending" and second["focus"] is True  # the latest present
    assert set(first) == {"view_id", "kind", "params", "focus", "caption", "summary"}
    assert first["caption"] == "Your outlook for September 2026"
    assert first["summary"]["received"]["currency"] == "SGD"
    [reply] = events[-1][1]
    assert [v["kind"] for v in reply["views"]] == ["finance.month_outlook", "finance.spending"]
    lines = (await owner.get("/api/chat/history")).json()["lines"]
    assert lines[0]["views"] == []
    assert lines[1]["views"] == [
        {"kind": "finance.month_outlook", "params": {"month": "2026-09"}, "focus": False},
        {"kind": "finance.spending", "params": {"month": "2026-09"}, "focus": True},
    ]
    assert "summary" not in json.dumps(lines[1]["views"])  # never figures


async def test_a_plain_post_and_a_voice_note_carry_the_views_too(
    chat: tuple[Browser, ScriptedModel, FakeSpeech],
) -> None:
    owner, model, speech = chat
    model.script += [call("show_portfolio"), say("Here you go.")]
    [reply] = (await owner.send("POST", "/api/chat", {"message": "my portfolio"})).json()
    assert [(v["kind"], v["focus"]) for v in reply["views"]] == [("invest.portfolio", True)]

    model.script += [call("list_budgets"), say("Your budgets.")]
    speech.script += ["How are my budgets?"]
    voiced = await owner.client.post(
        "/api/chat/voice",
        files={"audio": ("note", AUDIO, "audio/webm")},
        headers={"Origin": ORIGIN, "X-CSRF-Token": owner.csrf},
    )
    [reply] = voiced.json()
    assert [(v["kind"], v["focus"]) for v in reply["views"]] == [("finance.budgets", True)]
