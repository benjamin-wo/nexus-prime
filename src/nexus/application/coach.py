"""The Gym coach: the user's training inputs, a drafted plan saved once they confirm it, and
proposed changes from their log. Nothing here changes a routine on its own: the agent's tools
ask the user first, and each write goes through ``application.gym`` (consent, ownership, menu).
"""

import dataclasses
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from nexus.application import gym as gym_cases
from nexus.application.health_menu import note_health_write
from nexus.application.ports import UnitOfWork
from nexus.domain.coach import (
    DELOAD_LOOKBACK_DAYS,
    PlannedRoutine,
    PlannedSchedule,
    Proposal,
    ProposalKind,
    SlotRef,
    TrainingProfile,
    actionable,
    deloaded_slot,
    plain_kg,
    restored_slot,
    suggest_progression,
)
from nexus.domain.errors import ConsentRequired, InvalidInput
from nexus.domain.gym_training import PlanKind, Routine, SetEntry, Slot
from nexus.domain.health_safety import ADULT_AGE, safe_age
from nexus.domain.ledger import UserId

type UowFactory = Callable[[], UnitOfWork]


async def training_profile(uow: UnitOfWork, user_id: UserId) -> TrainingProfile | None:
    async with uow:
        return await uow.gym.get_training_profile(user_id)


async def save_training_profile(
    uow: UnitOfWork, user_id: UserId, profile: TrainingProfile, *, now: datetime
) -> TrainingProfile:
    """Replace the user's coach inputs. Needs the Health consent, like every health write."""
    async with uow:
        if await uow.gym.health_consent(user_id) is None:
            raise ConsentRequired("agree to Nexus keeping your health data first")
        await uow.gym.save_training_profile(user_id, profile, now)
        await note_health_write(uow, user_id)
        await uow.commit()
    return profile


async def birth_year(uow: UnitOfWork, user_id: UserId) -> int | None:
    async with uow:
        found = await uow.health.get_profile(user_id)
    return None if found is None else found.birth_year


def is_under_18(year: int | None, this_year: int) -> bool | None:
    """True when the person could be under 18 this year (the youngest they could be, as the
    other health gates judge it); None when no birth year is known."""
    age = safe_age(year, this_year)
    return None if age is None else age < ADULT_AGE


async def save_draft(
    make_uow: UowFactory,
    user_id: UserId,
    routines: Sequence[PlannedRoutine],
    schedule: PlannedSchedule,
    *,
    now: datetime,
) -> list[Routine]:
    """Save each routine, then make the schedule the user's plan (replacing the old plan)."""
    saved: dict[str, Routine] = {}
    for planned in routines:
        saved[planned.name.strip().casefold()] = await gym_cases.save_routine(
            make_uow(),
            user_id,
            name=planned.name,
            slots=[s.slot() for s in planned.slots],
            now=now,
        )
    if schedule.weekly:
        await gym_cases.set_plan(
            make_uow(),
            user_id,
            PlanKind.WEEKLY,
            weekly={d: saved[n.strip().casefold()].id for d, n in schedule.weekly},
            now=now,
        )
    else:
        await gym_cases.set_plan(
            make_uow(),
            user_id,
            PlanKind.ROTATION,
            rotation=[saved[n.strip().casefold()].id for n in schedule.rotation],
            now=now,
        )
    return list(saved.values())


@dataclasses.dataclass(frozen=True, slots=True)
class PlanRoutines:
    routines: list[Routine]
    refs: list[SlotRef]


async def current_plan(make_uow: UowFactory, user_id: UserId) -> PlanRoutines:
    """The routines in the user's plan (in plan order) and each of their slots."""
    plan = await gym_cases.plan(make_uow(), user_id)
    if plan is None:
        return PlanRoutines([], [])
    order = [*(plan.weekly[d] for d in sorted(plan.weekly)), *plan.rotation]
    wanted = list(dict.fromkeys(order))
    have = {r.id: r for r in await gym_cases.routines(make_uow(), user_id)}
    routines = [have[i] for i in wanted if i in have]
    refs = [SlotRef(r.id, r.name, i, slot) for r in routines for i, slot in enumerate(r.slots)]
    return PlanRoutines(routines, refs)


async def proposals(make_uow: UowFactory, user_id: UserId, *, now: datetime) -> list[Proposal]:
    """What the log suggests changing in the current plan. Worked out fresh every time from the
    same history, so the numbered list is the same for a suggestion and the apply after it."""
    found = await current_plan(make_uow, user_id)
    if not found.refs:
        return []
    ids = list(dict.fromkeys(r.slot.exercise_id for r in found.refs))
    async with make_uow() as uow:
        user = await uow.ledger.get_user(user_id)
        tz = ZoneInfo(user.timezone) if user else ZoneInfo("UTC")
        sets = await uow.gym.sets_between(
            user_id, now - timedelta(days=DELOAD_LOOKBACK_DAYS), now + timedelta(days=1)
        )
        catalogue = await uow.gym.get_exercises(ids)
    history: dict[str, list[SetEntry]] = {i: [] for i in ids}
    for s in sets:
        if s.exercise_id in history:
            history[s.exercise_id].append(s)
    return suggest_progression(found.refs, history, catalogue, now=now, tz=tz)


async def apply(
    make_uow: UowFactory, user_id: UserId, accepted: Sequence[int], *, now: datetime
) -> list[Proposal]:
    """Apply the proposals the user accepted, by their numbers in ``describe_proposals`` (from
    1). Returns what was applied. An unknown number is an ``InvalidInput``."""
    chosen = actionable(await proposals(make_uow, user_id, now=now))
    picked: list[Proposal] = []
    for n in dict.fromkeys(accepted):
        if not 1 <= n <= len(chosen):
            raise InvalidInput(
                f"there is no adjustment {n}: choose from 1 to {len(chosen)}"
                if chosen
                else "there are no adjustments to apply"
            )
        picked.append(chosen[n - 1])
    plan = await current_plan(make_uow, user_id)
    changed: dict[Routine, list[Slot]] = {r: list(r.slots) for r in plan.routines}
    for p in picked:
        for routine, slots in changed.items():
            for i, slot in enumerate(slots):
                if p.kind in (ProposalKind.INCREASE, ProposalKind.DECREASE):
                    if routine.id == p.routine_id and slot.exercise_id == p.exercise_id:
                        slots[i] = _with_load_note(slot, p)
                elif p.kind is ProposalKind.DELOAD:
                    slots[i] = deloaded_slot(slot)
                elif p.kind is ProposalKind.RESTORE:
                    slots[i] = restored_slot(slot)
    for routine, slots in changed.items():
        if tuple(slots) != routine.slots:
            await gym_cases.save_routine(
                make_uow(), user_id, name=routine.name, slots=slots, routine_id=routine.id, now=now
            )
    return picked


def _with_load_note(slot: Slot, p: Proposal) -> Slot:
    if p.to_kg is None or p.from_kg is None:
        raise InvalidInput("that adjustment has no weight")
    return dataclasses.replace(
        slot, note=f"Next time: {plain_kg(p.to_kg)} kg (last: {plain_kg(p.from_kg)} kg)"
    )
