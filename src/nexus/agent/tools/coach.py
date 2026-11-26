"""Health: the Gym coach. The coach proposes; it never applies. The model fills a
structured plan, code checks it (``domain.coach``) and builds the confirm card, and only a
confirmed card saves anything. Progression figures come from
``domain.coach.suggest_progression``, never from the model."""

from pydantic import Field

from nexus.agent.tools.core import Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.gym import enum_value, resolve_exercise
from nexus.agent.tools.health import (
    ai_blocked,
    has_consent,
    health_off,
    need_consent,
)
from nexus.application import coach as coach_cases
from nexus.domain import coach as coach_rules
from nexus.domain.errors import (
    ConsentRequired,
    InvalidInput,
    NexusError,
)
from nexus.domain.gym import Equipment
from nexus.domain.health_safety import red_flags
from nexus.domain.ledger import MenuSection

NO_PROGRAMMING_FOR_PAIN = (
    "the user mentioned pain or an injury, so don't draft or change any training. Tell them "
    "kindly that a doctor or physiotherapist is the right person to ask, and offer to log or "
    "look up their training afterwards."
)


UNDER_18 = (
    "the user may be under 18, so don't draft a plan. Say kindly that a qualified coach or "
    "PE teacher is the right person to build a programme for them, and offer to log their "
    "workouts instead."
)


NEEDS_AGE = (
    "no birth year is known: ask the user for their birth year (it is used only to check they "
    "are 18 or over, and is not stored by this tool), then call again with birth_year"
)


class DraftSlotArgs(Args):
    exercise_query: str | None = Field(
        None, description="The exercise as the user would say it ('bench press'); or use the id"
    )
    exercise_id: str | None = Field(None, description="An id from find_exercise")
    sets: int = Field(description="Working sets")
    reps: int | None = Field(None, description="Target reps per set (not with seconds)")
    seconds: int | None = Field(None, description="Target seconds per set, for holds like planks")
    rest_seconds: int = Field(90, description="Rest between sets, in seconds")


class DraftRoutineArgs(Args):
    name: str = Field(description="A short name ('Push', 'Full body A')")
    slots: list[DraftSlotArgs] = Field(
        max_length=coach_rules.MAX_SLOTS_PER_ROUTINE, description="The exercises, in order"
    )


class ScheduleDayArgs(Args):
    day: str = Field(description="mon, tue, wed, thu, fri, sat or sun")
    routine: str = Field(description="The name of one of the routines")


class DraftScheduleArgs(Args):
    weekly: list[ScheduleDayArgs] = Field(
        default_factory=list, max_length=7, description="A routine on each training weekday"
    )
    rotation: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Instead of weekdays: routine names in turn (A, B, A...)",
    )


class DraftPlanArgs(Args):
    routines: list[DraftRoutineArgs] = Field(max_length=coach_rules.MAX_ROUTINES)
    schedule: DraftScheduleArgs
    days_per_week: int | None = Field(None, description="Only what the user said, if not saved")
    session_minutes: int | None = Field(None, description="Only what the user said, if not saved")
    equipment: list[str] | None = Field(
        None, description="Only what the user said, if not saved: barbell, dumbbell, machine..."
    )
    experience: str | None = Field(None, description="beginner, intermediate or advanced")
    focus: str | None = Field(None, description="strength, hypertrophy or general")
    birth_year: int | None = Field(None, description="Only if the user said it and none is saved")


