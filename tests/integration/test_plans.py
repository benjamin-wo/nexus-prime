"""The research team end to end: a plan for a made-up stock with scripted analysts.
Every ticker, price and headline here is made up."""

from datetime import timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from nexus.application import departments as department_cases
from nexus.application import market as market_cases
from nexus.application import plans as plan_cases
from nexus.application import research as research_cases
from nexus.domain.departments import Run, RunStatus
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import User
from nexus.domain.plans import Verdict
from tests.fakes import NOW, FakeNews, FakePrices, ScriptedModel, call, scripted
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
        call("Debate", bull=["The trend is intact."], bear=[f"It's stretched.{extra}"]),
        call(
            "LeadView",
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
    assert run.title == "Plan for AMD" and run.steps_total == 5
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
    assert line.startswith("AMD: Wait for a pullback to the entry zone. Entry ")


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
    assert "Started 'Plan for AMD': 5 steps" in str(chat.seen[-1][-1].content)
    runs = await department_cases.list_runs(uow(), user.id, now=NOW)
    await finish(uow, registry, user, runs[0])
    only(await agent.handle_text(user.id, "show me the AMD plan", "m2"))
    shown = str(chat.seen[-1][-1].content)
    assert shown.startswith("Latest plan for AMD, made 28 Sep.")
    assert "AMD: Wait for a pullback to the entry zone. Entry " in shown
    assert "What would prove it wrong: A close below the stop." in shown
