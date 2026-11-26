"""Health -> Gym: the shared exercise catalogue, and one user's routines, plan and workouts.

Writing health data needs the user's consent (``users.health_consent_at``): without it every
write raises ``ConsentRequired``. Withdrawing consent keeps what is stored, so deleting (a
routine, a set, a workout) never needs it: the user must always be able to remove their data.
The first write turns Health on in the menu (``users.show_health``), if they haven't decided.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.health_menu import note_health_write
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import Conflict, ConsentRequired, InvalidInput, NotFound, NothingToUndo
from nexus.domain.gym import Equipment, Exercise, Level, Muscle, search
from nexus.domain.gym_training import (
    MuscleVolume,
    PlanKind,
    ProgressPoint,
    Record,
    Routine,
    SetEntry,
    SetKind,
    Slot,
    TrainingPlan,
    WeightUnit,
    Workout,
    WorkoutSummary,
    best_set,
    e1rm_kg,
    last_time,
    progress,
    records_of_set,
    summarise,
    todays_routine,
    volume_by_muscle,
    week_start,
)
from nexus.domain.ledger import UserId

MAX_BATCH = 100


async def sync_catalogue(uow: UnitOfWork, catalogue: list[Exercise]) -> int:
    """Bring the table up to date with the bundled catalogue; returns rows written (0 when it
    already matches). Safe to run on every start, from several instances at once."""
    async with uow:
        written = await uow.gym.upsert_exercises(catalogue)
        await uow.commit()
        return written


async def find_exercises(
    uow: UnitOfWork,
    *,
    text: str | None = None,
    muscle: Muscle | None = None,
    equipment: Equipment | None = None,
    level: Level | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Exercise]:
    async with uow:
        found = await uow.gym.find_exercises(
            text=text, muscle=muscle, equipment=equipment, level=level
        )
    return search(
        found,
        text=text,
        muscle=muscle,
        equipment=equipment,
        level=level,
        limit=limit,
        offset=offset,
    )


async def exercises_by_id(uow: UnitOfWork, ids: Sequence[str]) -> list[Exercise]:
    """These exercises in the order given (repeats once), unknown ids skipped. One query."""
    wanted = list(dict.fromkeys(ids))
    if len(wanted) > MAX_BATCH:
        raise InvalidInput(f"at most {MAX_BATCH} ids at a time")
    async with uow:
        found = await uow.gym.get_exercises(wanted)
    return [found[i] for i in wanted if i in found]


async def exercise(uow: UnitOfWork, exercise_id: str) -> Exercise:
    async with uow:
        found = await uow.gym.get_exercise(exercise_id)
    if found is None:
        raise NotFound("no such exercise")
    return found


# --- consent --------------------------------------------------------------------------------


async def consent(uow: UnitOfWork, user_id: UserId) -> datetime | None:
    """When the user agreed to Nexus keeping their health data; None if they haven't."""
    async with uow:
        return await uow.gym.health_consent(user_id)