async def _training_profile(ctx: ToolContext, a: DraftPlanArgs) -> coach_rules.TrainingProfile:
    """The saved inputs, with whatever the user just said on top. Missing ones are asked for."""
    saved = await coach_cases.training_profile(ctx.uow(), ctx.user.id)
    days = (
        a.days_per_week if a.days_per_week is not None else (saved.days_per_week if saved else None)
    )
    minutes = (
        a.session_minutes
        if a.session_minutes is not None
        else (saved.session_minutes if saved else None)
    )
    equipment = saved.equipment if saved else None
    if a.equipment is not None:
        said = (enum_value(Equipment, x, "kind of equipment") for x in a.equipment)
        equipment = tuple(e for e in said if e)
    experience = enum_value(coach_rules.Experience, a.experience, "experience level") or (
        saved.experience if saved else None
    )
    focus = enum_value(coach_rules.Focus, a.focus, "focus") or (saved.focus if saved else None)
    if days is None or minutes is None or equipment is None or not experience or not focus:
        missing = [
            name
            for name, value in (
                ("days per week", days),
                ("session length in minutes", minutes),
                ("equipment (body weight only is fine)", equipment),
                ("experience (beginner, intermediate or advanced)", experience),
                ("focus (strength, hypertrophy or general)", focus),
            )
            if value is None
        ]
        raise InvalidInput(
            "ask the user for: " + "; ".join(missing) + ". Don't guess them. Then call again."
        )
    return coach_rules.TrainingProfile(days, minutes, equipment, experience, focus)


async def _gate_coach(ctx: ToolContext, birth_year: int | None) -> None:
    """Refuse for pain or injury, for someone under 18, and for an age nobody knows."""
    if coach_rules.mentions_pain(ctx.message) or red_flags(ctx.message) is not None:
        raise InvalidInput(NO_PROGRAMMING_FOR_PAIN)
    year = birth_year or await coach_cases.birth_year(ctx.uow(), ctx.user.id)
    young = coach_cases.is_under_18(year, ctx.now.year)
    if young is None:
        raise InvalidInput(NEEDS_AGE)
    if young:
        raise InvalidInput(UNDER_18)


type Planned = tuple[
    list[coach_rules.PlannedRoutine], coach_rules.PlannedSchedule, coach_rules.TrainingProfile
]


async def _planned(
    ctx: ToolContext, a: DraftPlanArgs
) -> tuple[
    list[coach_rules.PlannedRoutine], coach_rules.PlannedSchedule, coach_rules.TrainingProfile
]:
    await _gate_coach(ctx, a.birth_year)
    profile = await _training_profile(ctx, a)
    problems: list[str] = []
    routines: list[coach_rules.PlannedRoutine] = []
    for routine in a.routines:
        slots: list[coach_rules.PlannedSlot] = []
        for n, s in enumerate(routine.slots, 1):
            where = f"{routine.name!r} exercise {n}"
            said = s.exercise_id or s.exercise_query
            if not said:
                problems.append(f"{where}: give an exercise_query or an exercise_id")
                continue
            try:
                found = await resolve_exercise(ctx, said)
            except NexusError as exc:
                problems.append(f"{where}: {exc}")
                continue
            slots.append(coach_rules.PlannedSlot(found, s.sets, s.reps, s.seconds, s.rest_seconds))
        routines.append(coach_rules.PlannedRoutine(routine.name.strip(), tuple(slots)))
    weekly: list[tuple[int, str]] = []
    for d in a.schedule.weekly:
        day = coach_rules.weekday_of(d.day)
        if day is None:
            problems.append(f"{d.day!r} isn't a day: use mon, tue, wed, thu, fri, sat or sun")
        else:
            weekly.append((day, d.routine.strip()))
    schedule = coach_rules.PlannedSchedule(
        tuple(weekly), tuple(r.strip() for r in a.schedule.rotation)
    )
    if not problems:  # numbers are judged once every exercise is known
        problems = coach_rules.validate_plan(routines, schedule, profile)
    if problems:
        raise InvalidInput(
            "the plan can't be shown yet. Fix these and call again (ask the user only if an "
            "exercise is unclear):\n" + "\n".join(f"- {p}" for p in problems)
        )
    return routines, schedule, profile


async def _describe_draft(ctx: ToolContext, a: DraftPlanArgs) -> str:
    await need_consent(ctx)
    routines, schedule, profile = await _planned(ctx, a)
    return coach_rules.draft_card(routines, schedule, profile)


async def _draft_training_plan(ctx: ToolContext, a: DraftPlanArgs) -> ToolResult:
    if not await has_consent(ctx):
        return health_off()
    routines, schedule, _ = await _planned(ctx, a)
    saved = await coach_cases.save_draft(ctx.uow, ctx.user.id, routines, schedule, now=ctx.now)
    names = ", ".join(r.name for r in saved)
    return ToolResult(
        f"Saved {len(saved)} routines ({names}) and made the schedule your training plan.",
        wrote=True,
    )


