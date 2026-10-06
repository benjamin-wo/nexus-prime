"""The research team end to end: a plan for a made-up stock with scripted analysts.
Every ticker, price and headline here is made up."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import departments as department_cases
from nexus.application import market as market_cases
from nexus.application import plans as plan_cases
from nexus.application import research as research_cases
from nexus.application.departments import StepContext
from nexus.domain.departments import Run, RunStatus
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import User
from nexus.domain.market import Bar
from nexus.domain.plans import PlanStatus, Verdict
from nexus.infra.db.tables import jobs
from tests.fakes import NOW, FakeNews, FakePrices, ScriptedModel, bar, call, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_departments import Shown
from tests.integration.test_email import person
from tests.integration.test_research import history

pytestmark = pytest.mark.integration


def analysts(*, made_up_price: bool = False) -> ScriptedModel:
    extra = " A run to 199.99 is likely." if made_up_price else ""
    return scripted(
        call("TechnicalView", summary=f"A steady climb above both averages.{extra}"),
        call(
            "NewsView",
            points=[
                {"text": "A rival opened a plant.", "sources": [1]},
                {"text": "An invented point.", "sources": [99]},  # cites nothing real
            ],
            risks=["A court ruling is due."],
        ),
        call(
            "LeadView",
            bull=["The trend is intact."],
            bear=[f"It's stretched.{extra}"],
            summary="Wait for a pullback to the entry zone. The trend is up.",
            invalidation="A close below the stop.",
        ),
    )


async def ready(uow: UowFactory) -> User:
    user = await person(uow)
    await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    await market_cases.refresh(uow, FakePrices({"AMD": history(80)}), now=NOW)
    news = FakeNews(headlines={"AMD": [(NOW - timedelta(hours=3), "A rival opens a plant")]})
    await research_cases.refresh_news(uow, news, now=NOW)
    return user


async def finish(
    uow: UowFactory, registry: department_cases.Departments, user: User, run: Run
) -> Run:
    shown = Shown()
    current: Run | None = run
    while current is not None and not current.finished:
        current = await department_cases.advance(uow, registry, shown, user, run.id, now=NOW)
    assert current is not None
    return current


async def test_a_plan_traces_every_price_to_code_and_every_point_to_a_source(
    uow: UowFactory,
) -> None:
    user = await ready(uow)
    model = analysts(made_up_price=True)
    registry = department_cases.default_registry([plan_cases.plan_kind(uow, model)])
    run = await plan_cases.start_plan(uow, registry, user, "amd", now=NOW)
    assert run.title == "Plan for AMD" and run.steps_total == 3
    done = await finish(uow, registry, user, run)
    assert done.status is RunStatus.DONE, done.error
    result = plan_cases.PlanResult.model_validate(done.result)
    assert result.verdict is Verdict.WAIT  # a steady climb: above its entry zone
    assert result.entry_low is not None and result.stop is not None
    assert result.entry_low < result.close and result.stop < result.entry_low
    # The made-up 199.99 is gone from every analyst's text.
    assert "199.99" not in result.technical and result.technical.startswith("A steady climb")
    assert result.bear == ["It's stretched."]
    # A point citing a headline that doesn't exist is dropped.
    assert [(p.text, p.sources) for p in result.news] == [("A rival opened a plant.", [1])]
    assert result.sources[0].headline == "A rival opens a plant"
    assert result.risks == ["A court ruling is due."]
    assert result.summary.startswith("Wait for a pullback")
    # The analysts saw headlines only as quoted data.
    news_prompt = str(model.seen[1][-1].content)
    assert "<headlines>" in news_prompt and "[1]" in news_prompt
    # Spend is counted (the scripted replies report no tokens, so it's zero here).
    assert done.spent == Decimal(0)
    saved = await plan_cases.list_plans(uow(), user.id, symbol="AMD")
    assert len(saved) == 1 and saved[0].id == result.plan_id
    assert saved[0].stop == result.stop
    line = plan_cases.summary_line(result)
    assert line.startswith("AMD: Wait for a dip to buy. It's above the buy zone")
    assert "\n🟢 Buy at " in line and "\n🎯 Sell part at " in line
    assert "\n🛑 Sell if a day closes below " in line and "\n📅 Valid until" in line


async def test_a_plan_needs_a_month_of_prices(uow: UowFactory) -> None:
    user = await person(uow)
    registry = department_cases.default_registry([plan_cases.plan_kind(uow, analysts())])
    with pytest.raises(InvalidInput, match="a month of prices for TSLA"):
        await plan_cases.start_plan(uow, registry, user, "TSLA", now=NOW)
    with pytest.raises(InvalidInput, match="aren't set up"):
        await plan_cases.start_plan(uow, department_cases.default_registry(), user, "TSLA", now=NOW)


async def test_asking_for_a_plan_in_chat(uow: UowFactory) -> None:
    user = await ready(uow)
    chat = scripted(
        call("research_plan", symbol="amd"),
        AIMessage(content="I've started a plan for AMD."),
        call("show_plan", symbol="amd"),
        AIMessage(content="Here it is."),
    )
    team = analysts()
    registry = department_cases.default_registry([plan_cases.plan_kind(uow, team)])
    agent = build(uow, chat, departments=registry)
    reply = only(await agent.handle_text(user.id, "plan for AMD", "m1"))
    assert reply.text == "I've started a plan for AMD."
    assert "Started 'Plan for AMD': 3 steps" in str(chat.seen[-1][-1].content)
    runs = await department_cases.list_runs(uow(), user.id, now=NOW)
    await finish(uow, registry, user, runs[0])
    only(await agent.handle_text(user.id, "show me the AMD plan", "m2"))
    shown = str(chat.seen[-1][-1].content)
    assert shown.startswith("Latest plan for AMD, made 28 Sep.")
    assert "AMD: Wait for a dip to buy." in shown and "🛑 Sell if a day closes below" in shown
    assert "What would prove it wrong: A close below the stop." in shown


async def test_plans_are_followed_after_each_close_with_alerts(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await ready(uow)
    registry = department_cases.default_registry([plan_cases.plan_kind(uow, analysts())])
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=NOW)
    await finish(uow, registry, user, run)
    saved = (await plan_cases.list_plans(uow(), user.id, symbol="AMD"))[0]
    assert saved.verdict is Verdict.WAIT and saved.entry_high is not None
    target = saved.first_target
    assert target is not None
    # Monday dips into the buy zone; Tuesday reaches the first target.
    zone = saved.entry_high
    monday = bar("AMD", date(2026, 9, 28), str(zone))
    tuesday = Bar("AMD", date(2026, 9, 29), zone, target + 1, zone, target, target, 1)
    async with uow() as tx:
        await tx.investments.save_bars("AMD", [monday, tuesday], known=True, at=NOW)
        await tx.commit()
    later = NOW + timedelta(days=1, hours=20)
    assert await plan_cases.follow_plans(uow, now=later) == 2
    done = (await plan_cases.list_plans(uow(), user.id, symbol="AMD"))[0]
    assert done.status is PlanStatus.TARGET and done.entered_on == date(2026, 9, 28)
    assert done.result_percent is not None and done.result_percent > 0
    async with engine.connect() as db:
        rows = (
            await db.execute(
                select(jobs.c.dedupe_key, jobs.c.payload)
                .where(jobs.c.kind == "telegram.send")
                .order_by(jobs.c.dedupe_key)
            )
        ).all()
    texts = {r.dedupe_key.rsplit(":", 1)[1]: r.payload for r in rows}
    assert texts["entry"]["text"].startswith("🟢 AMD dipped into its buy zone")
    assert texts["entry"]["buttons"] == []  # finished by the time the alerts went out
    assert texts["target"]["text"].startswith(f"🎯 AMD reached its first target, {target}")
    # Following again changes nothing and sends nothing twice.
    assert await plan_cases.follow_plans(uow, now=later) == 0
    r, finished = await plan_cases.track_record(uow(), user.id)
    assert (r.finished, r.targets) == (1, 1) and finished[0].id == done.id
    assert plan_cases.describe_record(r).startswith("1 finished: 1 hit their target")


async def test_alerts_can_be_turned_off_from_the_alert(uow: UowFactory) -> None:
    user = await ready(uow)
    registry = department_cases.default_registry([plan_cases.plan_kind(uow, analysts())])
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=NOW)
    await finish(uow, registry, user, run)
    saved = (await plan_cases.list_plans(uow(), user.id, symbol="AMD"))[0]
    agent = build(uow, scripted())
    reply = only(await agent.press(user.id, f"plan:mute:{saved.id}"))
    assert reply.text.startswith("🔕 No more alerts for that plan")
    assert not (await plan_cases.list_plans(uow(), user.id, symbol="AMD"))[0].alerts
    # A plan that ran out still finishes, quietly.
    assert await plan_cases.follow_plans(uow, now=NOW + timedelta(days=20)) == 0
    assert (await plan_cases.list_plans(uow(), user.id))[0].status is PlanStatus.EXPIRED


def uneven(days: int) -> dict[date, str]:
    """A made-up climb by uneven daily steps, ending the Friday before NOW."""
    last = date(2026, 9, 25)
    steps = [0.1, 1.2, 0.3, 0.9, 0.05, 1.5, 0.2, 0.6]
    price, closes = 100.0, {}
    for i in range(days):
        price += steps[i % len(steps)]
        closes[last - timedelta(days=days - 1 - i)] = f"{price:.2f}"
    return closes


async def test_a_plan_carries_odds_from_replaying_past_moves(uow: UowFactory) -> None:
    user = await person(uow)
    await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    await market_cases.refresh(uow, FakePrices({"AMD": uneven(120)}), now=NOW)
    view = await research_cases.stock(uow(), user, "AMD", today=NOW.date())
    assert [r.label for r in view.ranges] == ["1 week", "1 month", "3 months"]
    assert view.levels is not None and view.ranges[1].low_68 < view.levels.close
    team = analysts()
    registry = department_cases.default_registry([plan_cases.plan_kind(uow, team)])
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=NOW)
    done = await finish(uow, registry, user, run)
    assert done.status is RunStatus.DONE, done.error
    result = plan_cases.PlanResult.model_validate(done.result)
    # The analysts were shown the odds, likely ranges and history with the plan.
    brief = str(team.seen[0][-1].content)
    assert "Odds from replaying the last year's daily moves" in brief
    assert "Where the close is likely to be" in brief and "In 1 month: " in brief
    assert "Its last year, worked out from its prices:\nChange in price: 1 week +" in brief
    assert result.ranges[1].startswith("In 1 month: ")
    assert result.history[0].startswith("Change in price: 1 week +")
    odds = result.odds
    assert odds is not None and result.stop is not None
    assert odds.stop == result.stop
    assert [t.price for t in odds.targets] == [t.price for t in result.targets]
    assert odds.days == 11  # Friday 25 Sep to Monday 12 Oct, weekdays only
    assert abs(odds.targets[0].chance + odds.stop_first + odds.neither - 100) <= 1
    # The same prices always give the same odds.
    registry = department_cases.default_registry([plan_cases.plan_kind(uow, analysts())])
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=NOW)
    again = await finish(uow, registry, user, run)
    assert plan_cases.PlanResult.model_validate(again.result).odds == odds
    line = plan_cases.summary_line(result)
    assert "\n🎲 " in line and "Not a forecast." in line


def by_role(failing: set[str]) -> ScriptedModel:
    """Analysts that answer by role, whatever order the calls come in; the roles in
    ``failing`` fail on every try."""
    answers = {
        "technical": call("TechnicalView", summary="A steady climb above both averages."),
        "news": call(
            "NewsView", points=[{"text": "A rival opened a plant.", "sources": [1]}], risks=[]
        ),
        "lead": call(
            "LeadView",
            bull=["The trend is intact."],
            bear=["It's stretched."],
            summary="Wait for a pullback to the entry zone.",
            invalidation="A close below the stop.",
        ),
    }

    def answer(messages: Any) -> Any:
        prompt = str(messages[-1].content)
        role = next(r for r in answers if f"As the {r}" in prompt)
        if role in failing:
            raise RuntimeError(f"{role} provider error")
        return answers[role]

    return scripted(*[answer] * 12)


@pytest.mark.parametrize(
    ("failing", "missing"),
    [
        ({"technical"}, ["the chart reading"]),
        ({"news"}, ["the news"]),
        ({"lead"}, ["the case for and against"]),
        (
            {"technical", "news", "lead"},
            ["the chart reading", "the news", "the case for and against"],
        ),
    ],
)
async def test_a_writer_that_keeps_failing_doesnt_lose_the_plan(
    uow: UowFactory, failing: set[str], missing: list[str]
) -> None:
    user = await ready(uow)
    model = by_role(failing)
    registry = department_cases.default_registry([plan_cases.plan_kind(uow, model)])
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=NOW)
    done = await finish(uow, registry, user, run)
    assert done.status is RunStatus.DONE, done.error
    result = plan_cases.PlanResult.model_validate(done.result)
    assert result.incomplete == missing
    assert result.stop is not None and result.targets  # the numbers are all there
    if "lead" in failing:
        assert (result.bull, result.bear) == ([], [])
        assert result.summary == f"{result.verdict_text}. {result.reason}"
        assert result.invalidation == f"A daily close below {result.stop} would prove it wrong."
    if "technical" not in failing:
        assert result.technical.startswith("A steady climb")
    # Each failing role was tried twice, no more.
    tries = [str(m[-1].content) for m in model.seen]
    for role in failing:
        assert sum(f"As the {role}" in t for t in tries) == 2
    line = plan_cases.summary_line(result)
    assert line.endswith(
        f"⚠️ The write-up is missing {' and '.join(missing)} this time; the prices and game "
        "plan are complete."
    )
    saved = await plan_cases.list_plans(uow(), user.id, symbol="AMD")
    assert saved[0].body["incomplete"] == missing


async def test_a_slow_writer_is_cut_off_and_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_cases, "CALL_TIMEOUT", 0.05)

    class Slow:
        calls = 0

        def with_structured_output(self, schema: Any, include_raw: bool = False) -> Any:
            return self

        async def ainvoke(self, messages: Any) -> Any:
            Slow.calls += 1
            if Slow.calls == 1:
                await asyncio.sleep(1)
            return {"raw": None, "parsed": plan_cases.TechnicalView(summary="Fine.")}

    ctx = StepContext(run=None, user=None, now=NOW)  # type: ignore[arg-type]
    view = await plan_cases._ask(Slow(), plan_cases.TechnicalView, "prompt", ctx)  # type: ignore[arg-type]
    assert view.summary == "Fine." and Slow.calls == 2


def reviewer(*replies: Any) -> ScriptedModel:
    return scripted(*replies)


async def test_an_optional_reviewer_corrects_the_draft_before_its_saved(uow: UowFactory) -> None:
    user = await ready(uow)
    senior = reviewer(
        call(
            "ReviewView",
            technical="A steady climb: it closes above its 20-day average (the mean close of "
            "the last 20 trading days).",
            bull=["The climb is steady."],
            bear=["It may not dip to the zone. A run to 199.99 is likely."],  # made up
            summary="Wait for a dip to the buy zone before buying.",
            invalidation="",  # left out: the draft's is kept
        )
    )
    kind = plan_cases.plan_kind(uow, analysts(), reviewer=senior)
    registry = department_cases.default_registry([kind])
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=NOW)
    assert run.steps_total == 4
    done = await finish(uow, registry, user, run)
    assert done.status is RunStatus.DONE, done.error
    result = plan_cases.PlanResult.model_validate(done.result)
    assert result.technical.endswith("(the mean close of the last 20 trading days).")
    assert result.bull == ["The climb is steady."]
    assert result.bear == ["It may not dip to the zone."]  # the made-up price is still dropped
    assert result.summary == "Wait for a dip to the buy zone before buying."
    assert result.invalidation == "A close below the stop."
    # The reviewer saw the figures and the draft; the plan was saved once, as reviewed.
    prompt = str(senior.seen[0][-1].content)
    assert "<draft>" in prompt and "Case against: It's stretched." in prompt
    saved = await plan_cases.list_plans(uow(), user.id, symbol="AMD")
    assert len(saved) == 1 and saved[0].body["summary"] == result.summary


async def test_a_reviewer_that_fails_leaves_the_draft(uow: UowFactory) -> None:
    user = await ready(uow)

    def broken(_: Any) -> Any:
        raise RuntimeError("provider error")

    senior = reviewer(broken)
    kind = plan_cases.plan_kind(uow, analysts(), reviewer=senior)
    registry = department_cases.default_registry([kind])
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=NOW)
    done = await finish(uow, registry, user, run)
    assert done.status is RunStatus.DONE, done.error
    result = plan_cases.PlanResult.model_validate(done.result)
    assert result.summary.startswith("Wait for a pullback") and result.incomplete == []
    assert len(senior.seen) == 1  # one try: the draft is good enough to keep
    saved = await plan_cases.list_plans(uow(), user.id, symbol="AMD")
    assert len(saved) == 1 and saved[0].id == result.plan_id


async def test_the_market_and_past_earnings_feed_the_history(uow: UowFactory) -> None:
    user = await person(uow)
    await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    prices = FakePrices({"AMD": uneven(120), "SPY": history(120, start=400)})
    await market_cases.refresh(uow, prices, now=NOW)
    assert {s for s, _, _ in prices.asked} == {"AMD", "SPY"}  # the market comes along
    reported = date(2026, 8, 20)  # a Thursday, after the close
    news = FakeNews(earnings_days={"AMD": [reported, date(2026, 10, 27)]})
    await research_cases.refresh_news(uow, news, now=NOW)
    # Fetched again: the future date is replaced, the past one kept.
    await research_cases.refresh_news(uow, news, now=NOW + timedelta(hours=7))
    view = await research_cases.stock(uow(), user, "AMD", today=NOW.date())
    assert view.earnings is not None and view.earnings.day == date(2026, 10, 27)
    h = view.history
    assert h is not None
    assert [r.day for r in h.earnings] == [reported]
    assert [v.label for v in h.versus] == ["1 month", "3 months"]  # under a year of prices
