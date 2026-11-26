"""Prime's gym tools: logging by chat behind a confirm card, and the answers. Every name and
figure is made up. Figures in a tool's text come from the application layer."""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import gym as gym_cases
from nexus.application.users import get_user
from nexus.domain.gym_training import PlanKind, Slot
from nexus.domain.ledger import UserId
from nexus.infra.exercises import load_catalogue
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only

pytestmark = pytest.mark.integration

BENCH = "Barbell_Bench_Press_-_Medium_Grip"
SQUAT = "Barbell_Squat"


@pytest.fixture(autouse=True)
async def catalogue(uow: UowFactory) -> None:
    await gym_cases.sync_catalogue(uow(), load_catalogue())


async def run(uow: UowFactory, user: UserId, tool: str, **args: Any) -> tuple[str, str | None]:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW)
    result = await run_tool(build_tools(lambda _: "")[tool], ctx, args)
    return result.text, result.error


async def agree(uow: UowFactory, user: UserId) -> UserId:
    await gym_cases.give_consent(uow(), user, now=NOW)
    return user


async def lifted(
    uow: UowFactory, user: UserId, exercise: str, reps: int, weight: str, *, days_ago: int = 7
) -> None:
    from decimal import Decimal

    at = NOW - timedelta(days=days_ago)
    workout = await gym_cases.start_workout(uow(), user, now=at)
    for _ in range(3):
        await gym_cases.log_set(
            uow(), user, workout.id, exercise_id=exercise, reps=reps, weight=Decimal(weight), now=at
        )
    await gym_cases.finish_workout(uow(), user, workout.id, now=at + timedelta(minutes=50))


async def test_without_consent_a_write_says_how_to_turn_health_on(
    uow: UowFactory, alice: UserId
) -> None:
    for tool, args in (
        ("log_sets", {"exercise": "bench", "entry": "3x5 at 80"}),
        ("finish_workout", {}),
    ):
        text, error = await run(uow, alice, tool, **args)
        assert error == "ConsentRequired"
        assert text.startswith("Error: Health is off") and "Health section of the app" in text
    assert await gym_cases.workouts(uow(), alice) == []


async def test_a_chat_log_asks_first_then_saves_and_shows_health(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    model = scripted(
        call("log_sets", exercise="bench", sets=[{"reps": 5, "weight": "80", "count": 3}]),
        say("Logged."),
    )
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "bench 3x5 at 80", "m1"))
    assert ask.text == "Log Barbell Bench Press - Medium Grip: 3 sets of 5 at 80 kg?"
    assert await gym_cases.workouts(uow(), alice) == []  # nothing saved before the yes
    done = only(await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True))
    assert "Logged." in done.text
    (found,) = await gym_cases.workouts(uow(), alice)
    assert [(s.exercise_id, s.reps, str(s.weight)) for s in found.sets] == [(BENCH, 5, "80.00")] * 3
    assert (await get_user(uow(), alice)).show_health is True


async def test_logging_without_consent_asks_nothing(uow: UowFactory, alice: UserId) -> None:
    model = scripted(call("log_sets", exercise="bench", entry="3x5 at 80"), say("Health is off."))
    reply = only(await build(uow, model).handle_text(alice, "bench 3x5 at 80", "m1"))
    assert reply.text == "Health is off."
    assert await gym_cases.workouts(uow(), alice) == []


async def test_sets_append_to_the_open_workout_and_can_be_undone(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "log_sets", exercise="squat", entry="2x5 at 100kg RPE 8")
    assert error is None and "Logged Barbell Squat: 2 sets of 5 at 100 kg (RPE 8)." in text
    assert "2 working sets and 1,000 kg volume so far" in text
    text, _ = await run(uow, alice, "log_sets", exercise=BENCH, sets=[{"seconds": 30}])
    assert "3 working sets" in text
    assert len(await gym_cases.workouts(uow(), alice)) == 1  # one workout, not two
    text, _ = await run(uow, alice, "undo_last_set")
    assert text == "Removed the last set (Barbell Bench Press - Medium Grip: 1 set of 30 s)."
    (found,) = await gym_cases.workouts(uow(), alice)
    assert len(found.sets) == 2