async def give_consent(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> datetime:
    """Agree. Doing it again keeps the first date. Returns when they agreed."""
    async with uow:
        agreed = await uow.gym.health_consent(user_id)
        if agreed is None:
            agreed = now
            await uow.gym.set_health_consent(user_id, now)
            await uow.commit()
        return agreed


async def withdraw_consent(uow: UnitOfWork, user_id: UserId) -> None:
    """Take the agreement back. Nothing stored is deleted: that is the user's separate choice."""
    async with uow:
        await uow.gym.set_health_consent(user_id, None)
        await uow.commit()


async def weight_unit(uow: UnitOfWork, user_id: UserId) -> WeightUnit:
    """The unit they log weights in: their choice, else kilograms."""
    async with uow:
        return await uow.gym.weight_unit(user_id) or WeightUnit.KG


async def set_weight_unit(uow: UnitOfWork, user_id: UserId, unit: WeightUnit) -> WeightUnit:
    """Choose the unit sets are logged in when none is given. A preference, not health data,
    so it needs no consent."""
    async with uow:
        await uow.gym.set_weight_unit(user_id, unit)
        await uow.commit()
    return unit


async def _begin_write(uow: UnitOfWork, user_id: UserId) -> None:
    """Inside the unit of work: refuse a write without consent."""
    if await uow.gym.health_consent(user_id) is None:
        raise ConsentRequired("agree to Nexus keeping your health data first")


async def _zone(uow: UnitOfWork, user_id: UserId) -> tzinfo:
    user = await uow.ledger.get_user(user_id)
    return ZoneInfo(user.timezone) if user else ZoneInfo("UTC")


async def _known_exercises(uow: UnitOfWork, ids: Sequence[str]) -> dict[str, Exercise]:
    wanted = list(dict.fromkeys(ids))
    found = await uow.gym.get_exercises(wanted)
    missing = [i for i in wanted if i not in found]
    if missing:
        raise InvalidInput(f"no such exercise: {missing[0]}")
    return found


# --- routines and the plan --------------------------------------------------------------------


async def save_routine(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    name: str,
    slots: Sequence[Slot],
    routine_id: UUID | None = None,
    now: datetime,
) -> Routine:
    """Create a routine, or (with ``routine_id``) replace the name and slots of one."""
    async with uow:
        await _begin_write(uow, user_id)
        await _known_exercises(uow, [s.exercise_id for s in slots])
        if routine_id is None:
            routine = Routine(uuid4(), user_id, name, tuple(slots), now, now)
            await uow.gym.add_routine(routine)
        else:
            old = await uow.gym.get_routine(user_id, routine_id)
            if old is None:
                raise NotFound("no such routine")
            routine = dataclasses.replace(old, name=name, slots=tuple(slots), updated_at=now)
            await uow.gym.update_routine(routine)
        await note_health_write(uow, user_id)
        await uow.commit()
        return routine


async def routines(uow: UnitOfWork, user_id: UserId) -> list[Routine]:
    async with uow:
        return await uow.gym.list_routines(user_id)


async def routine(uow: UnitOfWork, user_id: UserId, routine_id: UUID) -> Routine:
    async with uow:
        found = await uow.gym.get_routine(user_id, routine_id)
    if found is None:
        raise NotFound("no such routine")
    return found


async def delete_routine(
    uow: UnitOfWork, user_id: UserId, routine_id: UUID, *, now: datetime
) -> None:
    """Delete it and take it out of the plan; past workouts keep their sets."""
    async with uow:
        if not await uow.gym.delete_routine(user_id, routine_id):
            raise NotFound("no such routine")
        plan = await uow.gym.get_plan(user_id)
        if plan is not None and routine_id in plan.routine_ids():
            await uow.gym.save_plan(plan.without(routine_id), now)
        await uow.commit()


async def set_plan(
    uow: UnitOfWork,
    user_id: UserId,
    kind: PlanKind,
    *,
    weekly: Mapping[int, UUID] | None = None,
    rotation: Sequence[UUID] = (),
    now: datetime,
) -> TrainingPlan:
    """Replace the user's plan. Every routine named must be theirs."""
    plan = TrainingPlan(user_id, kind, dict(weekly or {}), tuple(rotation))
    async with uow:
        await _begin_write(uow, user_id)
        wanted = list(plan.routine_ids())
        if len(await uow.gym.routine_ids(user_id, wanted)) != len(wanted):
            raise InvalidInput("a plan can only use your own routines")
        await uow.gym.save_plan(plan, now)
        await note_health_write(uow, user_id)
        await uow.commit()
    return plan


async def plan(uow: UnitOfWork, user_id: UserId) -> TrainingPlan | None:
    async with uow:
        return await uow.gym.get_plan(user_id)


@dataclass(frozen=True, slots=True)
class Today:
    routine: Routine | None  # what the plan says for today; None on a rest day or without a plan
    in_progress: Workout | None  # a workout started and not finished


async def todays_workout(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> Today:
    async with uow:
        zone = await _zone(uow, user_id)
        saved = await uow.gym.get_plan(user_id)
        open_workout = await uow.gym.open_workout(user_id)
        routine_id = None
        if saved is not None:
            last = await uow.gym.last_routine_workout(user_id)
            routine_id = todays_routine(saved, now.astimezone(zone).date(), last, tz=zone)
        found = await uow.gym.get_routine(user_id, routine_id) if routine_id else None
    return Today(found, open_workout)


# --- workouts and sets ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkoutDetail:
    workout: Workout
    sets: tuple[SetEntry, ...]


async def start_workout(
    uow: UnitOfWork, user_id: UserId, *, routine_id: UUID | None = None, now: datetime
) -> Workout:
    """Begin a workout, from a routine or freestyle. One at a time: finish or discard first."""
    async with uow:
        await _begin_write(uow, user_id)
        if routine_id is not None and await uow.gym.get_routine(user_id, routine_id) is None:
            raise NotFound("no such routine")
        if await uow.gym.open_workout(user_id) is not None:
            raise Conflict("you already have a workout in progress")
        workout = Workout(uuid4(), user_id, routine_id, now)
        await uow.gym.add_workout(workout)
        await note_health_write(uow, user_id)
        await uow.commit()
        return workout


async def _open(uow: UnitOfWork, user_id: UserId, workout_id: UUID) -> Workout:
    workout = await uow.gym.get_workout(user_id, workout_id)
    if workout is None:
        raise NotFound("no such workout")
    if not workout.is_open:
        raise Conflict("that workout is finished")
    return workout


@dataclass(frozen=True, slots=True)
class LoggedSet:
    entry: SetEntry
    records: tuple[Record, ...]  # the records this set sets; never for a warm-up


async def log_set(
    uow: UnitOfWork,
    user_id: UserId,
    workout_id: UUID,
    *,
    exercise_id: str,
    kind: SetKind = SetKind.WORKING,
    reps: int | None = None,
    weight: Decimal | None = None,
    unit: WeightUnit | None = None,
    seconds: int | None = None,
    rpe: Decimal | None = None,
    now: datetime,
) -> SetEntry:
    """Add a set to the end of a workout in progress (see ``log_set_with_records``)."""
    return (
        await log_set_with_records(
            uow,
            user_id,
            workout_id,
            exercise_id=exercise_id,
            kind=kind,
            reps=reps,
            weight=weight,
            unit=unit,
            seconds=seconds,
            rpe=rpe,
            now=now,
        )
    ).entry


async def log_set_with_records(
    uow: UnitOfWork,
    user_id: UserId,
    workout_id: UUID,
    *,
    exercise_id: str,
    kind: SetKind = SetKind.WORKING,
    reps: int | None = None,
    weight: Decimal | None = None,
    unit: WeightUnit | None = None,
    seconds: int | None = None,
    rpe: Decimal | None = None,
    now: datetime,
) -> LoggedSet:
    """Add a set to the end of a workout in progress, and say which records it sets: against
    the history before this workout and the sets already in it, the same rules as the summary
    at ``finish_workout``. Without a ``unit`` the user's own is used, else kilograms."""
    async with uow:
        await _begin_write(uow, user_id)
        workout = await _open(uow, user_id, workout_id)
        await _known_exercises(uow, [exercise_id])
        unit = unit or await uow.gym.weight_unit(user_id) or WeightUnit.KG
        entry = SetEntry(
            uuid4(),
            workout_id,
            exercise_id,
            await uow.gym.next_position(user_id, workout_id),
            kind,
            reps,
            weight,
            unit,
            seconds,
            rpe,
            now,
        )
        records: list[Record] = []
        if entry.counts:
            earlier = (await uow.gym.sets_of_workouts(user_id, [workout_id]))[workout_id]
            history = await uow.gym.sets_of_exercises(
                user_id, [exercise_id], before=workout.started_at, exclude_workout=workout_id
            )
            records = records_of_set(entry, earlier, history)
        await uow.gym.add_set(user_id, entry)
        await note_health_write(uow, user_id)
        await uow.commit()
        return LoggedSet(entry, tuple(records))


EDITABLE = frozenset({"exercise_id", "kind", "reps", "weight", "unit", "seconds", "rpe", "done_at"})


async def edit_set(
    uow: UnitOfWork, user_id: UserId, set_id: UUID, changes: Mapping[str, Any]
) -> SetEntry:
    """Change the fields named (a None clears reps, weight, seconds or rpe). Sets of a
    finished workout can be corrected too."""
    unknown = set(changes) - EDITABLE
    if unknown or not changes:
        raise InvalidInput(
            "nothing to change" if not changes else f"can't change {sorted(unknown)}"
        )
    async with uow:
        await _begin_write(uow, user_id)
        old = await uow.gym.get_set(user_id, set_id)
        if old is None:
            raise NotFound("no such set")
        if "exercise_id" in changes:
            await _known_exercises(uow, [changes["exercise_id"]])
        entry = dataclasses.replace(old, **changes)  # validated again on construction
        await uow.gym.update_set(user_id, entry)
        await note_health_write(uow, user_id)
        await uow.commit()
        return entry


async def delete_set(uow: UnitOfWork, user_id: UserId, set_id: UUID) -> None:
    async with uow:
        if not await uow.gym.delete_set(user_id, set_id):
            raise NotFound("no such set")
        await uow.commit()


async def undo_last_set(uow: UnitOfWork, user_id: UserId, workout_id: UUID) -> SetEntry:
    """Remove the set logged last in a workout in progress and return it."""
    async with uow:
        await _open(uow, user_id, workout_id)
        last = await uow.gym.last_set(user_id, workout_id)
        if last is None:
            raise NothingToUndo("there's no set to undo")
        await uow.gym.delete_set(user_id, last.id)
        await uow.commit()
        return last


async def finish_workout(
    uow: UnitOfWork, user_id: UserId, workout_id: UUID, *, note: str | None = None, now: datetime
) -> WorkoutSummary:
    """End a workout and say how it went: how long, working sets, volume (kg) and records."""
    async with uow:
        await _begin_write(uow, user_id)
        workout = await _open(uow, user_id, workout_id)
        finished = dataclasses.replace(
            workout, finished_at=max(now, workout.started_at), note=note or workout.note
        )
        sets = (await uow.gym.sets_of_workouts(user_id, [workout_id]))[workout_id]
        history = await uow.gym.sets_of_exercises(
            user_id,
            list({s.exercise_id for s in sets}),
            before=workout.started_at,
            exclude_workout=workout_id,
        )
        await uow.gym.update_workout(finished)
        await note_health_write(uow, user_id)
        await uow.commit()
        return summarise(finished, sets, history)


async def discard_workout(uow: UnitOfWork, user_id: UserId, workout_id: UUID) -> None:
    """Throw a workout away, with its sets (works for a finished one too)."""
    async with uow:
        if not await uow.gym.delete_workout(user_id, workout_id):
            raise NotFound("no such workout")
        await uow.commit()


async def workouts(
    uow: UnitOfWork, user_id: UserId, *, start: date | None = None, end: date | None = None
) -> list[WorkoutDetail]:
    """Workouts that started from ``start`` up to (not including) ``end``, newest first."""
    async with uow:
        zone = await _zone(uow, user_id)
        found = await uow.gym.list_workouts(
            user_id,
            start=datetime.combine(start, time.min, zone) if start else None,
            end=datetime.combine(end, time.min, zone) if end else None,
        )
        sets = await uow.gym.sets_of_workouts(user_id, [w.id for w in found])
    return [WorkoutDetail(w, tuple(sets[w.id])) for w in found]


async def workout(uow: UnitOfWork, user_id: UserId, workout_id: UUID) -> WorkoutDetail:
    async with uow:
        found = await uow.gym.get_workout(user_id, workout_id)
        if found is None:
            raise NotFound("no such workout")
        sets = await uow.gym.sets_of_workouts(user_id, [workout_id])
    return WorkoutDetail(found, tuple(sets[workout_id]))


async def last_sets(uow: UnitOfWork, user_id: UserId, exercise_id: str) -> list[SetEntry]:
    """The sets of the last workout that had this exercise: what to prefill from."""
    async with uow:
        await _known_exercises(uow, [exercise_id])
        history = await uow.gym.sets_of_exercises(user_id, [exercise_id])
    return last_time(exercise_id, history)


async def exercise_progress(
    uow: UnitOfWork, user_id: UserId, exercise_id: str
) -> list[ProgressPoint]:
    """The best set (by estimated one-rep max) of each workout, oldest first."""
    async with uow:
        await _known_exercises(uow, [exercise_id])
        sets = await uow.gym.sets_of_exercises(user_id, [exercise_id])
    return progress(sets)


async def weekly_volume(uow: UnitOfWork, user_id: UserId, week: date) -> dict[Muscle, MuscleVolume]:
    """Working volume and set counts per muscle for the Monday-to-Sunday week holding ``week``."""
    async with uow:
        zone = await _zone(uow, user_id)
        start = datetime.combine(week_start(week), time.min, zone)
        sets = await uow.gym.sets_between(user_id, start, start + timedelta(days=8))
        catalogue = await uow.gym.get_exercises(list({s.exercise_id for s in sets}))
    return volume_by_muscle(sets, catalogue, week=week, tz=zone)


@dataclass(frozen=True, slots=True)
class Records:
    """The best a user has done on one exercise, from their working sets (warm-ups never count)."""

    exercise: Exercise
    sessions: int  # workouts with at least one working set of it
    heaviest: SetEntry | None  # the heaviest weight lifted (the earlier set on a tie)
    best_e1rm: SetEntry | None  # the set with the best estimated one-rep max
    e1rm_kg: Decimal | None
    most_reps: SetEntry | None  # the most reps in one set (the heavier set on a tie)


def _records(exercise: Exercise, sets: Sequence[SetEntry]) -> Records:
    working = [s for s in sets if s.counts]
    weighted = [s for s in working if s.weight_kg]
    heaviest = min(
        weighted,
        key=lambda s: (-(s.weight_kg or Decimal(0)), s.done_at, s.position),
        default=None,
    )
    counted = [s for s in working if s.reps is not None]
    most_reps = min(
        counted,
        key=lambda s: (-(s.reps or 0), -(s.weight_kg or Decimal(0)), s.done_at, s.position),
        default=None,
    )
    best = best_set(working)
    return Records(
        exercise,
        len({s.workout_id for s in working}),
        heaviest,
        best,
        e1rm_kg(best) if best else None,
        most_reps,
    )


async def records(uow: UnitOfWork, user_id: UserId, exercise_id: str) -> Records:
    """The user's records on one exercise."""
    async with uow:
        found = await _known_exercises(uow, [exercise_id])
        sets = await uow.gym.sets_of_exercises(user_id, [exercise_id])
    return _records(found[exercise_id], sets)


async def all_records(uow: UnitOfWork, user_id: UserId, *, limit: int = 10) -> list[Records]:
    """Records on the exercises the user has done most (by working sets), most done first."""
    async with uow:
        done = await uow.gym.list_workouts(user_id, start=None, end=None)
        by_workout = await uow.gym.sets_of_workouts(user_id, [w.id for w in done])
        by_exercise: dict[str, list[SetEntry]] = {}
        for sets in by_workout.values():
            for s in sets:
                by_exercise.setdefault(s.exercise_id, []).append(s)
        catalogue = await uow.gym.get_exercises(list(by_exercise))
    ranked = sorted(
        (e for e in by_exercise if e in catalogue),
        key=lambda e: (-sum(1 for s in by_exercise[e] if s.counts), e),
    )
    found = [_records(catalogue[e], by_exercise[e]) for e in ranked]
    return [r for r in found if r.best_e1rm or r.heaviest or r.most_reps][:limit]


async def exercises_named(uow: UnitOfWork, ids: Sequence[str]) -> dict[str, Exercise]:
    """The catalogue entries for these ids (an id that isn't there is left out)."""
    async with uow:
        return await uow.gym.get_exercises(list(dict.fromkeys(ids)))
