"""Gym training rules: slots, plans, e1RM, records, volume, rotation and prefill. Pure; every
name and figure is made up."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.gym import Category, Exercise, Level, Muscle
from nexus.domain.gym_training import (
    LB_IN_KG,
    PlanKind,
    PrKind,
    Routine,
    SetEntry,
    SetKind,
    Slot,
    TrainingPlan,
    WeightUnit,
    Workout,
    best_set,
    clean_weight,
    detect_prs,
    epley_1rm,
    last_time,
    next_in_rotation,
    progress,
    records_of_set,
    summarise,
    to_kg,
    todays_routine,
    volume_by_muscle,
    week_start,
)
from nexus.domain.ledger import UserId

USER = UserId(uuid4())
T0 = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)  # a Monday
D = Decimal


def make_exercise(
    id: str, primary: tuple[Muscle, ...], secondary: tuple[Muscle, ...] = ()
) -> Exercise:
    return Exercise(
        id=id,
        name=id,
        category=Category.STRENGTH,
        level=Level.BEGINNER,
        equipment=None,
        force=None,
        mechanic=None,
        primary=primary,
        secondary=secondary,
        instructions=(),
        images=(),
    )


BENCH = make_exercise("bench", (Muscle.CHEST,), (Muscle.TRICEPS, Muscle.SHOULDERS))
SQUAT = make_exercise("squat", (Muscle.QUADRICEPS, Muscle.GLUTES), (Muscle.QUADRICEPS,))
CATALOGUE = {e.id: e for e in (BENCH, SQUAT)}


def a_set(
    exercise: str = "bench",
    *,
    reps: int | None = 5,
    weight: str | None = "100",
    unit: WeightUnit = WeightUnit.KG,
    kind: SetKind = SetKind.WORKING,
    workout: UUID | None = None,
    at: datetime = T0,
    position: int = 1,
    seconds: int | None = None,
    rpe: str | None = None,
) -> SetEntry:
    return SetEntry(
        id=uuid4(),
        workout_id=workout or uuid4(),
        exercise_id=exercise,
        position=position,
        kind=kind,
        reps=reps,
        weight=None if weight is None else D(weight),
        unit=unit,
        seconds=seconds,
        rpe=None if rpe is None else D(rpe),
        done_at=at,
    )


# --- slots, routines, plans ---------------------------------------------------------------------


def test_a_slot_has_reps_or_seconds_not_both_and_not_neither() -> None:
    assert Slot("bench", 3, 8, None).rest_seconds == 90
    assert Slot("plank", 3, None, 45, 30, "  hold  ").note == "hold"
    for reps, seconds in ((None, None), (8, 45)):
        with pytest.raises(InvalidInput):
            Slot("bench", 3, reps, seconds)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sets": 0},
        {"sets": 21},
        {"reps": 0},
        {"reps": 101},
        {"rest_seconds": -1},
        {"rest_seconds": 901},
        {"exercise_id": " "},
        {"sets": True},
    ],
)
def test_slot_bounds(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {"exercise_id": "bench", "sets": 3, "reps": 8, "seconds": None}
    with pytest.raises(InvalidInput):
        Slot(**{**base, **kwargs})  # type: ignore[arg-type]


def test_slot_edges_are_allowed() -> None:
    Slot("bench", 1, 1, None, 0)
    Slot("bench", 20, 100, None, 900)
    Slot("plank", 1, None, 1)
    Slot("plank", 1, None, 3600)
    with pytest.raises(InvalidInput):
        Slot("plank", 1, None, 3601)
    with pytest.raises(InvalidInput):
        Slot("plank", 1, None, 0)


def test_slots_round_trip_through_dicts() -> None:
    slot = Slot("plank", 2, None, 30, 45, "tight")
    assert Slot.from_dict(slot.as_dict()) == slot
    with pytest.raises(InvalidInput):
        Slot.from_dict({"sets": 3})
    with pytest.raises(InvalidInput):
        Slot.from_dict({"exercise_id": "x", "sets": "3", "reps": 5})


def test_a_routine_needs_a_name_and_slots_and_round_trips() -> None:
    slots = (Slot("bench", 3, 8, None), Slot("squat", 5, 5, None))
    routine = Routine(uuid4(), USER, "  Push A ", slots, T0, T0)
    assert routine.name == "Push A"
    assert Routine.from_dict(routine.as_dict()) == routine
    with pytest.raises(InvalidInput):
        Routine(uuid4(), USER, " ", slots, T0, T0)
    with pytest.raises(InvalidInput):
        Routine(uuid4(), USER, "Empty", (), T0, T0)
    with pytest.raises(InvalidInput):
        Routine(uuid4(), USER, "Long", slots * 26, T0, T0)
    with pytest.raises(InvalidInput):
        Routine.from_dict({"id": "nope"})


def test_a_plan_checks_its_shape_and_forgets_deleted_routines() -> None:
    a, b = uuid4(), uuid4()
    weekly = TrainingPlan(USER, PlanKind.WEEKLY, {0: a, 3: b})
    assert weekly.routine_ids() == {a, b}
    assert weekly.without(a).weekly == {3: b}
    rotation = TrainingPlan(USER, PlanKind.ROTATION, rotation=(a, b, a))
    assert rotation.without(a).rotation == (b,)
    for bad in (7, -1):
        with pytest.raises(InvalidInput):
            TrainingPlan(USER, PlanKind.WEEKLY, {bad: a})
    with pytest.raises(InvalidInput):
        TrainingPlan(USER, PlanKind.WEEKLY, {}, (a,))
    with pytest.raises(InvalidInput):
        TrainingPlan(USER, PlanKind.ROTATION, {0: a})


# --- weights and e1RM ---------------------------------------------------------------------------


def test_weights_have_two_decimals_and_sane_bounds() -> None:
    assert clean_weight(D("102.5")) == D("102.50")
    assert clean_weight(D("0")) == D("0.00")
    assert clean_weight(None) is None
    for bad in (D("1.005"), D("-1"), D("5000.01"), D("NaN"), D("Infinity")):
        with pytest.raises(InvalidInput):
            clean_weight(bad)


def test_a_pound_is_exactly_the_international_pound() -> None:
    assert LB_IN_KG == D("0.45359237")
    assert to_kg(D("100"), WeightUnit.LB) == D("45.359237")
    assert to_kg(D("100"), WeightUnit.KG) == D("100")


def test_epley_one_rep_is_the_weight_and_the_range_is_one_to_twelve() -> None:
    assert epley_1rm(D("140"), 1) == D("140")
    assert epley_1rm(D("100"), 5) == D("116.67")
    assert epley_1rm(D("100"), 10) == D("133.33")
    assert epley_1rm(D("100"), 12) == D("140.00")
    assert epley_1rm(D("100"), 13) is None
    assert epley_1rm(D("100"), 0) is None
    assert epley_1rm(D("0"), 5) is None


def test_a_set_checks_itself() -> None:
    assert a_set(weight="100.50").weight == D("100.50")
    assert a_set(reps=None, weight=None, seconds=30).seconds == 30
    for bad in (
        {"reps": None},  # neither reps nor seconds
        {"reps": 0},
        {"reps": 1001},
        {"weight": "1.234"},
        {"rpe": "0.5"},
        {"rpe": "10.5"},
        {"rpe": "7.25"},
    ):
        with pytest.raises(InvalidInput):
            a_set(**bad)
    for good in ("1", "6.5", "10"):
        assert a_set(rpe=good).rpe == D(good)


# --- best set -----------------------------------------------------------------------------------


def test_best_set_is_by_e1rm_and_ties_go_to_the_heavier_weight() -> None:
    light_many = a_set(reps=10, weight="80")  # 106.67
    heavy_few = a_set(reps=3, weight="95")  # 104.50
    assert best_set([heavy_few, light_many]) is light_many
    # 100 x 1 = 100.00; 90 x 4 = 102.00; 85 x 6 = 102.00: a tie, the heavier (90) wins.
    four, six = a_set(reps=4, weight="90"), a_set(reps=6, weight="85")
    assert epley_1rm(D("90"), 4) == epley_1rm(D("85"), 6) == D("102.00")
    assert best_set([six, four]) is four
    assert best_set([four, six]) is four


def test_best_set_ignores_warmups_time_sets_and_high_rep_sets() -> None:
    warm = a_set(reps=1, weight="200", kind=SetKind.WARMUP)
    plank = a_set("plank", reps=None, weight=None, seconds=60)
    high = a_set(reps=20, weight="150")
    assert best_set([warm, plank, high]) is None
    assert best_set([]) is None
    working = a_set(reps=5, weight="60")
    assert best_set([warm, plank, high, working]) is working


def test_best_set_compares_pounds_and_kilograms() -> None:
    pounds = a_set(reps=5, weight="225", unit=WeightUnit.LB)  # 102.06 kg x5
    kilos = a_set(reps=5, weight="100")
    assert best_set([kilos, pounds]) is pounds
    assert best_set([pounds, replace(kilos, weight=D("105"))]).weight == D("105")  # type: ignore[union-attr]


# --- records ------------------------------------------------------------------------------------


def test_a_first_time_exercise_has_no_records_yet() -> None:
    assert detect_prs([a_set(weight="100")], []) == {}
    assert detect_prs([a_set("squat", weight="100")], [a_set("bench", weight="50")]) == {}


def test_heaviest_weight_and_best_e1rm() -> None:
    old = a_set(reps=5, weight="100", at=T0 - timedelta(days=7))
    # 110 x 3 is heavier, and its e1RM 121 is a best too.
    heavier = a_set(reps=3, weight="110")
    assert detect_prs([heavier], [old]) == {"bench": (PrKind.HEAVIEST_WEIGHT, PrKind.BEST_E1RM)}
    # A lighter, higher-rep set can have the better e1RM without being the heaviest.
    reps = a_set(reps=10, weight="90")  # 120
    assert detect_prs([reps], [old]) == {"bench": (PrKind.BEST_E1RM,)}
    # Equal is not better.
    assert detect_prs([a_set(reps=5, weight="100")], [old]) == {}


def test_most_reps_at_a_weight_lifted_before() -> None:
    old = a_set(reps=5, weight="100")
    more = a_set(reps=6, weight="100")
    found = detect_prs([more], [old])
    assert PrKind.MOST_REPS in found["bench"]
    # Reps at a weight never lifted before aren't a reps record.
    assert PrKind.MOST_REPS not in detect_prs([a_set(reps=9, weight="80")], [old]).get("bench", ())
    # Bodyweight reps are compared with each other.
    bw_old, bw_new = a_set("pullup", weight=None, reps=8), a_set("pullup", weight=None, reps=10)
    assert detect_prs([bw_new], [bw_old]) == {"pullup": (PrKind.MOST_REPS,)}


def test_pounds_and_kilograms_are_compared_as_the_same_weight() -> None:
    old = a_set(reps=5, weight="100")
    same_in_lb = a_set(reps=5, weight=str(D("220.46")), unit=WeightUnit.LB)  # 99.9998 kg
    assert detect_prs([same_in_lb], [old]) == {}  # lighter, and not exactly the same weight
    exact = a_set(reps=6, weight="100", unit=WeightUnit.KG)
    assert PrKind.MOST_REPS in detect_prs([exact], [old])["bench"]
    heavier_lb = a_set(reps=5, weight="225", unit=WeightUnit.LB)  # 102.06 kg
    assert PrKind.HEAVIEST_WEIGHT in detect_prs([heavier_lb], [old])["bench"]
    lighter_lb = a_set(reps=5, weight="220", unit=WeightUnit.LB)  # 99.79 kg
    assert detect_prs([lighter_lb], [old]) == {}


def test_warmups_never_count_on_either_side() -> None:
    old = a_set(reps=5, weight="100")
    warm_new = a_set(reps=1, weight="200", kind=SetKind.WARMUP)
    assert detect_prs([warm_new], [old]) == {}
    warm_old = a_set(reps=1, weight="300", kind=SetKind.WARMUP)
    assert detect_prs([a_set(reps=5, weight="110")], [old, warm_old])["bench"][0] is (
        PrKind.HEAVIEST_WEIGHT
    )
    # History made only of warm-ups is no history.
    assert detect_prs([a_set(weight="110")], [warm_old]) == {}


def test_prs_skip_sets_that_are_in_both_lists_and_work_per_exercise() -> None:
    old_bench = a_set(reps=5, weight="100")
    new_bench = a_set(reps=5, weight="110")
    new_squat = a_set("squat", reps=5, weight="150")
    found = detect_prs([new_bench, new_squat], [old_bench, new_bench])
    assert set(found) == {"bench"}  # squat has no history


# --- rotation and today's routine -----------------------------------------------------------------


def test_next_in_rotation_wraps_round() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    plan = TrainingPlan(USER, PlanKind.ROTATION, rotation=(a, b, c))
    assert next_in_rotation(plan, None) == a
    assert next_in_rotation(plan, a) == b
    assert next_in_rotation(plan, b) == c
    assert next_in_rotation(plan, c) == a  # wrap-around
    assert next_in_rotation(plan, uuid4()) == a  # a routine no longer in it
    assert next_in_rotation(TrainingPlan(USER, PlanKind.ROTATION), a) is None
    twice = TrainingPlan(USER, PlanKind.ROTATION, rotation=(a, b, a, c))
    assert next_in_rotation(twice, a) == c  # after its last place


def test_todays_routine_for_a_weekly_plan() -> None:
    a, b = uuid4(), uuid4()
    plan = TrainingPlan(USER, PlanKind.WEEKLY, {0: a, 4: b})
    assert todays_routine(plan, date(2026, 11, 23), None) == a  # Monday
    assert todays_routine(plan, date(2026, 11, 24), None) is None  # Tuesday: rest
    assert todays_routine(plan, date(2026, 11, 27), None) == b  # Friday
    assert todays_routine(plan, date(2026, 11, 29), None) is None  # Sunday: 6


def test_todays_routine_for_a_rotation() -> None:
    a, b = uuid4(), uuid4()
    plan = TrainingPlan(USER, PlanKind.ROTATION, rotation=(a, b))
    assert todays_routine(plan, date(2026, 11, 24), None) == a
    last_a = Workout(uuid4(), USER, a, T0)  # started Monday 23rd
    assert todays_routine(plan, date(2026, 11, 24), last_a) == b  # a day later: the next one
    assert todays_routine(plan, date(2026, 11, 23), last_a) == a  # still today's
    last_b = Workout(uuid4(), USER, b, T0)
    assert todays_routine(plan, date(2026, 11, 25), last_b) == a  # wraps
    assert todays_routine(plan, date(2026, 11, 25), Workout(uuid4(), USER, None, T0)) == a


def test_todays_routine_judges_the_day_in_the_users_zone() -> None:
    a, b = uuid4(), uuid4()
    plan = TrainingPlan(USER, PlanKind.ROTATION, rotation=(a, b))
    singapore = timezone(timedelta(hours=8))
    late = datetime(2026, 11, 23, 20, 0, tzinfo=UTC)  # 04:00 on the 24th in Singapore
    last = Workout(uuid4(), USER, a, late)
    assert todays_routine(plan, date(2026, 11, 24), last, tz=singapore) == a
    assert todays_routine(plan, date(2026, 11, 24), last) == b  # in UTC it was the 23rd


# --- last time ----------------------------------------------------------------------------------


def test_last_time_is_the_most_recent_workout_with_the_exercise() -> None:
    w1, w2, w3 = uuid4(), uuid4(), uuid4()
    first = [a_set(workout=w1, at=T0, position=1), a_set(workout=w1, at=T0, position=2)]
    second = [
        a_set(workout=w2, at=T0 + timedelta(days=2), position=2, weight="105"),
        a_set(workout=w2, at=T0 + timedelta(days=2), position=1, weight="100"),
    ]
    other = [a_set("squat", workout=w3, at=T0 + timedelta(days=4))]
    got = last_time("bench", [*second, *other, *first])
    assert [s.weight for s in got] == [D("100"), D("105")]  # in order, only the second workout
    assert last_time("squat", [*first, *second, *other]) == other
    assert last_time("deadlift", first) == []
    assert last_time("bench", []) == []


# --- volume -------------------------------------------------------------------------------------


def test_volume_gives_primary_full_credit_and_secondary_half() -> None:
    bench = a_set(reps=5, weight="100", at=T0)  # 500
    squat = a_set("squat", reps=10, weight="60", at=T0 + timedelta(days=1))  # 600
    out = volume_by_muscle([bench, squat], CATALOGUE, week=date(2026, 11, 25))
    assert out[Muscle.CHEST].volume_kg == D("500")
    assert (out[Muscle.CHEST].sets, out[Muscle.CHEST].secondary_sets) == (1, 0)
    assert out[Muscle.TRICEPS].volume_kg == D("250")
    assert (out[Muscle.TRICEPS].sets, out[Muscle.TRICEPS].secondary_sets) == (0, 1)
    assert out[Muscle.QUADRICEPS].volume_kg == D("600")  # primary AND secondary: counted once
    assert out[Muscle.QUADRICEPS].secondary_sets == 0
    assert out[Muscle.GLUTES].volume_kg == D("600")
    assert Muscle.BICEPS not in out


def test_volume_skips_warmups_unknown_exercises_and_counts_time_sets_without_volume() -> None:
    warm = a_set(kind=SetKind.WARMUP)
    unknown = a_set("mystery")
    bodyweight = a_set(weight=None, reps=10)
    out = volume_by_muscle([warm, unknown, bodyweight], CATALOGUE, week=date(2026, 11, 23))
    assert out[Muscle.CHEST].volume_kg == D("0")
    assert out[Muscle.CHEST].sets == 1
    assert volume_by_muscle([], CATALOGUE, week=date(2026, 11, 23)) == {}


def test_volume_converts_pounds() -> None:
    lb = a_set(reps=10, weight="100", unit=WeightUnit.LB)
    out = volume_by_muscle([lb], CATALOGUE, week=T0.date())
    assert out[Muscle.CHEST].volume_kg == D("453.59237")


def test_week_boundaries_are_monday_to_sunday() -> None:
    assert week_start(date(2026, 11, 23)) == date(2026, 11, 23)
    assert week_start(date(2026, 11, 29)) == date(2026, 11, 23)  # Sunday
    assert week_start(date(2026, 11, 30)) == date(2026, 11, 30)
    sunday_night = a_set(at=datetime(2026, 11, 29, 23, 59, tzinfo=UTC))
    monday_morning = a_set(at=datetime(2026, 11, 30, 0, 0, tzinfo=UTC))
    before_monday = a_set(at=datetime(2026, 11, 22, 23, 59, tzinfo=UTC))
    sets = [sunday_night, monday_morning, before_monday]
    this = volume_by_muscle(sets, CATALOGUE, week=date(2026, 11, 26))
    assert this[Muscle.CHEST].sets == 1
    nxt = volume_by_muscle(sets, CATALOGUE, week=date(2026, 11, 30))
    assert nxt[Muscle.CHEST].sets == 1
    earlier = volume_by_muscle(sets, CATALOGUE, week=date(2026, 11, 22))
    assert earlier[Muscle.CHEST].sets == 1


def test_the_week_is_judged_in_the_users_zone() -> None:
    singapore = timezone(timedelta(hours=8))
    s = a_set(at=datetime(2026, 11, 29, 17, 0, tzinfo=UTC))  # 01:00 Monday the 30th there
    assert volume_by_muscle([s], CATALOGUE, week=date(2026, 11, 23)) != {}
    assert volume_by_muscle([s], CATALOGUE, week=date(2026, 11, 23), tz=singapore) == {}
    assert volume_by_muscle([s], CATALOGUE, week=date(2026, 11, 30), tz=singapore) != {}


# --- summary and progress -----------------------------------------------------------------------


def test_a_summary_counts_working_sets_volume_and_records() -> None:
    wid = uuid4()
    workout = Workout(wid, USER, None, T0, T0 + timedelta(minutes=50))
    sets = [
        a_set(workout=wid, kind=SetKind.WARMUP, weight="40", reps=10),
        a_set(workout=wid, reps=5, weight="110"),
        a_set(workout=wid, reps=5, weight="110", position=2),
    ]
    history = [a_set(reps=5, weight="100", at=T0 - timedelta(days=7))]
    summary = summarise(workout, sets, history)
    assert summary.duration == timedelta(minutes=50)
    assert summary.sets == 2
    assert summary.volume_kg == D("1100")
    assert summary.prs == {"bench": (PrKind.HEAVIEST_WEIGHT, PrKind.BEST_E1RM)}
    with pytest.raises(InvalidInput):
        summarise(replace(workout, finished_at=None), sets, history)


def test_a_workout_cannot_finish_before_it_starts() -> None:
    with pytest.raises(InvalidInput):
        Workout(uuid4(), USER, None, T0, T0 - timedelta(seconds=1))


def test_progress_is_the_best_set_of_each_workout_oldest_first() -> None:
    w1, w2 = uuid4(), uuid4()
    later = [
        a_set(workout=w2, reps=5, weight="105", at=T0 + timedelta(days=7)),
        a_set(workout=w2, reps=1, weight="90", at=T0 + timedelta(days=7)),
    ]
    first = [a_set(workout=w1, reps=5, weight="100", at=T0), a_set(workout=w1, reps=8, weight="60")]
    points = progress([*later, *first])
    assert [p.workout_id for p in points] == [w1, w2]
    assert [p.e1rm_kg for p in points] == [D("116.67"), D("122.50")]
    assert progress([a_set(kind=SetKind.WARMUP)]) == []


# --- records while logging ------------------------------------------------------------------------


def test_a_set_flags_the_records_it_sets_with_text() -> None:
    old = a_set(reps=5, weight="100", at=T0 - timedelta(days=7))
    heavier = a_set(reps=3, weight="110.50")
    found = records_of_set(heavier, [], [old])
    assert [(r.kind, r.exercise_id, r.value_text) for r in found] == [
        (PrKind.HEAVIEST_WEIGHT, "bench", "110.5 kg"),
        (PrKind.BEST_E1RM, "bench", "e1RM 121.55 kg"),
    ]
    more = records_of_set(a_set(reps=6, weight="100"), [], [old])
    assert [(r.kind, r.value_text) for r in more] == [
        (PrKind.BEST_E1RM, "e1RM 120 kg"),
        (PrKind.MOST_REPS, "6 reps at 100 kg"),
    ]
    bodyweight = records_of_set(
        a_set("pullup", weight=None, reps=10), [], [a_set("pullup", weight=None, reps=8)]
    )
    assert [(r.kind, r.value_text) for r in bodyweight] == [(PrKind.MOST_REPS, "10 reps")]


def test_warmups_and_first_times_flag_nothing() -> None:
    old = a_set(reps=5, weight="100")
    assert records_of_set(a_set(reps=1, weight="200", kind=SetKind.WARMUP), [], [old]) == []
    assert records_of_set(a_set(reps=5, weight="100"), [], []) == []
    assert records_of_set(a_set("squat", reps=5, weight="300"), [], [old]) == []


def test_a_set_is_measured_against_the_sets_before_it_in_the_workout() -> None:
    old = a_set(reps=5, weight="100", at=T0 - timedelta(days=7))
    first = a_set(reps=5, weight="110", position=1)
    second = a_set(reps=5, weight="105", position=2)  # beats history, not the first set
    third = a_set(reps=5, weight="115", position=3)
    assert [r.kind for r in records_of_set(first, [], [old])] == [
        PrKind.HEAVIEST_WEIGHT,
        PrKind.BEST_E1RM,
    ]
    assert records_of_set(second, [first], [old]) == []
    assert [r.kind for r in records_of_set(third, [first, second], [old])] == [
        PrKind.HEAVIEST_WEIGHT,
        PrKind.BEST_E1RM,
    ]


def test_a_warmup_earlier_in_the_workout_sets_no_bar() -> None:
    old = a_set(reps=5, weight="100", at=T0 - timedelta(days=7))
    warm = a_set(reps=1, weight="200", kind=SetKind.WARMUP, position=1)
    work = a_set(reps=5, weight="105", position=2)
    assert PrKind.HEAVIEST_WEIGHT in [r.kind for r in records_of_set(work, [warm], [old])]


def test_live_flags_add_up_to_the_summary() -> None:
    old = a_set(reps=5, weight="100", at=T0 - timedelta(days=7))
    # A weight first lifted in this workout can't be a reps record at the end, so not live either.
    sequence = [
        a_set(reps=5, weight="80", position=1),
        a_set(reps=8, weight="80", position=2),
        a_set(reps=6, weight="100", position=3),
        a_set(reps=3, weight="110", position=4),
        a_set(reps=3, weight="112.5", unit=WeightUnit.KG, position=5),
        a_set("squat", reps=5, weight="150", position=6),
    ]
    live: dict[str, set[PrKind]] = {}
    for i, entry in enumerate(sequence):
        for r in records_of_set(entry, sequence[:i], [old]):
            live.setdefault(r.exercise_id, set()).add(r.kind)
    final = detect_prs(sequence, [old])
    assert live == {e: set(kinds) for e, kinds in final.items()}
    assert live  # the sequence does set records
