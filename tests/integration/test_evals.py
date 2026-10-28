"""The evaluation harness itself: the cases are well formed, the seed's figures
are what the cases expect, and grading works end to end (with a scripted model;
real models are scored on demand with ``python -m nexus.evals``)."""

from collections.abc import Callable
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.ports import LedgerQuery
from nexus.domain.ledger import Direction
from nexus.evals import clips, photos, seed
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
        for turn in case.turns:
            assert turn.photo is None or photos.known(turn.photo), (case.id, turn.photo)
            assert turn.audio is None or clips.known(turn.audio), (case.id, turn.audio)
            assert not (turn.audio and turn.photo), case.id
        for wanted in case.calls:
            assert wanted.tool in tools, (case.id, wanted.tool)
            assert set(wanted.args) <= set(tools[wanted.tool].args.model_fields), case.id
        assert set(case.forbid) <= set(tools), case.id
        assert {cap.tool for cap in case.at_most} <= set(tools), case.id
        has_expectation = (
            case.calls
            or case.asks
            or case.unchanged
            or case.reply
            or case.checks
            or case.forbid
            or case.confirms is not None
        )
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

    # The harder questions' figures.
    in_sept = await tx_cases.summarize_in_home(uow(), FixedRates(), user, sept, end)
    received = next(t.total.amount for t in in_sept.totals if t.direction is Direction.IN)
    assert received - Decimal(seed.SEPT_SPENT) == Decimal("4539.97")
    assert Decimal(seed.DINING_BUDGET) - Decimal(seed.SEPT_DINING) == Decimal("156.10")
    kopi = await tx_cases.list_ledger(uow(), user.id, LedgerQuery(search="kopitiam", start=sept))
    assert sum(t.amount.amount for t in kopi.items) == Decimal("11.40")
    shops = [t for t in (await tx_cases.list_ledger(uow(), user.id, LedgerQuery(limit=100))).items]
    shopping = [t for t in shops if t.counterparty in {"Uniqlo", "Shopee"}]
    assert sum(t.amount.amount for t in shopping) == Decimal("94.80")
    assert len(grab) == 4

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


async def test_the_wallet_cases_are_graded_on_data_not_just_words(engine: AsyncEngine) -> None:
    scripts: dict[str, Callable[[], BaseChatModel]] = {
        "wallet-move-ibkr": lambda: scripted(
            call("log_move", amount="800", to_wallet="IBKR"), say("Logged 800 to IBKR.")
        ),
        "wallet-card-bill": lambda: scripted(  # logs an expense instead of a move
            call("log_expense", amount="1240", merchant="Card", best_guess_category="Other"),
            say("Logged."),
        ),
        "wallet-out-of-savings": lambda: scripted(
            call("log_move", amount="300", from_wallet="Savings", to_wallet="Spending"),
            say("Logged."),
        ),
        "wallet-person-is-not-a-move": lambda: scripted(
            call("log_expense", amount="50", merchant="Alex", best_guess_category="Dining Out"),
            say("Logged 50 for dinner with Alex."),
        ),
        "wallet-unknown-asks": lambda: scripted(
            say("I don't have a Tiger wallet. Want me to add it as an investment wallet?")
        ),
        "wallet-instruction-refused": lambda: scripted(),  # the kernel refuses; no model call
    }
    results = {
        r.case.id: r
        for r in await run_cases(
            engine, lambda case: scripts[case.id](), _only(*scripts), concurrency=2
        )
    }
    for good in (
        "wallet-move-ibkr",
        "wallet-out-of-savings",
        "wallet-person-is-not-a-move",
        "wallet-unknown-asks",
        "wallet-instruction-refused",
    ):
        assert results[good].passed, (good, results[good].failures, results[good].error)
    assert results["wallet-move-ibkr"].turns[0].confirmations == 1
    # An expense where a move was due fails on the data, whatever the reply said.
    assert results["wallet-card-bill"].failures == [
        "called log_expense",
        "didn't ask to confirm",
        "expected moved 1240 SGD from Spending to Card",
        "expected no expense or income of 1240",
    ]