async def test_bad_sets_save_nothing(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    text, error = await run(
        uow, alice, "log_sets", exercise="bench", sets=[{"reps": 5}, {"reps": 5, "rpe": "11"}]
    )
    assert error == "InvalidInput" and text.startswith("Error:")
    assert await gym_cases.workouts(uow(), alice) == []
    text, error = await run(uow, alice, "log_sets", exercise="bench")
    assert error == "InvalidInput" and "no sets" in text


async def test_an_unclear_name_asks_which_exercise(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "last_time", exercise="curl")
    assert error == "InvalidInput" and "several exercises" in text and "Ask the user" in text
    text, error = await run(uow, alice, "log_sets", exercise="curl", entry="3x10 at 20")
    assert error == "InvalidInput" and "several exercises" in text
    assert await gym_cases.workouts(uow(), alice) == []
    text, error = await run(uow, alice, "last_time", exercise="zzzz nothing")
    assert error == "NotFound"


async def test_finishing_reports_the_summary_from_code(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    await lifted(uow, alice, BENCH, 5, "70")
    await run(uow, alice, "log_sets", exercise="bench", entry="3x5 at 75")
    text, error = await run(uow, alice, "finish_workout")
    assert error is None
    assert "3 working sets, 1,125 kg volume" in text
    assert "New records: Barbell Bench Press - Medium Grip (heaviest weight" in text
    text, error = await run(uow, alice, "finish_workout")
    assert error == "NotFound" and "no workout in progress" in text


async def test_the_read_tools_answer_with_figures_from_the_log(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    assert (await run(uow, alice, "personal_records", exercise="bench"))[0].startswith(
        "No working sets of Barbell Bench Press"
    )
    assert (await run(uow, alice, "weekly_volume"))[0].startswith("No working sets logged")
    await lifted(uow, alice, SQUAT, 5, "100", days_ago=7)
    await lifted(uow, alice, BENCH, 5, "80", days_ago=3)

    text, _ = await run(uow, alice, "last_time", exercise="squats")
    assert text == "Last time, Mon 21 Sep, Barbell Squat: 3 sets of 5 at 100 kg."
    text, _ = await run(uow, alice, "personal_records", exercise="bench")
    assert "heaviest 80 kg for 5 reps (Fri 25 Sep)" in text
    assert "best estimated one-rep max 93.3 kg" in text and "Epley" in text
    text, _ = await run(uow, alice, "personal_records")
    assert "Barbell Squat" in text and "Barbell Bench Press" in text

    text, _ = await run(uow, alice, "workout_history", range="last 8 days")
    assert "2 workouts, 6 working sets, 2,700 kg volume" in text and "Barbell Squat" in text
    text, _ = await run(uow, alice, "workout_history", range="yesterday")
    assert text.startswith("No workouts from")
    text, error = await run(uow, alice, "workout_history", range="soon")
    assert error == "InvalidInput"

    text, _ = await run(uow, alice, "weekly_volume", week="last week")
    assert "• quadriceps: 1,500 kg, 3 sets" in text
    assert "• chest: 1,200 kg, 3 sets" in text
    text, _ = await run(uow, alice, "weekly_volume")
    assert text.startswith("No working sets logged in the week of Mon 28 Sep")


async def test_todays_workout_from_the_plan(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    assert "No plan" in (await run(uow, alice, "todays_workout"))[0]
    pull = await gym_cases.save_routine(
        uow(), alice, name="Push", slots=[Slot(BENCH, 3, 8, None), Slot("Plank", 2, None, 30, 45)],
        now=NOW,
    )  # fmt: skip
    day = NOW.astimezone(NOW.tzinfo).weekday()
    other: dict[int, UUID] = {(day + 1) % 7: pull.id}
    await gym_cases.set_plan(uow(), alice, PlanKind.WEEKLY, weekly=other, now=NOW)
    assert "Rest day" in (await run(uow, alice, "todays_workout"))[0]
    await gym_cases.set_plan(uow(), alice, PlanKind.WEEKLY, weekly={day: pull.id}, now=NOW)
    text, _ = await run(uow, alice, "todays_workout")
    assert "Push" in text
    assert "1. Barbell Bench Press - Medium Grip: 3 x 8, rest 90 s" in text
    assert "2. Plank: 2 x 30 s, rest 45 s" in text


async def test_finding_exercises(uow: UowFactory, alice: UserId) -> None:
    text, _ = await run(uow, alice, "find_exercise", query="bench")
    assert text.splitlines()[1].startswith(f"• Barbell Bench Press - Medium Grip [{BENCH}]")
    text, error = await run(uow, alice, "find_exercise", muscle="wings")
    assert error == "InvalidInput" and "chest" in text
