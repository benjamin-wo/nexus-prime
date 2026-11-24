"""The Gym coach's tools: a drafted plan is checked in code and saved only after a yes, and
adjustments are proposed from the log and applied only as the user accepts them. Every name
and figure is made up."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import coach as coach_cases
from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application import health_consent as consent_cases
from nexus.application.users import get_user
from nexus.domain.coach import Experience, Focus, TrainingProfile
from nexus.domain.gym import Equipment
from nexus.domain.gym_training import PlanKind, Slot
from nexus.domain.health import ConsentScope
from nexus.domain.ledger import UserId
from nexus.infra.exercises import load_catalogue
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only

pytestmark = pytest.mark.integration

BENCH = "Barbell_Bench_Press_-_Medium_Grip"
SQUAT = "Barbell_Squat"
PROFILE = TrainingProfile(
    3, 60, (Equipment.BARBELL, Equipment.DUMBBELL), Experience.BEGINNER, Focus.GENERAL
)


@pytest.fixture(autouse=True)
async def catalogue(uow: UowFactory) -> None:
    await gym_cases.sync_catalogue(uow(), load_catalogue())


async def run(
    uow: UowFactory, user: UserId, tool: str, args: dict[str, Any] | None = None, said: str = ""
) -> tuple[str, str | None]:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW, message=said)
    result = await run_tool(build_tools(lambda _: "")[tool], ctx, args or {})
    return result.text, result.error


async def ready(uow: UowFactory, user: UserId, *, birth_year: int | None = 1990) -> UserId:
    await gym_cases.give_consent(uow(), user, now=NOW)
    await consent_cases.grant(uow(), user, ConsentScope.AI_PROCESSING, now=NOW)
    await coach_cases.save_training_profile(uow(), user, PROFILE, now=NOW)
    if birth_year:
        await health_cases.save_profile(uow(), user, birth_year=birth_year, now=NOW)
    return user


def slot(query: str, sets: int = 3, reps: int = 8) -> dict[str, Any]:
    return {"exercise_query": query, "sets": sets, "reps": reps, "rest_seconds": 90}


PLAN: dict[str, Any] = {
    "routines": [
        {
            "name": "Full body",
            "slots": [
                slot("bench press"),
                slot("squat"),
                slot("pullups", 3, 6),
                slot("romanian deadlift"),
            ],
        }
    ],
    "schedule": {
        "weekly": [
            {"day": "mon", "routine": "Full body"},
            {"day": "wed", "routine": "Full body"},
            {"day": "fri", "routine": "Full body"},
        ]
    },
}


async def test_a_drafted_plan_is_saved_only_after_the_yes(uow: UowFactory, alice: UserId) -> None:
    await ready(uow, alice)
    model = scripted(call("draft_training_plan", **PLAN), say("Saved your plan."))
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "draft me a 3-day plan", "m1"))
    assert "Save this training plan?" in ask.text and "Full body (about" in ask.text
    assert "Schedule: Mon Full body, Wed Full body, Fri Full body" in ask.text
    assert await gym_cases.routines(uow(), alice) == []  # nothing saved before the yes
    done = only(await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True))
    assert "Saved your plan." in done.text
    (routine,) = await gym_cases.routines(uow(), alice)
    assert routine.name == "Full body" and len(routine.slots) == 4
    plan = await gym_cases.plan(uow(), alice)
    assert plan is not None and plan.kind is PlanKind.WEEKLY
    assert set(plan.weekly) == {0, 2, 4} and set(plan.weekly.values()) == {routine.id}


async def test_declining_the_card_saves_nothing(uow: UowFactory, alice: UserId) -> None:
    await ready(uow, alice)
    agent = build(uow, scripted(call("draft_training_plan", **PLAN), say("ok")))
    ask = only(await agent.handle_text(alice, "draft me a 3-day plan", "m1"))
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], False)
    assert await gym_cases.routines(uow(), alice) == []
    assert await gym_cases.plan(uow(), alice) is None


async def test_an_invalid_plan_lists_every_problem_and_saves_nothing(
    uow: UowFactory, alice: UserId
) -> None:
    await ready(uow, alice)
    bad: dict[str, Any] = {
        "routines": [
            {
                "name": "A",
                "slots": [
                    slot("leg press"),  # a machine the user doesn't have
                    slot("bench press", 3, 8),
                    slot("bench press", 3, 8),  # twice
                    {"exercise_query": "zzzz not an exercise", "sets": 3, "reps": 8},
                ],
            }
        ],
        "schedule": {"weekly": [{"day": "mon", "routine": "A"}]},
    }
    text, error = await run(uow, alice, "draft_training_plan", bad)
    assert error == "InvalidInput" and text.startswith("Error:")
    assert "no exercise matches" in text
    assert await gym_cases.routines(uow(), alice) == []
    fixable = {**bad, "routines": [{"name": "A", "slots": bad["routines"][0]["slots"][:3]}]}
    text, _ = await run(uow, alice, "draft_training_plan", fixable)
    assert "needs machine" in text and "twice" in text


async def test_unclear_and_missing_inputs_are_asked_for(uow: UowFactory, alice: UserId) -> None:
    await gym_cases.give_consent(uow(), alice, now=NOW)
    await health_cases.save_profile(uow(), alice, birth_year=1990, now=NOW)
    text, error = await run(uow, alice, "draft_training_plan", PLAN)  # no training profile
    assert error == "InvalidInput" and "ask the user for: days per week" in text
    said = {**PLAN, "days_per_week": 3, "session_minutes": 60, "equipment": ["barbell"]}
    text, _ = await run(uow, alice, "draft_training_plan", said)
    assert "experience" in text and "days per week" not in text


async def test_under_18_and_unknown_age_get_no_plan(uow: UowFactory, alice: UserId) -> None:
    await ready(uow, alice, birth_year=NOW.year - 16)
    text, error = await run(uow, alice, "draft_training_plan", PLAN)
    assert error == "InvalidInput" and "may be under 18" in text and "qualified coach" in text
    agent = build(uow, scripted(call("draft_training_plan", **PLAN), say("I can't draft one.")))
    reply = only(await agent.handle_text(alice, "draft me a plan", "m1"))
    assert reply.text == "I can't draft one." and not reply.buttons  # no card was offered
    assert await gym_cases.routines(uow(), alice) == []


async def test_unknown_age_is_asked_and_a_stated_adult_year_is_enough(
    uow: UowFactory, alice: UserId
) -> None:
    await ready(uow, alice, birth_year=None)
    text, _ = await run(uow, alice, "draft_training_plan", PLAN)
    assert "ask the user for their birth year" in text
    text, error = await run(
        uow, alice, "draft_training_plan", {**PLAN, "birth_year": NOW.year - 15}
    )
    assert "may be under 18" in text
    text, error = await run(uow, alice, "draft_training_plan", {**PLAN, "birth_year": 1990})
    assert error is None and text.startswith("Saved 1 routines")


async def test_pain_or_injury_in_the_message_refuses_any_programming(
    uow: UowFactory, alice: UserId
) -> None:
    await ready(uow, alice)
    for said in ("my knee hurts, draft me a plan", "I tore my hamstring, can you plan my week"):
        text, error = await run(uow, alice, "draft_training_plan", PLAN, said)
        assert error == "InvalidInput" and "doctor or physiotherapist" in text
    assert await gym_cases.routines(uow(), alice) == []
    agent = build(uow, scripted(call("draft_training_plan", **PLAN), say("Please see a physio.")))
    reply = only(await agent.handle_text(alice, "ok my shoulder is sore, draft a push plan", "m1"))
    assert not reply.buttons  # the card is refused too, not shown and then refused


async def test_without_consent_it_says_health_is_off(uow: UowFactory, alice: UserId) -> None:
    text, error = await run(uow, alice, "draft_training_plan", PLAN)
    assert error == "ConsentRequired" and text.startswith("Error: Health is off")


async def log_session(
    uow: UowFactory, user: UserId, exercise: str, days_ago: int, reps: list[int], weight: str
) -> None:
    at = NOW - timedelta(days=days_ago)
    workout = await gym_cases.start_workout(uow(), user, now=at)
    for r in reps:
        await gym_cases.log_set(
            uow(), user, workout.id, exercise_id=exercise, reps=r,
            weight=Decimal(weight), rpe=Decimal(7), now=at,
        )  # fmt: skip
    await gym_cases.finish_workout(uow(), user, workout.id, now=at + timedelta(minutes=50))


async def plan_with_history(uow: UowFactory, user: UserId) -> None:
    await ready(uow, user)
    push = await gym_cases.save_routine(
        uow(), user, name="Push", slots=[Slot(BENCH, 3, 5, None)], now=NOW
    )
    legs = await gym_cases.save_routine(
        uow(), user, name="Legs", slots=[Slot(SQUAT, 3, 5, None)], now=NOW
    )
    await gym_cases.set_plan(uow(), user, PlanKind.WEEKLY, weekly={0: push.id, 3: legs.id}, now=NOW)
    for days in (14, 7):
        await log_session(uow, user, BENCH, days, [5, 5, 5], "80")
        await log_session(uow, user, SQUAT, days, [5, 5, 5], "100")


async def test_adjustments_are_proposed_from_the_log_and_change_nothing(
    uow: UowFactory, alice: UserId
) -> None:
    await plan_with_history(uow, alice)
    before = await gym_cases.routines(uow(), alice)
    text, error = await run(uow, alice, "suggest_adjustments")
    assert error is None
    assert "1. Barbell Bench Press - Medium Grip" in text and "82.5 kg (from 80 kg)" in text
    assert "2. Barbell Squat" in text and "105 kg (from 100 kg)" in text  # lower body: +5
    assert "suggestions only" in text
    assert await gym_cases.routines(uow(), alice) == before


async def test_only_the_accepted_adjustments_are_applied_after_a_yes(
    uow: UowFactory, alice: UserId
) -> None:
    await plan_with_history(uow, alice)
    agent = build(uow, scripted(call("apply_adjustments", accept=[1]), say("Done.")))
    ask = only(await agent.handle_text(alice, "yes, the first one", "m1"))
    assert "82.5 kg" in ask.text and "105 kg" not in ask.text
    unchanged = {r.name: r.slots for r in await gym_cases.routines(uow(), alice)}
    assert all(s.note is None for slots in unchanged.values() for s in slots)  # not before the yes
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    notes = {r.name: r.slots[0].note for r in await gym_cases.routines(uow(), alice)}
    assert notes == {"Push": "Next time: 82.5 kg (last: 80 kg)", "Legs": None}


async def test_a_wrong_number_or_no_plan_is_an_error(uow: UowFactory, alice: UserId) -> None:
    await ready(uow, alice)
    text, _ = await run(uow, alice, "suggest_adjustments")
    assert "no training plan yet" in text
    await plan_with_history(uow, alice)
    text, error = await run(uow, alice, "apply_adjustments", {"accept": [7]})
    assert error == "InvalidInput" and "there is no adjustment 7" in text
    text, error = await run(uow, alice, "apply_adjustments", {"accept": []})
    assert error == "InvalidInput"


async def test_a_deload_halves_the_sets_and_a_second_apply_changes_nothing_more(
    uow: UowFactory, alice: UserId
) -> None:
    await ready(uow, alice)
    routine = await gym_cases.save_routine(
        uow(), alice, name="Push", slots=[Slot(BENCH, 4, 5, None)], now=NOW
    )
    await gym_cases.set_plan(uow(), alice, PlanKind.WEEKLY, weekly={0: routine.id}, now=NOW)
    for weeks in range(1, 7):  # a session in each of the six finished weeks
        await log_session(uow, alice, BENCH, 7 * weeks, [5, 5, 5, 5], "60")
    text, _ = await run(uow, alice, "suggest_adjustments")
    assert "1. 6 training weeks in a row without a lighter one" in text
    _, error = await run(uow, alice, "apply_adjustments", {"accept": [1]})
    assert error is None
    (halved,) = await gym_cases.routines(uow(), alice)
    assert halved.slots[0].sets == 2 and halved.slots[0].note == "Deload week: usual 4 sets"
    assert "1. " not in (await run(uow, alice, "suggest_adjustments"))[0]
    (again,) = await gym_cases.routines(uow(), alice)
    assert again.slots == halved.slots


async def test_adjustments_need_ai_processing(uow: UowFactory, alice: UserId) -> None:
    await plan_with_history(uow, alice)
    await consent_cases.withdraw(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    for tool, args in (("suggest_adjustments", {}), ("apply_adjustments", {"accept": [1]})):
        text, error = await run(uow, alice, tool, args)
        assert error == "ConsentRequired" and "82.5" not in text


async def test_the_training_profile_round_trips_and_needs_consent(
    uow: UowFactory, alice: UserId
) -> None:
    from nexus.domain.errors import ConsentRequired

    with pytest.raises(ConsentRequired):
        await coach_cases.save_training_profile(uow(), alice, PROFILE, now=NOW)
    await gym_cases.give_consent(uow(), alice, now=NOW)
    assert await coach_cases.training_profile(uow(), alice) is None
    await coach_cases.save_training_profile(uow(), alice, PROFILE, now=NOW)
    assert await coach_cases.training_profile(uow(), alice) == PROFILE