async def test_the_seed_has_wallets_but_no_moves(engine: AsyncEngine) -> None:
    user = (await seed.seed_user(lambda: SqlUnitOfWork(engine), 778)).user
    async with SqlUnitOfWork(engine) as db:
        wallets = await db.ledger.list_wallets(user.id)
    assert [w.name for w in wallets] == ["Spending", "Card", "IBKR", "Savings"]
    page = await tx_cases.list_ledger(
        SqlUnitOfWork(engine), user.id, LedgerQuery(direction=Direction.MOVE)
    )
    assert page.total == 0


async def test_the_shared_trip_cases_seed_a_member_and_grade_the_owners_trip(
    engine: AsyncEngine,
) -> None:
    seeded = await seed.seed_user(lambda: SqlUnitOfWork(engine), 779, shared=True)
    assert seeded.owner is not None and seeded.trip_id is not None
    async with SqlUnitOfWork(engine) as db:
        assert await db.trips.list_trips(seeded.user.id) == []  # the user owns no trip
        assert [t.destination for t, _ in await db.trips.list_member_trips(seeded.user.id)] == [
            "Tokyo, Japan"
        ]
        owner = await db.ledger.get_user(seeded.owner.id)
    assert owner is not None and owner.display_name == seed.OWNER_NAME

    scripts: dict[str, Callable[[], BaseChatModel]] = {
        "shared-trip-add-plan": lambda: scripted(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "add_to_itinerary",
                        "args": {
                            "kind": "activity",
                            "name": "Dinner at Sushi Ten",
                            "day": "2026-12-12",
                            "time": "19:00",
                        },
                        "id": "call-sushi",
                    }
                ],
            ),
            say("Added dinner at Sushi Ten to Alex's Japan trip."),
        ),
        "shared-trip-budget-refused": lambda: scripted(
            call("update_trip", trip="Japan", budget="5000"),
            say("Only Alex can change money or the trip's details on a shared trip."),
        ),
    }
    results = {
        r.case.id: r
        for r in await run_cases(
            engine, lambda case: scripts[case.id](), _only(*scripts), concurrency=2
        )
    }
    for good in scripts:
        assert results[good].passed, (good, results[good].failures, results[good].error)
    assert results["shared-trip-add-plan"].turns[0].confirmations == 1
    assert results["shared-trip-budget-refused"].turns[0].confirmations == 0

    # A model that changes the budget anyway, or that adds nothing, is graded on the
    # owner's trip, not on the member's own data.
    wrong = {
        "shared-trip-add-plan": lambda: scripted(say("Sure, I added it.")),
        "shared-trip-budget-refused": lambda: scripted(say("Done, the Japan budget is 5000.")),
    }
    failed = {
        r.case.id: r
        for r in await run_cases(
            engine,
            lambda case: wrong[case.id](),
            _only(*wrong),
            concurrency=2,
            first_telegram_id=910_000,
        )
    }
    assert any("Sushi Ten" in f for f in failed["shared-trip-add-plan"].failures)
    assert "reply lacks 'alex'" in failed["shared-trip-budget-refused"].failures


async def test_the_voice_cases_for_lasting_and_one_off_style(engine: AsyncEngine) -> None:
    memory = (say("nothing to remember"), say("nothing to remember"))
    good = {
        "voice-shorter-from-now-on": lambda: scripted(
            call("set_voice", length="short"), say("Done."), *memory
        ),
        "voice-one-off-short": lambda: scripted(say("Food: 58 this week."), *memory),
    }
    results = {
        r.case.id: r
        for r in await run_cases(engine, lambda case: good[case.id](), _only(*good), concurrency=2)
    }
    for case_id in good:
        assert results[case_id].passed, (case_id, results[case_id].failures, results[case_id].error)

    # Only remembering it is not enough, and a one-off must not change the voice.
    wrong = {
        "voice-shorter-from-now-on": lambda: scripted(say("Sure."), *memory),
        "voice-one-off-short": lambda: scripted(
            call("set_voice", length="short"), say("Food: 58 this week."), *memory
        ),
    }
    failed = {
        r.case.id: r
        for r in await run_cases(
            engine,
            lambda case: wrong[case.id](),
            _only(*wrong),
            concurrency=2,
            first_telegram_id=930_000,
        )
    }
    assert not failed["voice-shorter-from-now-on"].passed
    assert not failed["voice-one-off-short"].passed