class AcceptArgs(Args):
    accept: list[int] = Field(
        max_length=50, description="The numbers of the adjustments the user accepted (from 1)"
    )


async def _suggest_adjustments(ctx: ToolContext, _: NoArgs) -> ToolResult:
    if (blocked := await ai_blocked(ctx)) is not None:
        return blocked
    plan = await coach_cases.current_plan(ctx.uow, ctx.user.id)
    if not plan.refs:
        return ToolResult(
            "There is no training plan yet, so there is nothing to adjust. A plan can be "
            "drafted with draft_training_plan."
        )
    found = await coach_cases.proposals(ctx.uow, ctx.user.id, now=ctx.now)
    return ToolResult(
        coach_rules.describe_proposals(found)
        + "\nThese are suggestions only: nothing changes until the user accepts some "
        "(then apply_adjustments with their numbers)."
    )


async def _chosen(ctx: ToolContext, a: AcceptArgs) -> list[coach_rules.Proposal]:
    found = coach_rules.actionable(await coach_cases.proposals(ctx.uow, ctx.user.id, now=ctx.now))
    if not a.accept:
        raise InvalidInput("which adjustments did the user accept? Give their numbers")
    for n in a.accept:
        if not 1 <= n <= len(found):
            raise InvalidInput(
                f"there is no adjustment {n}: run suggest_adjustments and use its numbers"
            )
    return [found[n - 1] for n in dict.fromkeys(a.accept)]


async def _describe_apply(ctx: ToolContext, a: AcceptArgs) -> str:
    await need_consent(ctx)
    if (blocked := await ai_blocked(ctx)) is not None:
        raise ConsentRequired(blocked.text)
    chosen = await _chosen(ctx, a)
    return "Change your routines like this?\n" + "\n".join(f"- {p.reason}" for p in chosen)


async def _apply_adjustments(ctx: ToolContext, a: AcceptArgs) -> ToolResult:
    if not await has_consent(ctx):
        return health_off()
    if (blocked := await ai_blocked(ctx)) is not None:
        return blocked
    await _chosen(ctx, a)
    done = await coach_cases.apply(ctx.uow, ctx.user.id, a.accept, now=ctx.now)
    return ToolResult(
        "Updated your routines:\n" + "\n".join(f"- {p.reason}" for p in done), wrote=True
    )


SPECS = (
    ToolSpec(
        "draft_training_plan",
        "Draft a training plan (routines and a weekly or rotation schedule) for the user and "
        "show it for them to confirm; nothing is saved until they do. Exercises are looked up in "
        "the catalogue and the plan is checked in code against their days, session length and "
        "equipment: if it says what is wrong, fix it and call again. Ask the user for any input "
        "you don't have first. Wellness only: refuses for pain, injury and under-18s. Asks the "
        "user to confirm.",
        DraftPlanArgs,
        _draft_training_plan,
        confirm=_describe_draft,
    ),
    ToolSpec(
        "suggest_adjustments",
        "Numbered proposals to change the user's current plan (add load, hold, lower it, a "
        "deload week), worked out in code from their last few weeks of sets, each with its "
        "reason. Read-only: nothing changes.",
        NoArgs,
        _suggest_adjustments,
    ),
    ToolSpec(
        "apply_adjustments",
        "Apply the adjustments from suggest_adjustments that the user accepted, by number. "
        "Never apply one they didn't accept. Asks the user to confirm.",
        AcceptArgs,
        _apply_adjustments,
        confirm=_describe_apply,
    ),
)


READ_ONLY: frozenset[str] = frozenset(
    {
        "suggest_adjustments",
    }
)

MENU: dict[str, MenuSection] = dict.fromkeys(
    (
        "apply_adjustments",
        "draft_training_plan",
        "suggest_adjustments",
    ),
    MenuSection.HEALTH,
)
