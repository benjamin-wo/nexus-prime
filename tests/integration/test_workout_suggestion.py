"""A workout for today: the agent picks exercises, code checks them, the user taps Start. Every
name and figure is made up."""

from datetime import timedelta
from typing import Any

import pytest

from nexus.agent.tools import HEALTH_OFF, ToolContext, ToolResult, build_tools, run_tool
from nexus.application import coach as coach_cases
from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application.users import get_user
from nexus.domain.coach import Experience, Focus, Place, TrainingProfile
from nexus.domain.gym import Equipment
from nexus.domain.ledger import UserId
from nexus.infra.exercises import load_catalogue
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only

pytestmark = pytest.mark.integration

ORIGIN = "https://nexus.example"
PULLDOWN = "Wide-Grip_Lat_Pulldown"
ROW = "Seated_Cable_Rows"


@pytest.fixture(autouse=True)
async def catalogue(uow: UowFactory) -> None:
    await gym_cases.sync_catalogue(uow(), load_catalogue())


def lift(exercise: str, sets: int = 3, reps: int = 10) -> dict[str, Any]:
    return {"exercise": exercise, "sets": sets, "reps": reps, "rest_seconds": 90}


BACK: dict[str, Any] = {
    "focus": "back",
    "exercises": [
        lift("lat pulldown"),  # several match: the best one is taken, nobody is asked
        lift(ROW),
        lift("pullups", 3, 6),
        lift("face pull", 3, 12),
    ],
}
GYM: dict[str, Any] = {**BACK, "minutes": 45, "place": "gym"}


async def suggest(
    uow: UowFactory, user: UserId, args: dict[str, Any], said: str = "back workout today"
) -> ToolResult:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW, message=said)
    return await run_tool(build_tools(lambda _: "")["suggest_workout"], ctx, args)


async def consenting(uow: UowFactory, user: UserId) -> UserId:
    await gym_cases.give_consent(uow(), user, now=NOW)
    return user


async def open_workout(uow: UowFactory, user: UserId):  # type: ignore[no-untyped-def]
    async with uow() as tx:
        return await tx.gym.open_workout(user)


async def test_a_suggestion_is_a_card_with_start_and_shuffle(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)  # no profile and no birth year: neither is needed
    result = await suggest(uow, alice, GYM)
    assert result.error is None and not result.wrote
    assert result.text.startswith("Back workout, about 2")  # code's estimate, in minutes
    assert "1. " in result.text and "3 × 10, rest 90 s" in result.text  # noqa: RUF001
    assert "3 × 6, rest 90 s" in result.text  # noqa: RUF001
    (row,) = result.buttons or []
    (start, label_a), (shuffle, label_b) = [(b[0], b[1]) for b in row]
    assert (start, shuffle) == ("Start", "Shuffle")
    suggestion_id = label_a.removeprefix("workout:start:")
    assert label_b == f"workout:shuffle:{suggestion_id}"
    assert await open_workout(uow, alice) is None  # nothing starts before the tap


