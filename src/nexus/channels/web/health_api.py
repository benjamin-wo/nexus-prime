"""The Health department's API: Gym. The shared exercise catalogue, and the user's routines,
training plan, workouts and sets. Writing needs the user's consent (403 until they give it)."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import gym as gym_cases
from nexus.channels.web.security import Auth, Runtime
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.gym import Equipment, Exercise, Level, Muscle
from nexus.domain.gym_training import (
    PlanKind,
    PrKind,
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
    week_start,
)

router = APIRouter(prefix="/api/health")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExerciseOut(Model):
    id: str
    name: str
    category: str
    level: str
    equipment: str | None
    force: str | None
    mechanic: str | None
    primary_muscles: list[str]
    secondary_muscles: list[str]
    instructions: list[str]
    images: list[str]  # full URLs


def _exercise(e: Exercise, base_url: str) -> ExerciseOut:
    base = base_url if base_url.endswith("/") else base_url + "/"
    return ExerciseOut(
        id=e.id,
        name=e.name,
        category=e.category.value,
        level=e.level.value,
        equipment=e.equipment.value if e.equipment else None,
        force=e.force.value if e.force else None,
        mechanic=e.mechanic.value if e.mechanic else None,
        primary_muscles=[m.value for m in e.primary],
        secondary_muscles=[m.value for m in e.secondary],
        instructions=list(e.instructions),
        images=[base + image for image in e.images],
    )


@router.get("/exercises")
async def exercises(
    auth: Auth,
    web: Runtime,
    text: Annotated[str | None, Query(max_length=100)] = None,
    muscle: Muscle | None = None,
    equipment: Equipment | None = None,
    level: Level | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    ids: Annotated[str | None, Query(max_length=5000)] = None,
) -> list[ExerciseOut]:
    """Find exercises, best match first. Page with ``offset``: a page shorter than ``limit``
    is the last (there is no total). With ``ids`` (comma-separated, at most 100) it instead
    returns those exercises in the order given, skipping unknown ids; the filters, ``limit``
    and ``offset`` don't apply and can't be sent with it."""
    if ids is not None:
        if text or muscle or equipment or level or offset:
            raise InvalidInput("ids can't be combined with a search")
        wanted = [i.strip() for i in ids.split(",") if i.strip()]
        listed = await gym_cases.exercises_by_id(web.uow(), wanted)
        return [_exercise(e, web.settings.exercise_image_base_url) for e in listed]
    found = await gym_cases.find_exercises(
        web.uow(),
        text=text,
        muscle=muscle,
        equipment=equipment,
        level=level,
        limit=limit,
        offset=offset,
    )
    return [_exercise(e, web.settings.exercise_image_base_url) for e in found]


@router.get("/exercises/{exercise_id}")
async def exercise(exercise_id: str, auth: Auth, web: Runtime) -> ExerciseOut:
    found = await gym_cases.exercise(web.uow(), exercise_id)
    return _exercise(found, web.settings.exercise_image_base_url)


# --- consent --------------------------------------------------------------------------------


class ConsentOut(Model):
    consented_at: datetime | None  # None: not agreed (or withdrawn); writes are refused


@router.get("/consent")
async def get_consent(auth: Auth, web: Runtime) -> ConsentOut:
    return ConsentOut(consented_at=await gym_cases.consent(web.uow(), auth.user.id))


@router.post("/consent", status_code=201)
async def give_consent(auth: Auth, web: Runtime) -> ConsentOut:
    """Agree to Nexus keeping your health data. Doing it again changes nothing."""
    agreed = await gym_cases.give_consent(web.uow(), auth.user.id, now=web.clock())
    return ConsentOut(consented_at=agreed)


@router.delete("/consent", status_code=204)
async def withdraw_consent(auth: Auth, web: Runtime) -> None:
    """Take it back. What is stored stays until you delete it."""
    await gym_cases.withdraw_consent(web.uow(), auth.user.id)


# --- preferences --------------------------------------------------------------------------------


class HealthPreferencesIn(Model):
    unit: WeightUnit


class HealthPreferencesOut(Model):
    unit: WeightUnit  # what sets are logged in when none is given; kg until chosen


@router.get("/preferences")
async def get_preferences(auth: Auth, web: Runtime) -> HealthPreferencesOut:
    return HealthPreferencesOut(unit=await gym_cases.weight_unit(web.uow(), auth.user.id))


@router.put("/preferences")
async def put_preferences(
    body: HealthPreferencesIn, auth: Auth, web: Runtime
) -> HealthPreferencesOut:
    """Choose the weight unit. Needs no consent: it isn't health data."""
    return HealthPreferencesOut(
        unit=await gym_cases.set_weight_unit(web.uow(), auth.user.id, body.unit)
    )


