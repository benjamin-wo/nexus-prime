"""Health: Gym tools. Every figure in their text comes from ``application.gym`` and
``agent.gym_text``; the model quotes it and never works it out."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import Field

from nexus.agent import gym_text
from nexus.agent.tools.core import Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.health import (
    decimal,
    has_consent,
    health_off,
    local_day,
    log_day,
    need_consent,
)
from nexus.application import gym as gym_cases
from nexus.domain import gym_entry
from nexus.domain.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    NothingToUndo,
)
from nexus.domain.gym import Equipment, Exercise, Muscle
from nexus.domain.gym_training import SetEntry, SetKind, WeightUnit, volume_kg
from nexus.domain.ledger import MenuSection


def enum_value[E: StrEnum](kind: type[E], value: str | None, what: str) -> E | None:
    if not value:
        return None
    try:
        return kind(value.strip().casefold())
    except ValueError as exc:
        raise InvalidInput(
            f"{value!r} isn't a {what}; use one of: {', '.join(m.value for m in kind)}"
        ) from exc


async def resolve_exercise(ctx: ToolContext, text: str) -> Exercise:
    """The one exercise a name means: an id, a common name (bench, squat), or the single
    match. Several matches are an error that lists them, so the model asks the user."""
    said = text.strip()
    if not said:
        raise InvalidInput("which exercise?")
    if " " not in said:
        try:
            return await gym_cases.exercise(ctx.uow(), said)
        except NotFound:
            pass
    if (alias := gym_entry.alias_id(said)) is not None:
        try:
            return await gym_cases.exercise(ctx.uow(), alias)
        except NotFound:  # pragma: no cover - the aliases are checked against the catalogue
            pass
    found = await gym_cases.find_exercises(ctx.uow(), text=said, limit=6)
    if not found:
        raise NotFound(f"no exercise matches {said!r}: try find_exercise with fewer words")
    if (one := gym_entry.unambiguous(said, found)) is not None:
        return one
    options = "; ".join(f"{e.name} [{e.id}]" for e in found)
    raise InvalidInput(
        f"{said!r} could mean several exercises: {options}. Ask the user which one, then call "
        "again with its id as the exercise."
    )


class FindExerciseArgs(Args):
    query: str | None = Field(None, description="Part of the exercise's name, e.g. 'bench'")
    muscle: str | None = Field(None, description="Only exercises that work this muscle")
    equipment: str | None = Field(None, description="Only exercises with this equipment")


async def _find_exercise(ctx: ToolContext, a: FindExerciseArgs) -> ToolResult:
    muscle = enum_value(Muscle, a.muscle, "muscle")
    equipment = enum_value(Equipment, a.equipment, "kind of equipment")
    if not (a.query or muscle or equipment):
        raise InvalidInput("give a name, a muscle or equipment to look for")
    found = await gym_cases.find_exercises(
        ctx.uow(), text=a.query or None, muscle=muscle, equipment=equipment, limit=8
    )
    if a.query and not muscle and not equipment and (alias := gym_entry.alias_id(a.query)):
        usual = await gym_cases.exercises_named(ctx.uow(), [alias])
        if alias in usual:
            found = [usual[alias], *(e for e in found if e.id != alias)][:8]
    if not found:
        return ToolResult("No exercise matches that. Try fewer words or a muscle.")
    lines = [
        f"• {e.name} [{e.id}] ({e.equipment.value if e.equipment else 'no equipment'}; "
        f"works {', '.join(m.value for m in e.primary)})"
        for e in found
    ]
    return ToolResult("Best matches first:\n" + "\n".join(lines))


async def _todays_workout(ctx: ToolContext, _: NoArgs) -> ToolResult:
    today = await gym_cases.todays_workout(ctx.uow(), ctx.user.id, now=ctx.now)
    lines: list[str] = []
    if today.in_progress is not None:
        detail = await gym_cases.workout(ctx.uow(), ctx.user.id, today.in_progress.id)
        working = sum(1 for s in detail.sets if s.counts)
        started = today.in_progress.started_at.astimezone(ctx.tz)
        lines.append(
            f"A workout is in progress, started at {started:%H:%M} on "
            f"{gym_text.day_text(started.date(), ctx.today())}, with {working} working "
            f"{'set' if working == 1 else 'sets'} so far."
        )
    if today.routine is None:
        if await gym_cases.plan(ctx.uow(), ctx.user.id) is None:
            lines.append(
                "No plan: the user hasn't set up a training plan. Logging sets works without "
                "one; a plan can be set up in the Health section of the app."
            )
        else:
            lines.append("Rest day: the plan has nothing for today.")
        return ToolResult("\n".join(lines))
    names = await gym_cases.exercises_named(ctx.uow(), [s.exercise_id for s in today.routine.slots])
    lines.append(f"Today's routine from the plan: {today.routine.name}.")
    for n, slot in enumerate(today.routine.slots, 1):
        name = names[slot.exercise_id].name if slot.exercise_id in names else slot.exercise_id
        target = f"{slot.sets} x {slot.reps}" if slot.reps else f"{slot.sets} x {slot.seconds} s"
        lines.append(f"{n}. {name}: {target}, rest {slot.rest_seconds} s")
    return ToolResult("\n".join(lines))


class ExerciseArgs(Args):
    exercise: str = Field(description="The exercise's name as the user said it, or its id")


async def _last_time(ctx: ToolContext, a: ExerciseArgs) -> ToolResult:
    found = await resolve_exercise(ctx, a.exercise)
    sets = await gym_cases.last_sets(ctx.uow(), ctx.user.id, found.id)
    if not sets:
        return ToolResult(f"No sets of {found.name} logged yet.")
    day = gym_text.day_text(local_day(ctx, sets[0].done_at), ctx.today())
    return ToolResult(
        f"Last time, {day}, {found.name}: {gym_text.describe_sets(sets)}.", buttons=None
    )


def _record_line(r: gym_cases.Records, today: date, tz: ZoneInfo) -> str:
    def when(s: SetEntry) -> str:
        return gym_text.day_text(s.done_at.astimezone(tz).date(), today)

    def one(s: SetEntry) -> str:
        at = f" at {gym_text.weight_text(s.weight, s.unit)}" if s.weight else ""
        return f"{s.reps} reps{at}" if s.reps is not None else f"{s.seconds} s{at}"

    parts = []
    if r.heaviest is not None and r.heaviest.weight is not None:
        top = r.heaviest
        parts.append(
            f"heaviest {gym_text.weight_text(top.weight or Decimal(0), top.unit)} for "
            f"{top.reps if top.reps is not None else top.seconds}"
            f"{' reps' if top.reps is not None else ' s'} ({when(top)})"
        )
    if r.best_e1rm is not None and r.e1rm_kg is not None:
        parts.append(
            f"best estimated one-rep max {gym_text.kg_text(r.e1rm_kg)} "
            f"(from {one(r.best_e1rm)}, {when(r.best_e1rm)})"
        )
    if r.most_reps is not None:
        parts.append(f"most reps in one set: {one(r.most_reps)} ({when(r.most_reps)})")
    return f"{r.exercise.name} [{r.sessions} workouts]: " + "; ".join(parts)


class OptionalExerciseArgs(Args):
    exercise: str | None = Field(
        None, description="The exercise's name as the user said it; leave out for all lifts"
    )


async def _personal_records(ctx: ToolContext, a: OptionalExerciseArgs) -> ToolResult:
    note = " (Estimated one-rep maxes use the Epley formula and are in kg.)"
    if a.exercise:
        found = await resolve_exercise(ctx, a.exercise)
        rec = await gym_cases.records(ctx.uow(), ctx.user.id, found.id)
        if rec.sessions == 0:
            return ToolResult(f"No working sets of {found.name} logged yet, so no records.")
        return ToolResult(_record_line(rec, ctx.today(), ctx.tz) + "." + note)
    every = await gym_cases.all_records(ctx.uow(), ctx.user.id)
    if not every:
        return ToolResult("No working sets logged yet, so no records.")
    lines = [f"• {_record_line(r, ctx.today(), ctx.tz)}" for r in every]
    return ToolResult("Records on the lifts done most:\n" + "\n".join(lines) + note)


class HistoryArgs(Args):
    range: str = Field(
        description=f"Which days: {gym_entry.RANGES}",
    )


async def _workout_history(ctx: ToolContext, a: HistoryArgs) -> ToolResult:
    first, after = gym_entry.parse_range(a.range, ctx.today())
    found = await gym_cases.workouts(ctx.uow(), ctx.user.id, start=first, end=after)
    span = f"{gym_text.day_text(first, ctx.today())} to " + gym_text.day_text(
        after - timedelta(days=1), ctx.today()
    )
    if not found:
        return ToolResult(f"No workouts from {span}.")
    names = await gym_cases.exercises_named(
        ctx.uow(), [s.exercise_id for d in found for s in d.sets]
    )
    lines = []
    for d in found[:15]:
        working = sum(1 for s in d.sets if s.counts)
        volume = sum((volume_kg(s) for s in d.sets), Decimal(0))
        shown = list(
            dict.fromkeys(names[s.exercise_id].name for s in d.sets if s.exercise_id in names)
        )
        took = (
            gym_text.duration_text(d.workout.finished_at - d.workout.started_at)
            if d.workout.finished_at
            else "in progress"
        )
        day = gym_text.day_text(local_day(ctx, d.workout.started_at), ctx.today())
        weight = f", {gym_text.kg_text(volume)} volume" if volume else ""
        lines.append(f"• {day}: {working} working sets{weight}, {took}: {', '.join(shown)}")
    total_sets = sum(1 for d in found for s in d.sets if s.counts)
    total = sum((volume_kg(s) for d in found for s in d.sets), Decimal(0))
    more = f"\n(and {len(found) - 15} older ones)" if len(found) > 15 else ""
    return ToolResult(
        f"Workouts from {span}, newest first:\n" + "\n".join(lines) + more
        + f"\nIn all: {len(found)} {'workout' if len(found) == 1 else 'workouts'}, "
        f"{total_sets} working {'set' if total_sets == 1 else 'sets'}, "
        f"{gym_text.kg_text(total)} volume (reps x weight of working sets)."
    )  # fmt: skip


class WeekArgs(Args):
    week: str | None = Field(
        None, description="'this week' (the default), 'last week' or a date in the week"
    )


async def _weekly_volume(ctx: ToolContext, a: WeekArgs) -> ToolResult:
    monday = gym_entry.parse_week(a.week, ctx.today())
    span = f"{gym_text.day_text(monday, ctx.today())} to " + gym_text.day_text(
        monday + timedelta(days=6), ctx.today()
    )
    found = await gym_cases.weekly_volume(ctx.uow(), ctx.user.id, monday)
    if not found:
        return ToolResult(f"No working sets logged in the week of {span}.")
    ranked = sorted(found.items(), key=lambda m: (-m[1].volume_kg, -m[1].sets, m[0].value))
    lines = []
    for muscle, v in ranked:
        side = f" (+{v.secondary_sets} as a secondary muscle)" if v.secondary_sets else ""
        lines.append(f"• {muscle.value}: {gym_text.kg_text(v.volume_kg)}, {v.sets} sets{side}")
    return ToolResult(
        f"Working volume per muscle, week of {span} (reps x weight; a secondary muscle gets "
        "half):\n" + "\n".join(lines)
    )


class SetArgs(Args):
    reps: int | None = Field(None, description="Reps in the set (or seconds, for timed ones)")
    seconds: int | None = Field(None, description="Seconds held, for a timed set like a plank")
    weight: str | None = Field(
        None, description="The weight the user said, as they said it; leave out for bodyweight"
    )
    unit: Literal["kg", "lb"] | None = Field(None, description="Only if the user said it")
    rpe: str | None = Field(None, description="RPE 1 to 10, only if the user said it")
    kind: Literal["working", "warmup"] = "working"
    count: int = Field(1, ge=1, le=gym_entry.MAX_SETS_AT_ONCE, description="'3x5': count 3")


class LogSetsArgs(Args):
    exercise: str = Field(description="The exercise as the user said it ('bench'), or its id")
    sets: list[SetArgs] = Field(
        default_factory=list,
        description="The sets, with the numbers the user gave. 'same again': the sets of "
        "the last log_sets in this chat, or from last_time if there's none",
    )
    entry: str | None = Field(
        None,
        description="Instead of sets: the user's own words for them, like '3x5 at 80' or "
        "'3 by 8 at 60kg RPE 8'. Read by code",
    )
    when: str | None = Field(
        None, description="The day, if not today and the user said so: 2026-09-14 or yesterday"
    )


def _set_specs(a: LogSetsArgs) -> list[gym_entry.ParsedSet]:
    if a.sets and a.entry:
        raise InvalidInput("give the sets or the entry, not both")
    if a.entry:
        parsed = gym_entry.parse_sets(a.entry)
    elif a.sets:
        parsed = []
        for s in a.sets:
            one = gym_entry.ParsedSet(
                s.reps,
                s.seconds,
                decimal(s.weight, "the weight"),
                WeightUnit(s.unit) if s.unit else None,
                decimal(s.rpe, "the RPE"),
                SetKind(s.kind),
            )
            parsed.extend([one] * s.count)
    else:
        raise InvalidInput("no sets given: ask the user what they lifted")
    if len(parsed) > gym_entry.MAX_SETS_AT_ONCE:
        raise InvalidInput(f"log at most {gym_entry.MAX_SETS_AT_ONCE} sets at a time")
    return [replace(p, unit=p.unit or WeightUnit.KG) for p in parsed]


def _checked(exercise_id: str, specs: list[gym_entry.ParsedSet], at: datetime) -> None:
    """Refuse bad sets before anything is written (a set of three must not half-save)."""
    for position, p in enumerate(specs, 1):
        SetEntry(
            uuid4(), uuid4(), exercise_id, position, p.kind, p.reps, p.weight,
            p.unit or WeightUnit.KG, p.seconds, p.rpe, at,
        )  # fmt: skip


async def _describe_log_sets(ctx: ToolContext, a: LogSetsArgs) -> str:
    await need_consent(ctx)
    found = await resolve_exercise(ctx, a.exercise)
    specs = _set_specs(a)
    at = log_day(ctx, a.when)
    _checked(found.id, specs, at or ctx.now)
    day = f" on {at.astimezone(ctx.tz):%a %-d %b}" if at else ""
    return f"Log {found.name}: {gym_text.describe_sets(specs)}{day}?"


async def _log_sets(ctx: ToolContext, a: LogSetsArgs) -> ToolResult:
    if not await has_consent(ctx):
        return health_off()
    found = await resolve_exercise(ctx, a.exercise)
    specs = _set_specs(a)
    at = log_day(ctx, a.when)
    done_at = at or ctx.now
    _checked(found.id, specs, done_at)
    today = await gym_cases.todays_workout(ctx.uow(), ctx.user.id, now=ctx.now)
    if at is None:
        workout = today.in_progress
        if workout is None:
            planned = today.routine and any(s.exercise_id == found.id for s in today.routine.slots)
            workout = await gym_cases.start_workout(
                ctx.uow(), ctx.user.id,
                routine_id=today.routine.id if today.routine and planned else None, now=done_at,
            )  # fmt: skip
    else:
        if today.in_progress is not None:
            raise Conflict(
                "a workout is in progress: finish it before logging sets for an earlier day"
            )
        workout = await gym_cases.start_workout(ctx.uow(), ctx.user.id, now=done_at)
    for p in specs:
        await gym_cases.log_set(
            ctx.uow(), ctx.user.id, workout.id,
            exercise_id=found.id, kind=p.kind, reps=p.reps, weight=p.weight,
            unit=p.unit or WeightUnit.KG, seconds=p.seconds, rpe=p.rpe, now=done_at,
        )  # fmt: skip
    logged = f"Logged {found.name}: {gym_text.describe_sets(specs)}."
    if at is not None:
        await gym_cases.finish_workout(ctx.uow(), ctx.user.id, workout.id, now=done_at)
        day = gym_text.day_text(local_day(ctx, at), ctx.today())
        return ToolResult(f"{logged} Saved as a finished workout on {day}.", wrote=True)
    detail = await gym_cases.workout(ctx.uow(), ctx.user.id, workout.id)
    working = sum(1 for s in detail.sets if s.counts)
    volume = sum((volume_kg(s) for s in detail.sets), Decimal(0))
    so_far = f" and {gym_text.kg_text(volume)} volume" if volume else ""
    return ToolResult(
        f"{logged} Workout in progress: {working} working {'set' if working == 1 else 'sets'}"
        f"{so_far} so far. Records are checked when the workout is finished.",
        wrote=True,
    )


async def _open_workout(ctx: ToolContext) -> gym_cases.WorkoutDetail:
    today = await gym_cases.todays_workout(ctx.uow(), ctx.user.id, now=ctx.now)
    if today.in_progress is None:
        raise NotFound("there's no workout in progress")
    return await gym_cases.workout(ctx.uow(), ctx.user.id, today.in_progress.id)


async def _describe_finish(ctx: ToolContext, _: NoArgs) -> str:
    await need_consent(ctx)
    detail = await _open_workout(ctx)
    working = sum(1 for s in detail.sets if s.counts)
    return f"Finish your workout ({working} working {'set' if working == 1 else 'sets'} logged)?"


async def _finish_workout(ctx: ToolContext, _: NoArgs) -> ToolResult:
    if not await has_consent(ctx):
        return health_off()
    detail = await _open_workout(ctx)
    summary = await gym_cases.finish_workout(ctx.uow(), ctx.user.id, detail.workout.id, now=ctx.now)
    named = await gym_cases.exercises_named(ctx.uow(), list(summary.prs))
    names = {i: e.name for i, e in named.items()}
    volume = f", {gym_text.kg_text(summary.volume_kg)} volume" if summary.volume_kg else ""
    records = (
        f" New records: {gym_text.pr_text(summary.prs, names)}."
        if summary.prs
        else " No new records this time."
    )
    return ToolResult(
        f"Workout finished: {gym_text.duration_text(summary.duration)}, {summary.sets} working "
        f"{'set' if summary.sets == 1 else 'sets'}{volume}.{records}",
        wrote=True,
    )


async def _describe_undo_set(ctx: ToolContext, _: NoArgs) -> str:
    detail = await _open_workout(ctx)
    if not detail.sets:
        raise NothingToUndo("there's no set to undo")
    last = detail.sets[-1]
    named = await gym_cases.exercises_named(ctx.uow(), [last.exercise_id])
    name = named[last.exercise_id].name if last.exercise_id in named else last.exercise_id
    return f"Remove your last set ({name}: {gym_text.describe_sets([last])})?"


async def _undo_last_set(ctx: ToolContext, _: NoArgs) -> ToolResult:
    # No consent check: taking a set out is deleting the user's own data, always allowed.
    detail = await _open_workout(ctx)
    removed = await gym_cases.undo_last_set(ctx.uow(), ctx.user.id, detail.workout.id)
    named = await gym_cases.exercises_named(ctx.uow(), [removed.exercise_id])
    name = named[removed.exercise_id].name if removed.exercise_id in named else removed.exercise_id
    return ToolResult(
        f"Removed the last set ({name}: {gym_text.describe_sets([removed])}).", wrote=True
    )


SPECS = (
    ToolSpec(
        "find_exercise",
        "Look up exercises in the catalogue by name, muscle or equipment: the best matches "
        "with their ids. Read-only.",
        FindExerciseArgs,
        _find_exercise,
    ),
    ToolSpec(
        "todays_workout",
        "Today's routine from the user's training plan (exercises, sets, reps), or that "
        "there is no plan or it's a rest day, and any workout in progress. Read-only.",
        NoArgs,
        _todays_workout,
    ),
    ToolSpec(
        "last_time",
        "The sets the user did last time on one exercise, by name ('squats'). If the name "
        "could be several exercises it lists them: ask which. Read-only.",
        ExerciseArgs,
        _last_time,
    ),
    ToolSpec(
        "personal_records",
        "The user's records on one exercise (heaviest weight, best estimated one-rep max, "
        "most reps), or on the lifts they do most. Worked out in code. Read-only.",
        OptionalExerciseArgs,
        _personal_records,
    ),
    ToolSpec(
        "workout_history",
        "The user's past workouts in a range of days, with sets and volume. Read-only.",
        HistoryArgs,
        _workout_history,
    ),
    ToolSpec(
        "weekly_volume",
        "Working volume and sets per muscle for a week. Read-only.",
        WeekArgs,
        _weekly_volume,
    ),
    ToolSpec(
        "log_sets",
        "Log sets the user did, onto their workout in progress (one is started if there "
        "isn't one). Use the numbers the user gave, never guess a weight or reps. "
        "Wellness tracking only. Asks the user to confirm.",
        LogSetsArgs,
        _log_sets,
        confirm=_describe_log_sets,
    ),
    ToolSpec(
        "finish_workout",
        "End the user's workout in progress and report how long it took, the sets, the "
        "volume and any new records. Asks the user to confirm.",
        NoArgs,
        _finish_workout,
        confirm=_describe_finish,
    ),
    ToolSpec(
        "undo_last_set",
        "Take out the set logged last in the workout in progress. Asks the user to confirm.",
        NoArgs,
        _undo_last_set,
        confirm=_describe_undo_set,
    ),
)


READ_ONLY: frozenset[str] = frozenset(
    {
        "find_exercise",
        "last_time",
        "personal_records",
        "todays_workout",
        "weekly_volume",
        "workout_history",
    }
)

MENU: dict[str, MenuSection] = dict.fromkeys(
    (
        "find_exercise",
        "finish_workout",
        "last_time",
        "log_sets",
        "personal_records",
        "todays_workout",
        "undo_last_set",
        "weekly_volume",
        "workout_history",
    ),
    MenuSection.HEALTH,
)