async def test_start_begins_a_workout_with_the_planned_slots(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    result = await suggest(uow, alice, GYM)
    start = result.buttons[0][0][1]  # type: ignore[index]
    agent = build(uow, scripted())
    agent.origin = ORIGIN
    reply = only(await agent.press(alice, start))
    assert reply.text == "Started your back workout."
    assert [(b.label, b.data) for b in reply.buttons[0]] == [
        ("Open workout", f"url:{ORIGIN}/health/gym")
    ]
    workout = await open_workout(uow, alice)
    assert workout is not None and workout.planned_slots is not None
    assert len(workout.planned_slots) == 4
    assert [(s.sets, s.reps) for s in workout.planned_slots][2:] == [(3, 6), (3, 12)]
    assert workout.routine_id is None


async def test_no_web_origin_means_no_button(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    result = await suggest(uow, alice, GYM)
    reply = only(await build(uow, scripted()).press(alice, result.buttons[0][0][1]))  # type: ignore[index]
    assert reply.text == "Started your back workout." and reply.buttons == []


async def test_an_open_workout_is_said_not_replaced(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    first = await gym_cases.start_workout(uow(), alice, now=NOW)
    result = await suggest(uow, alice, GYM)
    agent = build(uow, scripted())
    agent.origin = ORIGIN
    reply = only(await agent.press(alice, result.buttons[0][0][1]))  # type: ignore[index]
    assert "already have a workout open" in reply.text
    assert reply.buttons[0][0].data == f"url:{ORIGIN}/health/gym"
    current = await open_workout(uow, alice)
    assert current is not None and current.id == first.id and current.planned_slots is None


async def test_time_and_place_are_remembered_the_first_time(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    home = {
        "focus": "arms",
        "minutes": 30,
        "place": "home",
        "equipment": ["dumbbell"],
        "exercises": [lift("One-Arm_Dumbbell_Row"), lift("pullups", 3, 6)],
    }
    assert (await suggest(uow, alice, home)).error is None
    saved = await coach_cases.training_profile(uow(), alice)
    assert saved is not None
    assert (saved.session_minutes, saved.place, saved.equipment) == (
        30,
        Place.HOME,
        (Equipment.DUMBBELL,),
    )
    # The next time neither is asked for or needed, and the dumbbells are still there.
    again = {"focus": "back", "exercises": home["exercises"]}
    assert (await suggest(uow, alice, again)).error is None
    # What the user said later doesn't overwrite what is saved.
    await suggest(uow, alice, {**GYM, "minutes": 60})
    kept = await coach_cases.training_profile(uow(), alice)
    assert kept is not None and (kept.session_minutes, kept.place) == (30, Place.HOME)
    assert kept.days_per_week is None  # a partial profile: a plan will still ask for the rest


async def test_the_missing_time_or_place_is_asked_for_once(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    both = await suggest(uow, alice, BACK)
    assert both.error == "InvalidInput" and "how long they have and whether" in both.text
    only_place = await suggest(uow, alice, {**BACK, "minutes": 40})
    assert "gym or at home" in only_place.text and "how long" not in only_place.text
    only_time = await suggest(uow, alice, {**BACK, "place": "gym"})
    assert "how long they have" in only_time.text and "gym or at home" not in only_time.text


async def test_home_without_equipment_is_body_weight_only(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    result = await suggest(uow, alice, {**BACK, "minutes": 45, "place": "home"})
    assert result.error == "InvalidInput"
    assert "needs cable" in result.text and "body weight only" in result.text


async def test_problems_are_listed_so_the_model_can_fix_them(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    bad = {
        **GYM,
        "minutes": 10,
        "exercises": [lift(ROW), lift(ROW), {"exercise": "zzzz", "sets": 3, "reps": 8}],
    }
    result = await suggest(uow, alice, bad)
    assert result.error == "InvalidInput" and result.text.startswith("Error:")
    assert "no exercise matches" in result.text
    fixable = {**bad, "exercises": bad["exercises"][:2]}
    text = (await suggest(uow, alice, fixable)).text
    assert "twice" in text and "would take about" in text


async def test_pain_is_referred_not_programmed(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    result = await suggest(uow, alice, GYM, said="my shoulder hurts, back workout?")
    assert result.error == "InvalidInput" and "doctor or physiotherapist" in result.text
    assert result.buttons is None


async def test_under_18_is_refused_but_no_birth_year_is_fine(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    await health_cases.save_profile(uow(), alice, birth_year=NOW.year - 15, now=NOW)
    result = await suggest(uow, alice, GYM)
    assert result.error == "InvalidInput" and "under 18" in result.text
    await health_cases.save_profile(uow(), alice, birth_year=1990, now=NOW)
    assert (await suggest(uow, alice, GYM)).error is None


async def test_health_off_is_said(uow: UowFactory, alice: UserId) -> None:
    result = await suggest(uow, alice, GYM)
    assert result.text == HEALTH_OFF and result.error == "ConsentRequired"
    agent = build(uow, scripted())
    await consenting(uow, alice)
    tapped = await suggest(uow, alice, GYM)
    await gym_cases.withdraw_consent(uow(), alice)
    reply = only(await agent.press(alice, tapped.buttons[0][0][1]))  # type: ignore[index]
    assert reply.text == HEALTH_OFF.removeprefix("Error: ")


async def test_a_suggestion_expires_after_a_day(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    result = await suggest(uow, alice, GYM)
    start = result.buttons[0][0][1]  # type: ignore[index]
    late = build(uow, scripted(), clock=lambda: NOW + timedelta(hours=25))
    reply = only(await late.press(alice, start))
    assert "expired" in reply.text and await open_workout(uow, alice) is None
    soon = build(uow, scripted(), clock=lambda: NOW + timedelta(hours=23))
    assert only(await soon.press(alice, start)).text == "Started your back workout."


async def test_someone_elses_suggestion_is_not_found(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await consenting(uow, alice)
    await consenting(uow, bob)
    result = await suggest(uow, alice, GYM)
    reply = only(await build(uow, scripted()).press(bob, result.buttons[0][0][1]))  # type: ignore[index]
    assert "expired" in reply.text and await open_workout(uow, bob) is None


async def test_shuffle_asks_the_model_for_a_different_one(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    result = await suggest(uow, alice, GYM)
    other = {"focus": "back", "exercises": [lift("Bent_Over_Barbell_Row"), lift(ROW)]}
    model = scripted(call("suggest_workout", **other), say("Here is another one."))
    agent = build(uow, model)
    replies = await agent.press(alice, result.buttons[0][1][1])  # type: ignore[index]
    asked = [str(m.content) for m in model.seen[0]]
    assert any("Give me a different back workout" in text for text in asked)
    assert replies[-1].text.startswith("Here is another one.")
    assert [b.label for b in replies[-1].buttons[0]] == ["Start", "Shuffle"]


async def test_a_plan_still_needs_all_five_inputs(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    await suggest(uow, alice, GYM)  # a partial profile now exists
    ctx = ToolContext(await get_user(uow(), alice), uow, NOW, message="draft me a plan")
    plan = {
        "routines": [{"name": "A", "slots": [{"exercise_query": "pullups", "sets": 3, "reps": 6}]}],
        "schedule": {"weekly": [{"day": "mon", "routine": "A"}]},
        "birth_year": 1990,
    }
    result = await run_tool(build_tools(lambda _: "")["draft_training_plan"], ctx, plan)
    assert result.error == "InvalidInput" and "days per week" in result.text
    assert "session length" not in result.text  # the 45 minutes were remembered


def test_the_profile_type_still_takes_five_inputs() -> None:
    full = TrainingProfile(3, 60, (), Experience.BEGINNER, Focus.GENERAL)
    assert full.missing() == [] and full.required()[0] == 3