# --- routines and the plan --------------------------------------------------------------------


class SlotIn(Model):
    exercise_id: str = Field(min_length=1, max_length=200)
    sets: int
    reps: int | None = None
    seconds: int | None = None
    rest_seconds: int = 90
    note: str | None = Field(None, max_length=1000)


class SlotOut(Model):
    exercise_id: str
    sets: int
    reps: int | None
    seconds: int | None
    rest_seconds: int
    note: str | None


class RoutineIn(Model):
    name: str = Field(max_length=200)
    slots: list[SlotIn] = Field(max_length=100)


class RoutineOut(Model):
    id: str
    name: str
    slots: list[SlotOut]
    created_at: datetime
    updated_at: datetime


def _routine(r: Routine) -> RoutineOut:
    return RoutineOut(
        id=str(r.id),
        name=r.name,
        slots=[SlotOut(**s.as_dict()) for s in r.slots],
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _slots(body: RoutineIn) -> list[Slot]:
    return [Slot(**s.model_dump()) for s in body.slots]


@router.get("/routines")
async def routines(auth: Auth, web: Runtime) -> list[RoutineOut]:
    return [_routine(r) for r in await gym_cases.routines(web.uow(), auth.user.id)]


@router.post("/routines", status_code=201)
async def create_routine(body: RoutineIn, auth: Auth, web: Runtime) -> RoutineOut:
    saved = await gym_cases.save_routine(
        web.uow(), auth.user.id, name=body.name, slots=_slots(body), now=web.clock()
    )
    return _routine(saved)


@router.get("/routines/{routine_id}")
async def get_routine(routine_id: str, auth: Auth, web: Runtime) -> RoutineOut:
    return _routine(await gym_cases.routine(web.uow(), auth.user.id, _uuid(routine_id, "routine")))


@router.put("/routines/{routine_id}")
async def replace_routine(routine_id: str, body: RoutineIn, auth: Auth, web: Runtime) -> RoutineOut:
    saved = await gym_cases.save_routine(
        web.uow(),
        auth.user.id,
        name=body.name,
        slots=_slots(body),
        routine_id=_uuid(routine_id, "routine"),
        now=web.clock(),
    )
    return _routine(saved)


@router.delete("/routines/{routine_id}", status_code=204)
async def delete_routine(routine_id: str, auth: Auth, web: Runtime) -> None:
    await gym_cases.delete_routine(
        web.uow(), auth.user.id, _uuid(routine_id, "routine"), now=web.clock()
    )


class PlanIn(Model):
    kind: PlanKind
    weekly: dict[int, str] = Field(default_factory=dict)  # weekday (Monday is 0) -> routine id
    rotation: list[str] = Field(default_factory=list, max_length=100)  # routine ids, in turn


class PlanOut(Model):
    kind: PlanKind
    weekly: dict[int, str]
    rotation: list[str]


def _plan(p: TrainingPlan) -> PlanOut:
    return PlanOut(
        kind=p.kind,
        weekly={d: str(r) for d, r in sorted(p.weekly.items())},
        rotation=[str(r) for r in p.rotation],
    )


@router.get("/plan")
async def get_plan(auth: Auth, web: Runtime) -> PlanOut | None:
    found = await gym_cases.plan(web.uow(), auth.user.id)
    return _plan(found) if found else None


@router.put("/plan")
async def put_plan(body: PlanIn, auth: Auth, web: Runtime) -> PlanOut:
    saved = await gym_cases.set_plan(
        web.uow(),
        auth.user.id,
        body.kind,
        weekly={d: _uuid(r, "routine") for d, r in body.weekly.items()},
        rotation=[_uuid(r, "routine") for r in body.rotation],
        now=web.clock(),
    )
    return _plan(saved)


class WorkoutOut(Model):
    id: str
    routine_id: str | None
    started_at: datetime
    finished_at: datetime | None
    note: str | None


def _workout(w: Workout) -> WorkoutOut:
    return WorkoutOut(
        id=str(w.id),
        routine_id=str(w.routine_id) if w.routine_id else None,
        started_at=w.started_at,
        finished_at=w.finished_at,
        note=w.note,
    )


class TodayOut(Model):
    routine: RoutineOut | None  # what the plan says for today; None on a rest day
    in_progress: WorkoutOut | None


@router.get("/today")
async def today(auth: Auth, web: Runtime) -> TodayOut:
    found = await gym_cases.todays_workout(web.uow(), auth.user.id, now=web.clock())
    return TodayOut(
        routine=_routine(found.routine) if found.routine else None,
        in_progress=_workout(found.in_progress) if found.in_progress else None,
    )


# --- workouts and sets ------------------------------------------------------------------------


class SetOut(Model):
    id: str
    workout_id: str
    exercise_id: str
    position: int
    kind: SetKind
    reps: int | None
    weight: str | None  # a decimal, with its unit
    unit: WeightUnit
    seconds: int | None
    rpe: str | None
    done_at: datetime


def _set(s: SetEntry) -> SetOut:
    return SetOut(
        id=str(s.id),
        workout_id=str(s.workout_id),
        exercise_id=s.exercise_id,
        position=s.position,
        kind=s.kind,
        reps=s.reps,
        weight=None if s.weight is None else str(s.weight),
        unit=s.unit,
        seconds=s.seconds,
        rpe=None if s.rpe is None else str(s.rpe),
        done_at=s.done_at,
    )


class WorkoutDetailOut(WorkoutOut):
    sets: list[SetOut]


def _detail(d: gym_cases.WorkoutDetail) -> WorkoutDetailOut:
    return WorkoutDetailOut(**_workout(d.workout).model_dump(), sets=[_set(s) for s in d.sets])


class WorkoutIn(Model):
    routine_id: str | None = None  # None: a freestyle workout


@router.post("/workouts", status_code=201)
async def start_workout(body: WorkoutIn, auth: Auth, web: Runtime) -> WorkoutOut:
    started = await gym_cases.start_workout(
        web.uow(),
        auth.user.id,
        routine_id=_uuid(body.routine_id, "routine") if body.routine_id else None,
        now=web.clock(),
    )
    return _workout(started)


@router.get("/workouts")
async def workouts(
    auth: Auth, web: Runtime, start: date | None = None, end: date | None = None
) -> list[WorkoutDetailOut]:
    """Workouts that started from ``start`` up to (not including) ``end``, newest first."""
    found = await gym_cases.workouts(web.uow(), auth.user.id, start=start, end=end)
    return [_detail(d) for d in found]


@router.get("/workouts/{workout_id}")
async def get_workout(workout_id: str, auth: Auth, web: Runtime) -> WorkoutDetailOut:
    return _detail(await gym_cases.workout(web.uow(), auth.user.id, _uuid(workout_id, "workout")))


class FinishIn(Model):
    note: str | None = Field(None, max_length=1000)


class SummaryOut(Model):
    workout_id: str
    duration_seconds: int
    sets: int  # working sets
    volume_kg: str
    prs: dict[str, list[str]]  # exercise id -> kinds of records


def _summary(s: WorkoutSummary) -> SummaryOut:
    return SummaryOut(
        workout_id=str(s.workout_id),
        duration_seconds=int(s.duration.total_seconds()),
        sets=s.sets,
        volume_kg=str(s.volume_kg.quantize(Decimal("0.01"))),
        prs={e: [k.value for k in kinds] for e, kinds in s.prs.items()},
    )


@router.post("/workouts/{workout_id}/finish")
async def finish_workout(workout_id: str, body: FinishIn, auth: Auth, web: Runtime) -> SummaryOut:
    summary = await gym_cases.finish_workout(
        web.uow(), auth.user.id, _uuid(workout_id, "workout"), note=body.note, now=web.clock()
    )
    return _summary(summary)


@router.delete("/workouts/{workout_id}", status_code=204)
async def discard_workout(workout_id: str, auth: Auth, web: Runtime) -> None:
    await gym_cases.discard_workout(web.uow(), auth.user.id, _uuid(workout_id, "workout"))


def _weight(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise InvalidInput("that weight isn't a number") from exc


class RecordOut(Model):
    kind: PrKind
    exercise_id: str
    value_text: str


class LoggedSetOut(SetOut):
    records: list[RecordOut]  # records this set sets; empty for a warm-up or none


def _record(r: Record) -> RecordOut:
    return RecordOut(kind=r.kind, exercise_id=r.exercise_id, value_text=r.value_text)


class SetIn(Model):
    exercise_id: str = Field(min_length=1, max_length=200)
    kind: SetKind = SetKind.WORKING
    reps: int | None = None
    weight: str | None = Field(None, max_length=16)
    unit: WeightUnit | None = None  # None: the user's preference, else kg
    seconds: int | None = None
    rpe: str | None = Field(None, max_length=8)


@router.post("/workouts/{workout_id}/sets", status_code=201)
async def log_set(workout_id: str, body: SetIn, auth: Auth, web: Runtime) -> LoggedSetOut:
    """Log a set; ``records`` lists the records it sets, as the summary at the end would."""
    logged = await gym_cases.log_set_with_records(
        web.uow(),
        auth.user.id,
        _uuid(workout_id, "workout"),
        exercise_id=body.exercise_id,
        kind=body.kind,
        reps=body.reps,
        weight=_weight(body.weight),
        unit=body.unit,
        seconds=body.seconds,
        rpe=_weight(body.rpe),
        now=web.clock(),
    )
    return LoggedSetOut(
        **_set(logged.entry).model_dump(), records=[_record(r) for r in logged.records]
    )


@router.post("/workouts/{workout_id}/undo")
async def undo_last_set(workout_id: str, auth: Auth, web: Runtime) -> SetOut:
    """Remove the set logged last and return it."""
    return _set(
        await gym_cases.undo_last_set(web.uow(), auth.user.id, _uuid(workout_id, "workout"))
    )


class SetPatch(Model):
    """Only the fields sent change; null clears reps, weight, seconds or rpe."""

    exercise_id: str | None = Field(None, min_length=1, max_length=200)
    kind: SetKind | None = None
    reps: int | None = None
    weight: str | None = Field(None, max_length=16)
    unit: WeightUnit | None = None
    seconds: int | None = None
    rpe: str | None = Field(None, max_length=8)
    done_at: datetime | None = None


@router.patch("/sets/{set_id}")
async def edit_set(set_id: str, body: SetPatch, auth: Auth, web: Runtime) -> SetOut:
    changes: dict[str, Any] = {}
    for name in body.model_fields_set:
        value = getattr(body, name)
        if value is None and name in {"exercise_id", "kind", "unit", "done_at"}:
            raise InvalidInput(f"{name} can't be cleared")
        changes[name] = _weight(value) if name in {"weight", "rpe"} else value
    edited = await gym_cases.edit_set(web.uow(), auth.user.id, _uuid(set_id, "set"), changes)
    return _set(edited)


@router.delete("/sets/{set_id}", status_code=204)
async def delete_set(set_id: str, auth: Auth, web: Runtime) -> None:
    await gym_cases.delete_set(web.uow(), auth.user.id, _uuid(set_id, "set"))


# --- history, progress and volume ---------------------------------------------------------------


@router.get("/exercises/{exercise_id}/last")
async def last_time(exercise_id: str, auth: Auth, web: Runtime) -> list[SetOut]:
    """The sets from the last workout that had this exercise, to prefill the next one."""
    return [_set(s) for s in await gym_cases.last_sets(web.uow(), auth.user.id, exercise_id)]


class ProgressOut(Model):
    workout_id: str
    at: datetime
    weight: str | None
    unit: WeightUnit
    reps: int | None
    e1rm_kg: str


def _progress(p: ProgressPoint) -> ProgressOut:
    return ProgressOut(
        workout_id=str(p.workout_id),
        at=p.at,
        weight=None if p.best.weight is None else str(p.best.weight),
        unit=p.best.unit,
        reps=p.best.reps,
        e1rm_kg=str(p.e1rm_kg.quantize(Decimal("0.01"))),
    )


@router.get("/exercises/{exercise_id}/progress")
async def exercise_progress(exercise_id: str, auth: Auth, web: Runtime) -> list[ProgressOut]:
    """The best set of each workout, oldest first."""
    found = await gym_cases.exercise_progress(web.uow(), auth.user.id, exercise_id)
    return [_progress(p) for p in found]


class MuscleVolumeOut(Model):
    muscle: Muscle
    volume_kg: str
    sets: int  # working sets that train it primarily
    secondary_sets: int


class VolumeOut(Model):
    week_start: date  # the Monday
    muscles: list[MuscleVolumeOut]  # most volume first


@router.get("/volume")
async def weekly_volume(auth: Auth, web: Runtime, week: date | None = None) -> VolumeOut:
    """Working volume per muscle for the Monday-to-Sunday week holding ``week`` (default:
    this one)."""
    day = week or web.clock().date()
    found = await gym_cases.weekly_volume(web.uow(), auth.user.id, day)
    ranked = sorted(found.items(), key=lambda kv: (-kv[1].volume_kg, kv[0].value))
    return VolumeOut(
        week_start=week_start(day),
        muscles=[
            MuscleVolumeOut(
                muscle=m,
                volume_kg=str(v.volume_kg.quantize(Decimal("0.01"))),
                sets=v.sets,
                secondary_sets=v.secondary_sets,
            )
            for m, v in ranked
        ],
    )


def _uuid(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise NotFound(f"no such {what}") from exc
