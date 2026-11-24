"""The Gym coach's rules: plan validation and progression suggestions (pure, no database).
Every name and figure is made up."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from nexus.domain import coach
from nexus.domain.coach import (
    Experience,
    Focus,
    PlannedRoutine,
    PlannedSchedule,
    PlannedSlot,
    ProposalKind,
    SlotRef,
    TrainingProfile,
)
from nexus.domain.gym import Equipment, Exercise
from nexus.domain.gym_training import SetEntry, SetKind, Slot, WeightUnit, week_start
from nexus.domain.ledger import UserId
from nexus.infra.exercises import load_catalogue

CATALOGUE = {e.id: e for e in load_catalogue()}
BENCH = CATALOGUE["Barbell_Bench_Press_-_Medium_Grip"]
SQUAT = CATALOGUE["Barbell_Squat"]
CURL = CATALOGUE["Dumbbell_Bicep_Curl"]
PULLUP = CATALOGUE["Pullups"]
RDL = CATALOGUE["Romanian_Deadlift"]
PRESS = CATALOGUE["Dumbbell_Shoulder_Press"]
LEG_PRESS = CATALOGUE["Leg_Press"]
PLANK = CATALOGUE["Plank"]

PROFILE = TrainingProfile(
    3, 60, (Equipment.BARBELL, Equipment.DUMBBELL), Experience.BEGINNER, Focus.GENERAL
)
NOW = datetime(2026, 11, 24, 14, 0, tzinfo=UTC)  # a Tuesday


def slot(
    e: Exercise, sets: int = 3, reps: int | None = 8, rest: int = 90, secs: int | None = None
) -> PlannedSlot:
    return PlannedSlot(e, sets, None if secs else reps, secs, rest)


def routine(name: str, *slots: PlannedSlot) -> PlannedRoutine:
    return PlannedRoutine(name, tuple(slots))


FULL_BODY = routine("Full body", slot(BENCH), slot(SQUAT), slot(PULLUP, reps=6), slot(RDL))
WEEKLY = PlannedSchedule(weekly=((0, "Full body"), (2, "Full body"), (4, "Full body")))


def test_a_sensible_plan_has_no_problems() -> None:
    assert coach.validate_plan([FULL_BODY], WEEKLY, PROFILE) == []


@pytest.mark.parametrize(
    ("label", "routines", "schedule", "profile", "expected"),
    [
        (
            "equipment the user lacks",
            [routine("A", slot(LEG_PRESS, 4), slot(BENCH, 4))],
            PlannedSchedule(weekly=((0, "A"), (2, "A"))),
            PROFILE,
            "needs machine",
        ),
        (
            "body weight never needs listing",
            [routine("A", slot(PULLUP, 4, 6), slot(PLANK, 3, secs=40))],
            PlannedSchedule(weekly=((0, "A"), (2, "A"))),
            replace(PROFILE, equipment=()),
            None,
        ),
        (
            "an exercise twice in a routine",
            [routine("A", slot(BENCH), slot(BENCH))],
            PlannedSchedule(weekly=((0, "A"),)),
            PROFILE,
            "has Barbell Bench Press - Medium Grip twice",
        ),
        (
            "sets over the slot bound",
            [routine("A", slot(BENCH, 21))],
            PlannedSchedule(weekly=((0, "A"),)),
            PROFILE,
            "sets must be a whole number from 1 to 20",
        ),
        (
            "reps over the slot bound",
            [routine("A", slot(BENCH, 3, 101))],
            PlannedSchedule(weekly=((0, "A"),)),
            PROFILE,
            "reps must be a whole number from 1 to 100",
        ),
        (
            "rest over the slot bound",
            [routine("A", slot(BENCH, 3, 5, rest=901))],
            PlannedSchedule(weekly=((0, "A"),)),
            PROFILE,
            "rest must be a whole number from 0 to 900",
        ),
        (
            "too many weekly sets for one muscle",
            [routine("A", slot(BENCH, 9), slot(PRESS, 9))],
            PlannedSchedule(weekly=((0, "A"), (2, "A"), (4, "A"))),
            PROFILE,
            "chest would get 27 sets a week, over the 25 allowed",
        ),
        (
            "too few weekly sets for a trained muscle",
            [routine("A", slot(BENCH, 3), slot(CURL, 3))],
            PlannedSchedule(weekly=((0, "A"),)),
            PROFILE,
            "biceps would get only 3 sets a week",
        ),
        (
            "more days than the user trains",
            [FULL_BODY],
            PlannedSchedule(
                weekly=((0, "Full body"), (1, "Full body"), (3, "Full body"), (5, "Full body"))
            ),
            PROFILE,
            "trains on 4 days, but the user trains 3 days a week",
        ),
        (
            "a routine left off the schedule",
            [FULL_BODY, routine("B", slot(PRESS, 4))],
            WEEKLY,
            PROFILE,
            "routine 'B' isn't in the schedule",
        ),
        (
            "the schedule names an unknown routine",
            [FULL_BODY],
            PlannedSchedule(weekly=((0, "Full body"), (2, "Legs"))),
            PROFILE,
            "names 'Legs', which isn't one of the routines",
        ),
        (
            "weekdays and a rotation together",
            [FULL_BODY],
            PlannedSchedule(weekly=((0, "Full body"),), rotation=("Full body",)),
            PROFILE,
            "either days of the week or a rotation",
        ),
        (
            "two routines with one name",
            [routine("A", slot(BENCH, 4)), routine("a", slot(SQUAT, 4))],
            PlannedSchedule(rotation=("A", "a")),
            PROFILE,
            "two routines are called 'a'",
        ),
        ("no routines", [], PlannedSchedule(), PROFILE, "no routines"),
    ],
)
def test_validate_plan(label, routines, schedule, profile, expected) -> None:  # type: ignore[no-untyped-def]
    problems = coach.validate_plan(routines, schedule, profile)
    if expected is None:
        assert problems == [], label
    else:
        assert any(expected in p for p in problems), (label, problems)


def test_session_length_allows_fifteen_percent_over() -> None:
    # 10 sets of 10 reps with 90 s rest: 10 x (40 + 90) = 1300 s = 22 min.
    heavy = routine("A", slot(BENCH, 5, 10), slot(SQUAT, 5, 10))
    assert coach.session_minutes(heavy) == 22
    schedule = PlannedSchedule(weekly=((0, "A"), (2, "A")))
    assert (
        coach.validate_plan([heavy], schedule, replace(PROFILE, session_minutes=20)) == []
    )  # 23 allowed
    over = coach.validate_plan(
        [heavy], schedule, replace(PROFILE, session_minutes=19)
    )  # 21 allowed
    assert any("about 22 minutes, over the 21 minutes allowed" in p for p in over)


def test_a_rotation_counts_sessions_from_days_per_week() -> None:
    a = routine("A", slot(BENCH, 4), slot(PULLUP, 4, 6))
    b = routine("B", slot(SQUAT, 4), slot(RDL, 4))
    totals, direct = coach.weekly_sets([a, b], PlannedSchedule(rotation=("A", "B")), PROFILE)
    # 3 sessions a week over 2 routines: 1.5 of each, so 4 x 1.5 = 6 sets of chest.
    assert float(totals[BENCH.primary[0]]) == 6.0
    assert BENCH.primary[0] in direct


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my knee hurts when I squat", True),
        ("I tore my hamstring last month", True),
        ("recovering from shoulder surgery", True),
        ("my back is sore and stiff", True),
        ("I have a sprained ankle", True),
        ("draft me a 3-day plan", False),
        ("I want to build muscle and get stronger", False),
        ("bench 3x5 at 80", False),
    ],
)
def test_mentions_pain(text: str, expected: bool) -> None:
    assert coach.mentions_pain(text) is expected


def test_training_profile_bounds_and_round_trip() -> None:
    assert TrainingProfile.from_dict(PROFILE.as_dict()) == PROFILE
    for days, minutes in ((0, 60), (8, 60), (3, 5), (3, 300)):
        with pytest.raises(Exception, match="must be a whole number"):
            TrainingProfile(days, minutes, (), Experience.BEGINNER, Focus.GENERAL)
    with pytest.raises(Exception, match="bad training profile"):
        TrainingProfile.from_dict({"days_per_week": 3})


# --- progression ----------------------------------------------------------------------------

USER = UserId(uuid4())
ROUTINE_ID = UUID(int=1)


def refs(*pairs: tuple[Exercise, int, int]) -> list[SlotRef]:
    return [
        SlotRef(ROUTINE_ID, "Full body", i, Slot(e.id, sets, reps, None, 90))
        for i, (e, sets, reps) in enumerate(pairs)
    ]


def session(
    exercise: Exercise,
    days_ago: int,
    reps: list[int],
    weight: str | None = "80",
    rpe: str | None = "7",
) -> list[SetEntry]:
    workout = uuid4()
    at = NOW - timedelta(days=days_ago)
    return [
        SetEntry(
            uuid4(),
            workout,
            exercise.id,
            i + 1,
            SetKind.WORKING,
            r,
            None if weight is None else Decimal(weight),
            WeightUnit.KG,
            None,
            Decimal(rpe) if rpe else None,
            at,
        )
        for i, r in enumerate(reps)
    ]


def propose(plan: list[SlotRef], history: dict[str, list[SetEntry]]):  # type: ignore[no-untyped-def]
    return coach.suggest_progression(plan, history, CATALOGUE, now=NOW)


def kinds(found) -> list[ProposalKind]:  # type: ignore[no-untyped-def]
    return [p.kind for p in found]


@pytest.mark.parametrize(
    ("label", "exercise", "sessions", "kind", "to_kg"),
    [
        (
            "two good upper-body sessions: +2.5",
            BENCH,
            [(14, [5, 5, 5], "80", "8"), (7, [5, 6, 5], "80", "7")],
            ProposalKind.INCREASE,
            "82.5",
        ),
        (
            "two good lower-body sessions: +5",
            SQUAT,
            [(14, [5, 5, 5], "100", "7"), (7, [5, 5, 5], "100", None)],
            ProposalKind.INCREASE,
            "105",
        ),
        (
            "the target is reached but at RPE 9: nothing",
            BENCH,
            [(14, [5, 5, 5], "80", "7"), (7, [5, 5, 5], "80", "9")],
            None,
            None,
        ),
        (
            "missed twice running: hold",
            BENCH,
            [(14, [5, 5, 4], "80", "9"), (7, [5, 4, 4], "80", "9")],
            ProposalKind.HOLD,
            None,
        ),
        (
            "a set short counts as missed",
            BENCH,
            [(14, [5, 5], "80", "7"), (7, [5, 5], "80", "7")],
            ProposalKind.HOLD,
            None,
        ),
        (
            "missed three running: minus 10 percent, to the nearest half kilo",
            BENCH,
            [(21, [4, 4, 4], "80", "9"), (14, [4, 4, 3], "80", "9"), (7, [3, 3, 3], "80", "10")],
            ProposalKind.DECREASE,
            "72",
        ),
        (
            "one session is not enough",
            BENCH,
            [(7, [5, 5, 5], "80", "7")],
            None,
            None,
        ),
        (
            "sessions older than four weeks don't count",
            BENCH,
            [(40, [5, 5, 5], "80", "7"), (35, [5, 5, 5], "80", "7")],
            None,
            None,
        ),
        (
            "a miss then a hit: nothing",
            BENCH,
            [(14, [4, 4, 4], "80", "9"), (7, [5, 5, 5], "80", "7")],
            None,
            None,
        ),
    ],
)
def test_progression_rules(label, exercise, sessions, kind, to_kg) -> None:  # type: ignore[no-untyped-def]
    history = {
        exercise.id: [s for d, reps, w, rpe in sessions for s in session(exercise, d, reps, w, rpe)]
    }
    found = propose(refs((exercise, 3, 5)), history)
    if kind is None:
        assert found == [], label
        return
    assert kinds(found) == [kind], label
    if to_kg is not None:
        assert found[0].to_kg == Decimal(to_kg), label


def test_warm_up_sets_never_count() -> None:
    warm = [replace(s, kind=SetKind.WARMUP, reps=1) for s in session(BENCH, 7, [1, 1])]
    good = session(BENCH, 7, [5, 5, 5])
    older = session(BENCH, 14, [5, 5, 5])
    found = propose(refs((BENCH, 3, 5)), {BENCH.id: [*warm, *good, *older]})
    assert kinds(found) == [ProposalKind.INCREASE]


def test_a_bodyweight_slot_has_no_weight_to_add_to() -> None:
    history = {
        PULLUP.id: [*session(PULLUP, 14, [6, 6, 6], None), *session(PULLUP, 7, [6, 6, 6], None)]
    }
    assert propose(refs((PULLUP, 3, 6)), history) == []


def test_the_reason_is_built_from_the_numbers() -> None:
    history = {BENCH.id: [*session(BENCH, 14, [5, 5, 5]), *session(BENCH, 7, [5, 5, 5])]}
    (p,) = propose(refs((BENCH, 3, 5)), history)
    assert p.reason == (
        "Barbell Bench Press - Medium Grip: every target rep was reached at RPE 8 or easier in the "
        "last 2 sessions, so add 2.5 kg: 82.5 kg (from 80 kg)"
    )
    assert coach.describe_proposals([p]).startswith("1. Barbell Bench Press")


def weeks_of_training(weeks: list[int], exercise: Exercise = BENCH) -> list[SetEntry]:
    """Sets per finished week, the latest week last: Monday 16 November is the week before NOW."""
    sets: list[SetEntry] = []
    for i, n in enumerate(reversed(weeks)):  # i = weeks back from last week
        day = datetime(2026, 11, 16, 9, 0, tzinfo=UTC) - timedelta(days=7 * i)
        for _ in range(n):
            sets += session(exercise, 0, [5], "60", "7")
            sets[-1] = replace(sets[-1], done_at=day)
    return sets


def test_six_weeks_without_a_lighter_one_suggests_a_deload() -> None:
    history = {BENCH.id: weeks_of_training([9, 9, 9, 9, 9, 9])}
    (p,) = propose(refs((BENCH, 3, 5), (SQUAT, 3, 5)), history)
    assert p.kind is ProposalKind.DELOAD and "6 training weeks in a row" in p.reason


def test_five_weeks_or_a_light_week_in_between_is_not_enough() -> None:
    five = propose(refs((BENCH, 3, 5)), {BENCH.id: weeks_of_training([9, 9, 9, 9, 9])})
    assert ProposalKind.DELOAD not in kinds(five)
    broken = weeks_of_training([9, 9, 9, 5, 9, 9, 9, 9])  # the 5 is under 60% of 9
    assert coach.weeks_without_deload(coach._week_counts(broken, UTC), week_start(NOW.date())) == 4
    assert ProposalKind.DELOAD not in kinds(propose(refs((BENCH, 3, 5)), {BENCH.id: broken}))


def test_a_falling_estimated_max_on_three_exercises_suggests_a_deload() -> None:
    plan = refs((BENCH, 3, 5), (SQUAT, 3, 5), (PRESS, 3, 5))
    history = {
        e.id: [
            s
            for days, weight in ((21, "100"), (14, "95"), (7, "90"))
            for s in session(e, days, [5, 5, 5], weight, "7")
        ]
        for e in (BENCH, SQUAT, PRESS)
    }
    (p,) = propose(plan, history)
    assert p.kind is ProposalKind.DELOAD and "on 3 exercises" in p.reason
    two = {k: v for k, v in history.items() if k != PRESS.id}
    assert ProposalKind.DELOAD not in kinds(propose(plan, two))


def test_deload_halves_sets_and_remembers_the_usual_ones() -> None:
    s = Slot(BENCH.id, 5, 5, None, 120)
    light = coach.deloaded_slot(s)
    assert (light.sets, light.note) == (3, "Deload week: usual 5 sets")
    assert coach.deloaded_slot(light) == light  # applying it twice changes nothing more
    assert coach.deloaded_slot(Slot(BENCH.id, 1, 5, None, 60)).sets == 1
    assert coach.restored_slot(light) == s


def test_after_a_deload_the_usual_sets_are_proposed_back() -> None:
    plan = [replace(r, slot=coach.deloaded_slot(r.slot)) for r in refs((BENCH, 4, 5))]
    light_week = weeks_of_training([8, 8, 8, 3])
    (p,) = coach.suggest_progression(plan, {BENCH.id: light_week}, CATALOGUE, now=NOW)
    assert p.kind is ProposalKind.RESTORE
    still = weeks_of_training([8, 8, 8, 8])
    assert coach.suggest_progression(plan, {BENCH.id: still}, CATALOGUE, now=NOW) == []


def test_the_card_lists_routines_schedule_and_weekly_sets() -> None:
    card = coach.draft_card([FULL_BODY], WEEKLY, PROFILE)
    assert "Full body (about" in card and "- Barbell Squat: 3 x 8, rest 90 s" in card
    assert "Schedule: Mon Full body, Wed Full body, Fri Full body" in card
    assert "chest 9" in card and "Built for 3 days a week, 60-minute sessions" in card
