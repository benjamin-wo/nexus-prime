"""The evaluation harness itself: the cases are well formed, the seed's figures
are what the cases expect, and grading works end to end (with a scripted model;
real models are scored on demand with ``python -m nexus.evals``)."""

from collections.abc import Callable
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.ports import LedgerQuery
from nexus.domain.ledger import Direction
from nexus.evals import seed
from nexus.evals.cases import CASES, WRITES, Case
from nexus.evals.runner import FixedRates, run_cases
from nexus.infra.db.uow import SqlUnitOfWork
from tests.fakes import call, say, scripted

pytestmark = pytest.mark.integration


def test_cases_are_well_formed() -> None:
    tools = {n: s for n, s in build_tools(SkillLibrary.load().body).items() if s.exposed}
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)) and len(ids) >= 100
    for case in CASES:
        assert case.turns, case.id
        for wanted in case.calls:
            assert wanted.tool in tools, (case.id, wanted.tool)
            assert set(wanted.args) <= set(tools[wanted.tool].args.model_fields), case.id
        assert set(case.forbid) <= set(tools), case.id
        has_expectation = case.calls or case.asks or case.unchanged or case.reply or case.checks
        assert has_expectation, f"{case.id} expects nothing"
    assert set(WRITES) <= set(tools)


async def test_the_seed_matches_the_figures_the_cases_expect(engine: AsyncEngine) -> None:
    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(engine)

    user = (await seed.seed_user(uow, 777)).user
    sept = datetime(2026, 9, 1, tzinfo=seed.TZ)
    aug = datetime(2026, 8, 1, tzinfo=seed.TZ)
    end = datetime.combine(seed.NOW.date() + timedelta(days=1), time(), tzinfo=seed.TZ)

    async def spent(start: datetime, stop: datetime) -> Decimal:
        summary = await tx_cases.summarize_in_home(uow(), FixedRates(), user, start, stop)
        return next(t.total.amount for t in summary.totals if t.direction is Direction.OUT)

    assert await spent(sept, end) == Decimal(seed.SEPT_SPENT)
    assert await spent(aug, sept) == Decimal(seed.AUG_SPENT)

    page = await tx_cases.list_ledger(uow(), user.id, LedgerQuery(search="grab", limit=100))
    grab = [t for t in page.items if t.occurred_at >= sept]
    assert sum(t.amount.amount for t in grab) == Decimal(seed.SEPT_GRAB)
    weekend = [t for t in grab if t.occurred_at.astimezone(seed.TZ).weekday() >= 5]
    assert sum(t.amount.amount for t in weekend) == Decimal(seed.SEPT_WEEKEND_GRAB)
    august = [t for t in page.items if aug <= t.occurred_at < sept]
    assert sum(t.amount.amount for t in august) == Decimal(seed.AUG_GRAB)

    ious = await split_cases.list_open_ious(uow(), user.id)
    ann = [i for i in ious if i.split.participant_name == "Ann"]
    assert [i.outstanding.amount for i in ann] == [Decimal(seed.ANN_OWES)]


def _only(*ids: str) -> list[Case]:
    return [c for c in CASES if c.id in ids]


async def test_grading_passes_the_right_behaviour_and_fails_the_wrong(
    engine: AsyncEngine,
) -> None:
    scripts: dict[str, Callable[[], BaseChatModel]] = {
        "log-grab": lambda: scripted(
            call("log_expense", amount="12", merchant="Grab", best_guess_category="Transport"),
            say("Logged 12.00 at Grab."),
        ),
        "ask-no-amount": lambda: scripted(say("How much was lunch?")),
        "income-bonus": lambda: scripted(
            call("record_income", amount="500", kind="other", note="bonus"),
            say("Recorded your 500 bonus."),
        ),
        "safe-transfer": lambda: scripted(),  # the kernel refuses; no model call
        "q-month-spent": lambda: scripted(say("You spent 10.00 this month.")),  # wrong
        "ask-in-or-out": lambda: scripted(  # logs instead of asking
            call("log_expense", amount="50", best_guess_category="Other"), say("Logged 50.")
        ),
    }
    results = {
        r.case.id: r
        for r in await run_cases(
            engine,
            lambda case: scripts[case.id](),
            _only(*scripts),
            concurrency=2,
        )
    }
    for good in ("log-grab", "ask-no-amount", "income-bonus", "safe-transfer"):
        assert results[good].passed, (good, results[good].failures, results[good].error)
    assert results["income-bonus"].turns[0].confirmations == 1
    assert results["q-month-spent"].failures == [f"reply lacks '{seed.SEPT_SPENT}'"]
    assert results["ask-in-or-out"].failures == [
        "didn't ask a question",
        "changed data instead of asking",
    ]