async def test_the_voice_cases_are_graded_on_the_saved_voice_and_the_wording(
    engine: AsyncEngine,
) -> None:
    # After each turn the memory writer shares the scripted model and takes two steps (it
    # tries twice when a reply doesn't parse).
    memory = (say("nothing to remember"), say("nothing to remember"))
    grab = call("log_expense", amount="12", merchant="Grab", best_guess_category="Transport")
    tea = call("log_expense", amount="6.50", merchant="Bubble Tea Place", category="Dining Out")
    good = {
        "voice-direct": lambda: scripted(
            call("set_voice", preset="direct"), say("Done."), *memory, grab, say("12, Grab.")
        ),
        "voice-cheeky": lambda: scripted(
            call("set_voice", preset="cheeky"),
            say("Oh, can I."),
            *memory,
            tea,
            say("6.50 on bubble tea."),
        ),
        "voice-default-no-stock": lambda: scripted(
            say("Your salary's from Acme."),
            *memory,
            grab,
            say("Grab, 12."),
            *memory,
            say("Nobody."),
            *memory,
            say("Anytime."),
        ),
    }
    results = {
        r.case.id: r
        for r in await run_cases(engine, lambda case: good[case.id](), _only(*good), concurrency=3)
    }
    for case_id in good:
        assert results[case_id].passed, (case_id, results[case_id].failures, results[case_id].error)

    # An emoji, a long reply, or a stock phrase fails; so does never changing the voice.
    wrong = {
        "voice-direct": lambda: scripted(
            say("Okay ✅"),
            *memory,
            grab,
            say("Logged 12.00 at Grab for you, as you asked. " * 3 + "⚠️"),
        ),
        "voice-cheeky": lambda: scripted(say("Sure."), *memory, tea, say("Logged.")),
        "voice-default-no-stock": lambda: scripted(
            say("Fair enough."),
            *memory,
            grab,
            say("Absolutely, logged."),
            *memory,
            say("Nobody."),
            *memory,
            say("Noted!"),
        ),
    }
    failed = {
        r.case.id: r
        for r in await run_cases(
            engine,
            lambda case: wrong[case.id](),
            _only(*wrong),
            concurrency=3,
            first_telegram_id=920_000,
        )
    }
    direct = failed["voice-direct"].failures
    assert "reply longer than 80 characters" in direct
    assert any("reply matches" in f for f in direct)
    assert any(f.startswith("expected voice emoji none") for f in direct)
    assert any(
        f.startswith("expected voice preset cheeky") for f in failed["voice-cheeky"].failures
    )
    stock = failed["voice-default-no-stock"].failures
    assert len([f for f in stock if "reply matches" in f]) == 3


async def test_repeat_runs_each_case_in_every_round_as_a_fresh_user(engine: AsyncEngine) -> None:
    seen: list[str] = []

    def model_for(case: Case) -> BaseChatModel:
        seen.append(case.id)
        return (
            scripted(say("How much was lunch?"))
            if case.id == "ask-no-amount"
            else scripted(
                call("log_expense", amount="12", merchant="Grab", best_guess_category="Transport"),
                say("Logged 12.00 at Grab."),
            )
        )

    results = await run_cases(
        engine, model_for, _only("log-grab", "ask-no-amount"), concurrency=2, repeat=3
    )
    assert [(r.case.id, r.round_no) for r in results] == [
        (c, n) for n in (1, 2, 3) for c in ("log-grab", "ask-no-amount")
    ]
    assert len(seen) == 6
    assert all(r.passed for r in results), [(r.case.id, r.failures, r.error) for r in results]
