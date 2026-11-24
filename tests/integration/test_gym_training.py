"""Gym training data: routines, the plan, workouts and sets; consent; the web API; and that one
user never sees or writes another's. Every name and figure is made up."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import gym as gym_cases
from nexus.application.users import get_user, set_preferences
from nexus.domain.errors import (
    Conflict,
    ConsentRequired,
    InvalidInput,
    NotFound,
    NothingToUndo,
)
from nexus.domain.gym import Muscle
from nexus.domain.gym_training import (
    PlanKind,
    PrKind,
    SetKind,
    Slot,
    WeightUnit,
)
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import routines, workout_sets, workouts
from nexus.infra.exercises import load_catalogue
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory
from tests.integration.test_web_api import MEMBER, OWNER, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

BENCH = "Barbell_Bench_Press_-_Medium_Grip"
SQUAT = "Barbell_Squat"
PLANK = "Plank"
D = Decimal


@pytest.fixture(autouse=True)
async def catalogue(uow: UowFactory) -> None:
    await gym_cases.sync_catalogue(uow(), load_catalogue())


async def consenting(uow: UowFactory, user: UserId) -> UserId:
    await gym_cases.give_consent(uow(), user, now=NOW)
    return user


async def a_routine(
    uow: UowFactory, user: UserId, name: str = "Push", *, at: datetime = NOW
) -> UUID:
    saved = await gym_cases.save_routine(
        uow(),
        user,
        name=name,
        slots=[Slot(BENCH, 3, 8, None), Slot(PLANK, 2, None, 30, 30)],
        now=at,
    )
    return saved.id


# --- consent ------------------------------------------------------------------------------------


async def test_every_write_needs_consent(uow: UowFactory, alice: UserId) -> None:
    some = uuid4()
    writes = [
        gym_cases.save_routine(uow(), alice, name="x", slots=[Slot(BENCH, 1, 1, None)], now=NOW),
        gym_cases.set_plan(uow(), alice, PlanKind.ROTATION, rotation=[some], now=NOW),
        gym_cases.start_workout(uow(), alice, now=NOW),
        gym_cases.log_set(uow(), alice, some, exercise_id=BENCH, reps=5, now=NOW),
        gym_cases.edit_set(uow(), alice, some, {"reps": 6}),
        gym_cases.finish_workout(uow(), alice, some, now=NOW),
    ]
    for write in writes:
        with pytest.raises(ConsentRequired):
            await write
    assert await gym_cases.consent(uow(), alice) is None
    assert await gym_cases.routines(uow(), alice) == []  # nothing was written


async def test_consent_is_given_once_and_withdrawing_keeps_the_data(
    uow: UowFactory, alice: UserId
) -> None:
    first = await gym_cases.give_consent(uow(), alice, now=NOW)
    again = await gym_cases.give_consent(uow(), alice, now=NOW + timedelta(days=1))
    assert first == again == NOW
    assert (await get_user(uow(), alice)).health_consent_at == NOW

    routine_id = await a_routine(uow, alice)
    workout = await gym_cases.start_workout(uow(), alice, routine_id=routine_id, now=NOW)
    await gym_cases.log_set(uow(), alice, workout.id, exercise_id=BENCH, reps=5, now=NOW)

    await gym_cases.withdraw_consent(uow(), alice)
    assert await gym_cases.consent(uow(), alice) is None
    with pytest.raises(ConsentRequired):
        await a_routine(uow, alice, "Another")
    with pytest.raises(ConsentRequired):
        await gym_cases.log_set(uow(), alice, workout.id, exercise_id=BENCH, reps=5, now=NOW)
    # What was stored stays, can be read, and can be deleted without agreeing again.
    assert len(await gym_cases.routines(uow(), alice)) == 1
    assert len((await gym_cases.workout(uow(), alice, workout.id)).sets) == 1
    await gym_cases.discard_workout(uow(), alice, workout.id)
    await gym_cases.delete_routine(uow(), alice, routine_id, now=NOW)
    assert await gym_cases.routines(uow(), alice) == []

    assert await gym_cases.give_consent(uow(), alice, now=NOW + timedelta(days=2)) == (
        NOW + timedelta(days=2)
    )


async def test_the_first_write_turns_health_on_unless_the_user_turned_it_off(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await consenting(uow, alice)
    await consenting(uow, bob)
    assert (await get_user(uow(), alice)).show_health is None
    await gym_cases.give_consent(uow(), alice, now=NOW)  # agreeing alone doesn't
    assert (await get_user(uow(), alice)).show_health is None
    await a_routine(uow, alice)
    assert (await get_user(uow(), alice)).show_health is True

    await set_preferences(uow(), bob, show_health=False)
    await a_routine(uow, bob)
    assert (await get_user(uow(), bob)).show_health is False  # their own choice sticks


# --- routines and the plan ----------------------------------------------------------------------


async def test_routines_are_created_updated_listed_and_deleted(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    first = await a_routine(uow, alice, "Push")
    second = await a_routine(uow, alice, "Pull", at=NOW + timedelta(minutes=1))
    assert [r.name for r in await gym_cases.routines(uow(), alice)] == ["Push", "Pull"]

    edited = await gym_cases.save_routine(
        uow(),
        alice,
        name="Push B",
        slots=[Slot(SQUAT, 5, 5, None, 180, "heavy")],
        routine_id=first,
        now=NOW + timedelta(hours=1),
    )
    assert edited.created_at == NOW and edited.updated_at == NOW + timedelta(hours=1)
    assert await gym_cases.routine(uow(), alice, first) == edited
    assert edited.slots[0].note == "heavy"

    await gym_cases.delete_routine(uow(), alice, second, now=NOW)
    assert [r.id for r in await gym_cases.routines(uow(), alice)] == [first]
    for missing in (second, uuid4()):
        with pytest.raises(NotFound):
            await gym_cases.delete_routine(uow(), alice, missing, now=NOW)
        with pytest.raises(NotFound):
            await gym_cases.routine(uow(), alice, missing)
    with pytest.raises(NotFound):
        await gym_cases.save_routine(
            uow(), alice, name="x", slots=[Slot(BENCH, 1, 1, None)], routine_id=uuid4(), now=NOW
        )


async def test_routines_must_use_catalogue_exercises(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    with pytest.raises(InvalidInput, match="Nope"):
        await gym_cases.save_routine(
            uow(),
            alice,
            name="x",
            slots=[Slot(BENCH, 1, 1, None), Slot("Nope", 1, 1, None)],
            now=NOW,
        )
    assert await gym_cases.routines(uow(), alice) == []


async def test_the_plan_is_one_per_user_and_loses_a_deleted_routine(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    assert await gym_cases.plan(uow(), alice) is None
    push, pull = await a_routine(uow, alice, "Push"), await a_routine(uow, alice, "Pull")

    weekly = await gym_cases.set_plan(
        uow(), alice, PlanKind.WEEKLY, weekly={0: push, 3: pull}, now=NOW
    )
    assert await gym_cases.plan(uow(), alice) == weekly
    rotation = await gym_cases.set_plan(
        uow(), alice, PlanKind.ROTATION, rotation=[push, pull, push], now=NOW
    )
    assert await gym_cases.plan(uow(), alice) == rotation  # replaced, not added to

    await gym_cases.delete_routine(uow(), alice, push, now=NOW)
    left = await gym_cases.plan(uow(), alice)
    assert left is not None and left.rotation == (pull,)
    with pytest.raises(InvalidInput):
        await gym_cases.set_plan(uow(), alice, PlanKind.ROTATION, rotation=[uuid4()], now=NOW)
    with pytest.raises(InvalidInput):
        await gym_cases.set_plan(uow(), alice, PlanKind.WEEKLY, weekly={9: pull}, now=NOW)


async def test_todays_workout_follows_the_plan(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    push, pull = await a_routine(uow, alice, "Push"), await a_routine(uow, alice, "Pull")
    assert (await gym_cases.todays_workout(uow(), alice, now=NOW)).routine is None  # no plan

    # NOW is a Monday (noon in Singapore, but UTC is the user's zone here).
    await gym_cases.set_plan(uow(), alice, PlanKind.WEEKLY, weekly={0: push}, now=NOW)
    today = await gym_cases.todays_workout(uow(), alice, now=NOW)
    assert today.routine is not None and today.routine.id == push and today.in_progress is None
    assert (
        await gym_cases.todays_workout(uow(), alice, now=NOW + timedelta(days=1))
    ).routine is None

    await gym_cases.set_plan(uow(), alice, PlanKind.ROTATION, rotation=[push, pull], now=NOW)
    started = await gym_cases.start_workout(uow(), alice, routine_id=push, now=NOW)
    today = await gym_cases.todays_workout(uow(), alice, now=NOW)
    assert today.routine is not None and today.routine.id == push  # started today: still today's
    assert today.in_progress == started
    await gym_cases.finish_workout(uow(), alice, started.id, now=NOW + timedelta(hours=1))
    tomorrow = await gym_cases.todays_workout(uow(), alice, now=NOW + timedelta(days=1))
    assert tomorrow.routine is not None and tomorrow.routine.id == pull
    assert tomorrow.in_progress is None


# --- workouts and sets --------------------------------------------------------------------------


async def test_a_workout_from_start_to_summary(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    # An earlier workout to set records against.
    old = await gym_cases.start_workout(uow(), alice, now=NOW - timedelta(days=7))
    await gym_cases.log_set(
        uow(),
        alice,
        old.id,
        exercise_id=BENCH,
        reps=5,
        weight=D("100"),
        now=NOW - timedelta(days=7),
    )
    await gym_cases.finish_workout(uow(), alice, old.id, now=NOW - timedelta(days=7, hours=-1))

    routine_id = await a_routine(uow, alice)
    workout = await gym_cases.start_workout(uow(), alice, routine_id=routine_id, now=NOW)
    with pytest.raises(Conflict):  # one at a time
        await gym_cases.start_workout(uow(), alice, now=NOW)

    at = NOW + timedelta(minutes=5)
    warm = await gym_cases.log_set(
        uow(),
        alice,
        workout.id,
        exercise_id=BENCH,
        kind=SetKind.WARMUP,
        reps=10,
        weight=D("40"),
        now=at,
    )
    work = await gym_cases.log_set(
        uow(),
        alice,
        workout.id,
        exercise_id=BENCH,
        reps=5,
        weight=D("225"),
        unit=WeightUnit.LB,
        rpe=D("8.5"),
        now=at + timedelta(minutes=5),
    )
    plank = await gym_cases.log_set(
        uow(), alice, workout.id, exercise_id=PLANK, seconds=45, now=at + timedelta(minutes=10)
    )
    assert [s.position for s in (warm, work, plank)] == [1, 2, 3]

    edited = await gym_cases.edit_set(uow(), alice, work.id, {"reps": 6, "weight": D("230")})
    assert (edited.reps, edited.weight, edited.unit, edited.position) == (
        6,
        D("230.00"),
        WeightUnit.LB,
        2,
    )
    with pytest.raises(InvalidInput):
        await gym_cases.edit_set(uow(), alice, work.id, {"weight": D("1.234")})
    with pytest.raises(InvalidInput):
        await gym_cases.edit_set(uow(), alice, work.id, {"position": 9})
    with pytest.raises(InvalidInput):
        await gym_cases.edit_set(uow(), alice, work.id, {"exercise_id": "Nope"})
    assert (await gym_cases.edit_set(uow(), alice, work.id, {"rpe": None})).rpe is None

    undone = await gym_cases.undo_last_set(uow(), alice, workout.id)
    assert undone.id == plank.id
    again = await gym_cases.log_set(
        uow(), alice, workout.id, exercise_id=PLANK, seconds=60, now=at + timedelta(minutes=11)
    )
    assert again.position == 3  # the undone set's place is free again

    summary = await gym_cases.finish_workout(
        uow(), alice, workout.id, note="solid", now=NOW + timedelta(minutes=50)
    )
    assert summary.duration == timedelta(minutes=50)
    assert summary.sets == 2  # the warm-up isn't one
    assert summary.volume_kg == D("230.00") * D("0.45359237") * 6
    assert summary.prs == {BENCH: (PrKind.HEAVIEST_WEIGHT, PrKind.BEST_E1RM)}

    detail = await gym_cases.workout(uow(), alice, workout.id)
    assert (
        detail.workout.finished_at == NOW + timedelta(minutes=50) and detail.workout.note == "solid"
    )
    assert [s.id for s in detail.sets] == [warm.id, work.id, again.id]
    with pytest.raises(Conflict):
        await gym_cases.finish_workout(uow(), alice, workout.id, now=NOW)
    with pytest.raises(Conflict):
        await gym_cases.log_set(uow(), alice, workout.id, exercise_id=BENCH, reps=1, now=NOW)
    with pytest.raises(Conflict):
        await gym_cases.undo_last_set(uow(), alice, workout.id)

    # A finished workout's set can still be corrected, and deleted.
    await gym_cases.edit_set(uow(), alice, work.id, {"reps": 5})
    await gym_cases.delete_set(uow(), alice, again.id)
    with pytest.raises(NotFound):
        await gym_cases.delete_set(uow(), alice, again.id)


async def test_undo_with_nothing_logged_and_unknown_things(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    workout = await gym_cases.start_workout(uow(), alice, now=NOW)
    with pytest.raises(NothingToUndo):
        await gym_cases.undo_last_set(uow(), alice, workout.id)
    with pytest.raises(InvalidInput):
        await gym_cases.log_set(uow(), alice, workout.id, exercise_id="Nope", reps=5, now=NOW)
    with pytest.raises(InvalidInput):  # neither reps nor seconds
        await gym_cases.log_set(uow(), alice, workout.id, exercise_id=BENCH, now=NOW)
    with pytest.raises(NotFound):
        await gym_cases.start_workout(uow(), alice, routine_id=uuid4(), now=NOW)
    with pytest.raises(NotFound):
        await gym_cases.log_set(uow(), alice, uuid4(), exercise_id=BENCH, reps=5, now=NOW)
    with pytest.raises(NotFound):
        await gym_cases.workout(uow(), alice, uuid4())
    with pytest.raises(NotFound):
        await gym_cases.discard_workout(uow(), alice, uuid4())
    await gym_cases.discard_workout(uow(), alice, workout.id)
    await gym_cases.start_workout(uow(), alice, now=NOW)  # none open any more


async def test_workouts_in_a_range_and_deleting_a_routine_keeps_them(
    uow: UowFactory, alice: UserId, engine: AsyncEngine
) -> None:
    await consenting(uow, alice)
    routine_id = await a_routine(uow, alice)
    made = []
    for days in (10, 3, 0):
        started = NOW - timedelta(days=days)
        w = await gym_cases.start_workout(uow(), alice, routine_id=routine_id, now=started)
        await gym_cases.log_set(uow(), alice, w.id, exercise_id=BENCH, reps=5, now=started)
        await gym_cases.finish_workout(uow(), alice, w.id, now=started + timedelta(hours=1))
        made.append(w.id)
    everything = await gym_cases.workouts(uow(), alice)
    assert [d.workout.id for d in everything] == made[::-1]  # newest first
    assert all(len(d.sets) == 1 for d in everything)
    window = await gym_cases.workouts(
        uow(), alice, start=(NOW - timedelta(days=5)).date(), end=NOW.date()
    )
    assert [d.workout.id for d in window] == [made[1]]  # end is exclusive

    await gym_cases.delete_routine(uow(), alice, routine_id, now=NOW)
    kept = await gym_cases.workouts(uow(), alice)
    assert len(kept) == 3 and all(d.workout.routine_id is None for d in kept)

    await gym_cases.discard_workout(uow(), alice, made[0])  # takes its sets with it
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(workout_sets)) == 2
        assert await db.scalar(select(func.count()).select_from(workouts)) == 2


async def test_last_time_progress_and_weekly_volume(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)

    async def session(days_ago: int, weight: str, reps: int) -> UUID:
        at = NOW - timedelta(days=days_ago)
        w = await gym_cases.start_workout(uow(), alice, now=at)
        for _ in range(2):
            await gym_cases.log_set(
                uow(), alice, w.id, exercise_id=BENCH, reps=reps, weight=D(weight), now=at
            )
        await gym_cases.log_set(
            uow(),
            alice,
            w.id,
            exercise_id=BENCH,
            kind=SetKind.WARMUP,
            reps=10,
            weight=D("20"),
            now=at,
        )
        await gym_cases.finish_workout(uow(), alice, w.id, now=at + timedelta(hours=1))
        return w.id

    first = await session(14, "100", 5)
    second = await session(7, "105", 5)
    this_week = await session(0, "110", 5)

    assert await gym_cases.last_sets(uow(), alice, SQUAT) == []
    last = await gym_cases.last_sets(uow(), alice, BENCH)
    assert {s.workout_id for s in last} == {this_week} and len(last) == 3
    with pytest.raises(InvalidInput):
        await gym_cases.last_sets(uow(), alice, "Nope")

    points = await gym_cases.exercise_progress(uow(), alice, BENCH)
    assert [p.workout_id for p in points] == [first, second, this_week]
    assert [p.best.weight for p in points] == [D("100.00"), D("105.00"), D("110.00")]
    assert await gym_cases.exercise_progress(uow(), alice, SQUAT) == []

    volume = await gym_cases.weekly_volume(uow(), alice, NOW.date())
    assert volume[Muscle.CHEST].volume_kg == D("110") * 5 * 2  # working sets of this week only
    assert volume[Muscle.CHEST].sets == 2
    assert volume[Muscle.TRICEPS].volume_kg == D("550.00")
    assert volume[Muscle.TRICEPS].secondary_sets == 2
    last_week = await gym_cases.weekly_volume(uow(), alice, (NOW - timedelta(days=7)).date())
    assert last_week[Muscle.CHEST].volume_kg == D("1050")
    assert await gym_cases.weekly_volume(uow(), alice, (NOW - timedelta(days=60)).date()) == {}


# --- isolation ----------------------------------------------------------------------------------


async def test_one_user_never_sees_or_writes_anothers_data(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await consenting(uow, alice)
    await consenting(uow, bob)
    routine_id = await a_routine(uow, alice)
    await gym_cases.set_plan(uow(), alice, PlanKind.ROTATION, rotation=[routine_id], now=NOW)
    workout = await gym_cases.start_workout(uow(), alice, routine_id=routine_id, now=NOW)
    logged = await gym_cases.log_set(
        uow(), alice, workout.id, exercise_id=BENCH, reps=5, weight=D("100"), now=NOW
    )
    await gym_cases.finish_workout(uow(), alice, workout.id, now=NOW + timedelta(hours=1))

    assert await gym_cases.routines(uow(), bob) == []
    assert await gym_cases.plan(uow(), bob) is None
    assert await gym_cases.workouts(uow(), bob) == []
    assert await gym_cases.last_sets(uow(), bob, BENCH) == []
    assert await gym_cases.exercise_progress(uow(), bob, BENCH) == []
    assert await gym_cases.weekly_volume(uow(), bob, NOW.date()) == {}
    assert (await gym_cases.todays_workout(uow(), bob, now=NOW)).routine is None

    with pytest.raises(NotFound):
        await gym_cases.routine(uow(), bob, routine_id)
    with pytest.raises(NotFound):
        await gym_cases.workout(uow(), bob, workout.id)
    with pytest.raises(NotFound):
        await gym_cases.delete_routine(uow(), bob, routine_id, now=NOW)
    with pytest.raises(NotFound):
        await gym_cases.save_routine(
            uow(),
            bob,
            name="mine now",
            slots=[Slot(BENCH, 1, 1, None)],
            routine_id=routine_id,
            now=NOW,
        )
    with pytest.raises(NotFound):
        await gym_cases.start_workout(uow(), bob, routine_id=routine_id, now=NOW)
    with pytest.raises(InvalidInput):
        await gym_cases.set_plan(uow(), bob, PlanKind.ROTATION, rotation=[routine_id], now=NOW)
    with pytest.raises(NotFound):
        await gym_cases.edit_set(uow(), bob, logged.id, {"reps": 99})
    with pytest.raises(NotFound):
        await gym_cases.delete_set(uow(), bob, logged.id)
    with pytest.raises(NotFound):
        await gym_cases.discard_workout(uow(), bob, workout.id)
    await gym_cases.start_workout(uow(), bob, now=NOW)
    with pytest.raises(NotFound):
        await gym_cases.undo_last_set(uow(), bob, workout.id)

    # Alice's data is untouched.
    detail = await gym_cases.workout(uow(), alice, workout.id)
    assert [(s.reps, s.weight) for s in detail.sets] == [(5, D("100.00"))]
    assert len(await gym_cases.routines(uow(), alice)) == 1


async def test_the_database_itself_refuses_a_cross_user_link_and_hides_rows(
    uow: UowFactory, alice: UserId, bob: UserId, engine: AsyncEngine
) -> None:
    await consenting(uow, alice)
    routine_id = await a_routine(uow, alice)
    workout = await gym_cases.start_workout(uow(), alice, routine_id=routine_id, now=NOW)
    await gym_cases.log_set(uow(), alice, workout.id, exercise_id=BENCH, reps=5, now=NOW)

    # With bob named, row-level security shows him nothing of alice's and refuses his writes.
    async with engine.connect() as db:
        async with db.begin() as transaction:
            await db.execute(text("SELECT set_config('app.user_id', :id, true)"), {"id": str(bob)})
            for table in (routines, workouts, workout_sets):
                assert await db.scalar(select(func.count()).select_from(table)) == 0
            with pytest.raises(DBAPIError):
                await db.execute(
                    workouts.insert().values(id=uuid4(), user_id=alice, started_at=NOW)
                )
            await transaction.rollback()

    # Without a name the composite keys still stop a workout pointing at someone else's routine.
    async with engine.connect() as db:
        async with db.begin() as transaction:
            with pytest.raises(IntegrityError):
                await db.execute(
                    workouts.insert().values(
                        id=uuid4(), user_id=bob, routine_id=routine_id, started_at=NOW
                    )
                )
            await transaction.rollback()
        async with db.begin() as transaction:
            with pytest.raises(IntegrityError):  # a set in someone else's workout
                await db.execute(
                    workout_sets.insert().values(
                        id=uuid4(),
                        user_id=bob,
                        workout_id=workout.id,
                        exercise_id=BENCH,
                        position=9,
                        kind="working",
                        reps=5,
                        unit="kg",
                        done_at=NOW,
                    )
                )
            await transaction.rollback()
        async with db.begin() as transaction:
            with pytest.raises(IntegrityError):  # a set of an exercise that isn't in the catalogue
                await db.execute(
                    workout_sets.insert().values(
                        id=uuid4(),
                        user_id=alice,
                        workout_id=workout.id,
                        exercise_id="Nope",
                        position=9,
                        kind="working",
                        reps=5,
                        unit="kg",
                        done_at=NOW,
                    )
                )
            await transaction.rollback()


# --- the web API --------------------------------------------------------------------------------


async def test_health_endpoints_need_a_session(world: World) -> None:
    anonymous = world.browser()
    for method, path in (
        ("GET", "/api/health/routines"),
        ("GET", "/api/health/consent"),
        ("POST", "/api/health/workouts"),
        ("GET", "/api/health/volume"),
    ):
        response = await anonymous.send(method, path, {} if method == "POST" else None)
        assert response.status_code in (401, 403), path


async def test_writes_are_refused_until_the_user_consents_and_need_csrf(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    body = {"name": "Push", "slots": [{"exercise_id": BENCH, "sets": 3, "reps": 8}]}
    refused = await owner.send("POST", "/api/health/routines", body)
    assert refused.status_code == 403
    assert "agree" in refused.json()["detail"]
    assert (await owner.get("/api/health/consent")).json() == {"consented_at": None}
    assert (await owner.get("/api/health/routines")).json() == []  # reading is fine

    no_csrf = await owner.send("POST", "/api/health/consent", **{"X-CSRF-Token": "wrong"})
    assert no_csrf.status_code == 403
    agreed = await owner.send("POST", "/api/health/consent")
    assert agreed.status_code == 201 and agreed.json()["consented_at"] is not None
    again = await owner.send("POST", "/api/health/consent")
    assert again.json() == agreed.json()
    assert (await owner.send("POST", "/api/health/routines", body)).status_code == 201

    me = await owner.get("/api/me")
    assert me.json()["preferences"]["show_health"] is True

    gone = await owner.send("DELETE", "/api/health/consent")
    assert gone.status_code == 204
    assert (await owner.get("/api/health/consent")).json() == {"consented_at": None}
    assert (await owner.send("POST", "/api/health/routines", body)).status_code == 403
    assert len((await owner.get("/api/health/routines")).json()) == 1  # kept


async def test_routines_and_plan_over_http(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await owner.send("POST", "/api/health/consent")
    slots = [
        {"exercise_id": BENCH, "sets": 3, "reps": 8, "rest_seconds": 120},
        {"exercise_id": PLANK, "sets": 2, "seconds": 45, "note": "tight"},
    ]
    made = await owner.send("POST", "/api/health/routines", {"name": " Push ", "slots": slots})
    assert made.status_code == 201
    routine = made.json()
    assert routine["name"] == "Push" and routine["slots"][1] == {
        "exercise_id": PLANK,
        "sets": 2,
        "reps": None,
        "seconds": 45,
        "rest_seconds": 90,
        "note": "tight",
    }
    one = await owner.get(f"/api/health/routines/{routine['id']}")
    assert one.json() == routine

    for bad in (
        {"name": "x", "slots": []},
        {"name": "x", "slots": [{"exercise_id": BENCH, "sets": 0, "reps": 5}]},
        {"name": "x", "slots": [{"exercise_id": BENCH, "sets": 1, "reps": 5, "seconds": 5}]},
        {"name": "x", "slots": [{"exercise_id": "Nope", "sets": 1, "reps": 5}]},
        {"name": "x", "slots": slots, "extra": 1},
        {"name": "", "slots": slots},
    ):
        assert (await owner.send("POST", "/api/health/routines", bad)).status_code == 422, bad

    renamed = await owner.send(
        "PUT", f"/api/health/routines/{routine['id']}", {"name": "Push B", "slots": slots[:1]}
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Push B"
    assert len(renamed.json()["slots"]) == 1
    assert (await owner.get("/api/health/routines/not-a-uuid")).status_code == 404
    assert (await owner.get(f"/api/health/routines/{uuid4()}")).status_code == 404
    assert (
        await owner.send("PUT", f"/api/health/routines/{uuid4()}", {"name": "x", "slots": slots})
    ).status_code == 404

    assert (await owner.get("/api/health/plan")).json() is None
    plan = await owner.send(
        "PUT", "/api/health/plan", {"kind": "weekly", "weekly": {"0": routine["id"]}}
    )
    assert plan.status_code == 200
    assert plan.json() == {"kind": "weekly", "weekly": {"0": routine["id"]}, "rotation": []}
    assert (await owner.get("/api/health/plan")).json() == plan.json()
    today = (await owner.get("/api/health/today")).json()  # NOW is a Monday
    assert today["routine"]["id"] == routine["id"] and today["in_progress"] is None
    for bad_plan in (
        {"kind": "weekly", "weekly": {"7": routine["id"]}},
        {"kind": "weekly", "weekly": {"0": str(uuid4())}},
        {"kind": "weekly", "weekly": {"0": "nope"}},
        {"kind": "monthly"},
        {"kind": "rotation", "weekly": {"0": routine["id"]}},
    ):
        assert (await owner.send("PUT", "/api/health/plan", bad_plan)).status_code in (404, 422), (
            bad_plan
        )

    assert (await owner.send("DELETE", f"/api/health/routines/{routine['id']}")).status_code == 204
    assert (await owner.get("/api/health/plan")).json()["weekly"] == {}
    assert (await owner.send("DELETE", f"/api/health/routines/{routine['id']}")).status_code == 404


async def test_a_workout_over_http(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await owner.send("POST", "/api/health/consent")

    world.clock.now = NOW - timedelta(days=7)
    old = (await owner.send("POST", "/api/health/workouts", {})).json()
    assert old["finished_at"] is None
    await owner.send(
        "POST",
        f"/api/health/workouts/{old['id']}/sets",
        {"exercise_id": BENCH, "reps": 5, "weight": "100"},
    )
    world.clock.now = NOW - timedelta(days=7) + timedelta(hours=1)
    assert (
        await owner.send("POST", f"/api/health/workouts/{old['id']}/finish", {})
    ).status_code == 200
    world.clock.now = NOW

    started = await owner.send("POST", "/api/health/workouts", {})
    assert started.status_code == 201
    workout = started.json()
    assert (await owner.send("POST", "/api/health/workouts", {})).status_code == 409
    assert (await owner.get("/api/health/today")).json()["in_progress"]["id"] == workout["id"]

    logged = await owner.send(
        "POST",
        f"/api/health/workouts/{workout['id']}/sets",
        {"exercise_id": BENCH, "reps": 5, "weight": "225.5", "unit": "lb", "rpe": "8.5"},
    )
    assert logged.status_code == 201
    one = logged.json()
    assert (one["weight"], one["unit"], one["rpe"], one["position"], one["kind"]) == (
        "225.50",
        "lb",
        "8.5",
        1,
        "working",
    )
    for bad in (
        {"exercise_id": BENCH, "reps": 5, "weight": "1.234"},
        {"exercise_id": BENCH, "reps": 5, "weight": "heavy"},
        {"exercise_id": BENCH, "reps": 5, "weight": "50", "rpe": "11"},
        {"exercise_id": BENCH, "reps": 5, "unit": "stone"},
        {"exercise_id": BENCH, "reps": 5, "kind": "drop"},
        {"exercise_id": BENCH},
        {"exercise_id": "Nope", "reps": 5},
        {"exercise_id": BENCH, "reps": 5, "x": 1},
    ):
        response = await owner.send("POST", f"/api/health/workouts/{workout['id']}/sets", bad)
        assert response.status_code == 422, bad

    patched = await owner.send(
        "PATCH", f"/api/health/sets/{one['id']}", {"reps": 6, "weight": None}
    )
    assert (
        patched.status_code == 200
        and patched.json()["reps"] == 6
        and patched.json()["weight"] is None
    )
    assert (await owner.send("PATCH", f"/api/health/sets/{one['id']}", {})).status_code == 422
    assert (
        await owner.send("PATCH", f"/api/health/sets/{one['id']}", {"kind": None})
    ).status_code == 422
    assert (
        await owner.send("PATCH", f"/api/health/sets/{uuid4()}", {"reps": 1})
    ).status_code == 404
    assert (await owner.send("PATCH", "/api/health/sets/nope", {"reps": 1})).status_code == 404
    await owner.send("PATCH", f"/api/health/sets/{one['id']}", {"weight": "230"})

    second = (
        await owner.send(
            "POST",
            f"/api/health/workouts/{workout['id']}/sets",
            {"exercise_id": PLANK, "seconds": 45},
        )
    ).json()
    undone = await owner.send("POST", f"/api/health/workouts/{workout['id']}/undo")
    assert undone.status_code == 200 and undone.json()["id"] == second["id"]
    assert (await owner.send("DELETE", f"/api/health/sets/{second['id']}")).status_code == 404

    finished = await owner.send(
        "POST", f"/api/health/workouts/{workout['id']}/finish", {"note": "good"}
    )
    assert finished.status_code == 200
    summary = finished.json()
    assert summary["sets"] == 1 and summary["duration_seconds"] == 0
    assert summary["volume_kg"] == "625.96"  # 230 lb x 6 reps
    assert summary["prs"] == {BENCH: ["heaviest_weight", "best_e1rm"]}
    assert (
        await owner.send("POST", f"/api/health/workouts/{workout['id']}/finish", {})
    ).status_code == 409

    got = (await owner.get(f"/api/health/workouts/{workout['id']}")).json()
    assert got["note"] == "good" and [s["id"] for s in got["sets"]] == [one["id"]]
    listing = (await owner.get("/api/health/workouts")).json()
    assert [w["id"] for w in listing] == [workout["id"], old["id"]]
    window = await owner.get("/api/health/workouts", params={"start": "2026-09-28"})
    assert [w["id"] for w in window.json()] == [workout["id"]]
    assert (await owner.get("/api/health/workouts", params={"start": "soon"})).status_code == 422
    assert (await owner.get("/api/health/workouts/nope")).status_code == 404

    last = (await owner.get(f"/api/health/exercises/{BENCH}/last")).json()
    assert [s["workout_id"] for s in last] == [workout["id"]]
    assert (await owner.get("/api/health/exercises/Nope/last")).status_code == 422
    progress = (await owner.get(f"/api/health/exercises/{BENCH}/progress")).json()
    assert [p["workout_id"] for p in progress] == [old["id"], workout["id"]]
    volume = (await owner.get("/api/health/volume", params={"week": "2026-09-30"})).json()
    assert volume["week_start"] == "2026-09-28"
    chest = next(m for m in volume["muscles"] if m["muscle"] == "chest")
    assert chest["sets"] == 1 and chest["volume_kg"] == "625.96"
    assert (await owner.get("/api/health/volume", params={"week": "x"})).status_code == 422
    assert (await owner.get("/api/health/volume")).status_code == 200

    assert (await owner.send("DELETE", f"/api/health/workouts/{workout['id']}")).status_code == 204
    assert (await owner.send("DELETE", f"/api/health/workouts/{workout['id']}")).status_code == 404


async def test_two_users_over_http_never_meet(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite=invite)).status_code == 200
    for who in (owner, member):
        assert (await who.send("POST", "/api/health/consent")).status_code == 201

    made = await owner.send(
        "POST",
        "/api/health/routines",
        {"name": "Mine", "slots": [{"exercise_id": BENCH, "sets": 3, "reps": 8}]},
    )
    routine_id = made.json()["id"]
    workout = (await owner.send("POST", "/api/health/workouts", {"routine_id": routine_id})).json()
    logged = (
        await owner.send(
            "POST",
            f"/api/health/workouts/{workout['id']}/sets",
            {"exercise_id": BENCH, "reps": 5, "weight": "100"},
        )
    ).json()

    assert (await member.get("/api/health/routines")).json() == []
    assert (await member.get("/api/health/workouts")).json() == []
    assert (await member.get("/api/health/plan")).json() is None
    assert (await member.get("/api/health/volume")).json()["muscles"] == []
    assert (await member.get(f"/api/health/exercises/{BENCH}/progress")).json() == []
    assert (await member.get(f"/api/health/exercises/{BENCH}/last")).json() == []
    assert (await member.get(f"/api/health/routines/{routine_id}")).status_code == 404
    assert (await member.get(f"/api/health/workouts/{workout['id']}")).status_code == 404
    assert (
        await member.send(
            "PUT",
            f"/api/health/routines/{routine_id}",
            {"name": "x", "slots": made.json()["slots"]},
        )
    ).status_code == 404
    assert (await member.send("DELETE", f"/api/health/routines/{routine_id}")).status_code == 404
    assert (
        await member.send("POST", "/api/health/workouts", {"routine_id": routine_id})
    ).status_code == 404
    assert (
        await member.send("PUT", "/api/health/plan", {"kind": "rotation", "rotation": [routine_id]})
    ).status_code == 422
    assert (
        await member.send(
            "POST", f"/api/health/workouts/{workout['id']}/sets", {"exercise_id": BENCH, "reps": 1}
        )
    ).status_code == 404
    assert (
        await member.send("PATCH", f"/api/health/sets/{logged['id']}", {"reps": 50})
    ).status_code == 404
    assert (await member.send("DELETE", f"/api/health/sets/{logged['id']}")).status_code == 404
    assert (
        await member.send("POST", f"/api/health/workouts/{workout['id']}/undo")
    ).status_code == 404
    assert (
        await member.send("POST", f"/api/health/workouts/{workout['id']}/finish", {})
    ).status_code == 404
    assert (await member.send("DELETE", f"/api/health/workouts/{workout['id']}")).status_code == 404

    # Consent is each user's own: withdrawing the member's leaves the owner's alone.
    await member.send("DELETE", "/api/health/consent")
    assert (await owner.get("/api/health/consent")).json()["consented_at"] is not None
    still = (await owner.get(f"/api/health/workouts/{workout['id']}")).json()
    assert [s["reps"] for s in still["sets"]] == [5]


# --- paging, batches, the unit preference and live records ---------------------------------------


async def test_exercise_pages_follow_the_ranking_and_never_overlap(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    whole = (await owner.get("/api/health/exercises?text=press&limit=12")).json()
    assert len(whole) == 12
    pages = []
    for offset in (0, 5, 10, 15):
        page = (await owner.get(f"/api/health/exercises?text=press&limit=5&offset={offset}")).json()
        assert len(page) <= 5
        pages.extend(page)
    assert [e["id"] for e in pages[:12]] == [e["id"] for e in whole]
    assert len({e["id"] for e in pages}) == len(pages)
    past_end = (await owner.get("/api/health/exercises?text=press&offset=100000")).json()
    assert past_end == []  # a short page is the end
    assert (await owner.get("/api/health/exercises?offset=-1")).status_code == 422


async def test_exercises_by_id_come_back_in_order_skipping_unknown(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    got = await owner.get(f"/api/health/exercises?ids={SQUAT},Nope,{BENCH},{SQUAT}, {PLANK},")
    assert got.status_code == 200
    assert [e["id"] for e in got.json()] == [SQUAT, BENCH, PLANK]
    assert got.json()[0]["images"][0].endswith(f"{SQUAT}/0.jpg")
    assert (await owner.get("/api/health/exercises?ids=")).json() == []
    assert (await owner.get("/api/health/exercises?ids=Nope")).json() == []

    many = ",".join(f"x{i}" for i in range(100))
    assert (await owner.get(f"/api/health/exercises?ids={many}")).status_code == 200
    assert (await owner.get(f"/api/health/exercises?ids={many},x100")).status_code == 422
    assert (await owner.get(f"/api/health/exercises?ids={BENCH}&text=squat")).status_code == 422
    assert (await owner.get(f"/api/health/exercises?ids={BENCH}&offset=1")).status_code == 422


async def test_the_weight_unit_preference_is_per_user_and_used_when_logging(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite=invite)).status_code == 200
    for who in (owner, member):
        await who.send("POST", "/api/health/consent")

    assert (await owner.get("/api/health/preferences")).json() == {"unit": "kg"}
    assert (await owner.send("PUT", "/api/health/preferences", {"unit": "lb"})).json() == {
        "unit": "lb"
    }
    assert (await owner.get("/api/health/preferences")).json() == {"unit": "lb"}
    assert (await member.get("/api/health/preferences")).json() == {"unit": "kg"}  # not theirs
    for bad in ({"unit": "stone"}, {}, {"unit": None}, {"unit": "lb", "x": 1}):
        assert (await owner.send("PUT", "/api/health/preferences", bad)).status_code == 422
    wrong = await owner.send(
        "PUT", "/api/health/preferences", {"unit": "kg"}, **{"X-CSRF-Token": "x"}
    )
    assert wrong.status_code == 403
    assert (await owner.get("/api/health/preferences")).json() == {"unit": "lb"}

    async def log(who: Any, body: dict[str, Any]) -> dict[str, Any]:
        workout = (await who.get("/api/health/today")).json()["in_progress"]
        if workout is None:
            workout = (await who.send("POST", "/api/health/workouts", {})).json()
        response = await who.send("POST", f"/api/health/workouts/{workout['id']}/sets", body)
        assert response.status_code == 201
        return dict(response.json())

    plain = {"exercise_id": BENCH, "reps": 5, "weight": "135"}
    assert (await log(owner, plain))["unit"] == "lb"  # their preference
    assert (await log(owner, {**plain, "unit": "kg"}))["unit"] == "kg"  # an explicit unit wins
    assert (await log(member, plain))["unit"] == "kg"  # the other user's is untouched

    await owner.send("PUT", "/api/health/preferences", {"unit": "kg"})
    assert (await log(owner, plain))["unit"] == "kg"
    assert (await member.get("/api/health/preferences")).json() == {"unit": "kg"}


async def test_the_preference_needs_no_consent_and_a_session(world: World) -> None:
    assert (await world.browser().get("/api/health/preferences")).status_code in (401, 403)
    owner = world.browser()
    await owner.login(OWNER)
    assert (await owner.send("PUT", "/api/health/preferences", {"unit": "lb"})).status_code == 200


async def test_live_records_match_the_summary_at_the_end(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await owner.send("POST", "/api/health/consent")

    async def run(
        at: datetime, sets: list[dict[str, Any]]
    ) -> tuple[list[list[Any]], dict[str, Any]]:
        world.clock.now = at
        workout = (await owner.send("POST", "/api/health/workouts", {})).json()
        flags = []
        for body in sets:
            world.clock.now += timedelta(minutes=3)
            response = await owner.send("POST", f"/api/health/workouts/{workout['id']}/sets", body)
            assert response.status_code == 201
            flags.append(response.json()["records"])
        world.clock.now += timedelta(minutes=3)
        done = await owner.send("POST", f"/api/health/workouts/{workout['id']}/finish", {})
        return flags, done.json()

    first, _ = await run(
        NOW - timedelta(days=7), [{"exercise_id": BENCH, "reps": 5, "weight": "100"}]
    )
    assert first == [[]]  # nothing to beat yet

    sets = [
        {"exercise_id": BENCH, "reps": 10, "weight": "40", "kind": "warmup"},
        {"exercise_id": BENCH, "reps": 5, "weight": "100"},  # equal: nothing
        {"exercise_id": BENCH, "reps": 6, "weight": "100"},  # reps and e1RM
        {"exercise_id": BENCH, "reps": 3, "weight": "110.5"},  # heaviest and e1RM
        {"exercise_id": BENCH, "reps": 3, "weight": "105"},  # under this workout's best
        {"exercise_id": BENCH, "reps": 1, "weight": "300", "kind": "warmup"},  # never counts
        {"exercise_id": SQUAT, "reps": 5, "weight": "150"},  # first time: nothing
    ]
    flags, summary = await run(NOW, sets)
    kinds = [[r["kind"] for r in f] for f in flags]
    assert kinds == [
        [],
        [],
        ["best_e1rm", "most_reps"],
        ["heaviest_weight", "best_e1rm"],
        [],
        [],
        [],
    ]
    assert flags[2][1] == {
        "kind": "most_reps",
        "exercise_id": BENCH,
        "value_text": "6 reps at 100 kg",
    }
    assert flags[3][0] == {
        "kind": "heaviest_weight",
        "exercise_id": BENCH,
        "value_text": "110.5 kg",
    }
    live: dict[str, set[str]] = {}
    for f in flags:
        for r in f:
            live.setdefault(r["exercise_id"], set()).add(r["kind"])
    assert summary["prs"] and live == {e: set(k) for e, k in summary["prs"].items()}
