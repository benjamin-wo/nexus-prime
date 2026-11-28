"""Health foundation: body and activity samples from any source, and the wellness profile.

Every write needs the master consent (``users.health_consent_at``) and, for a sample from a
phone or a brand's service, that source's scope too; typed and chat entries need only the
master one. Withdrawing consent keeps what is stored, so deleting a sample never needs it. The
first write turns Health on in the menu (``users.show_health``), as Gym's does.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from nexus.application.health_consent import require_consent
from nexus.application.health_menu import note_health_write
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.health import (
    ActivityLevel,
    Goal,
    HealthProfile,
    Sample,
    SampleKind,
    SampleSource,
    SampleUnit,
    Sex,
    UnitSystem,
    clean_unit,
    edited,
    scope_for,
)
from nexus.domain.health_safety import Gate, bmi_of, safe_age, weight_loss_allowed
from nexus.domain.ledger import UserId

DEFAULT_WINDOW = timedelta(days=30)
MAX_SAMPLES = 1000
FUTURE_SLACK = timedelta(days=1)  # a clock a little ahead is fine; next week is a typo


def _not_future(at: datetime, now: datetime) -> None:
    if at > now + FUTURE_SLACK:
        raise InvalidInput("that time is in the future")


async def log_sample(
    uow: UnitOfWork,
    user_id: UserId,
    kind: SampleKind,
    value: Decimal,
    *,
    unit: SampleUnit | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    source: SampleSource = SampleSource.MANUAL,
    source_name: str | None = None,
    external_id: str | None = None,
    now: datetime,
) -> Sample:
    """Record a measurement (``start_at`` defaults to now, ``end_at`` to ``start_at``).

    A typed or chat entry for a kind and moment that already has one replaces its value; an
    imported sample with a known (source, external id) updates the one stored. The unit defaults
    to the kind's usual one."""
    start = start_at or now
    sample = Sample(
        uuid4(),
        user_id,
        kind,
        value,
        clean_unit(kind, unit),
        start,
        end_at or start,
        source,
        now,
        source_name,
        external_id,
    )
    _not_future(sample.start_at, now)
    async with uow:
        await require_consent(uow, user_id, scope_for(source))
        if sample.is_manual:
            old = await uow.health.find_manual(user_id, kind, sample.start_at)
            if old is None:
                await uow.health.add_sample(sample)
            else:
                sample = edited(old, value=sample.value, unit=sample.unit, end_at=sample.end_at)
                await uow.health.update_sample(sample)
        elif sample.external_id is not None:
            sample = await uow.health.upsert_imported(sample)
        else:
            await uow.health.add_sample(sample)
        await note_health_write(uow, user_id)
        await uow.commit()
    return sample


EDITABLE = frozenset({"value", "unit", "start_at", "end_at"})


async def edit_sample(
    uow: UnitOfWork, user_id: UserId, sample_id: UUID, changes: Mapping[str, Any], *, now: datetime
) -> Sample:
    """Change the value, unit or times of a typed or chat entry. An imported sample is
    corrected where it came from, since the next sync would undo it here."""
    unknown = set(changes) - EDITABLE
    if unknown or not changes:
        raise InvalidInput(
            "nothing to change" if not changes else f"can't change {sorted(unknown)}"
        )
    async with uow:
        await require_consent(uow, user_id, None)
        old = await uow.health.get_sample(user_id, sample_id)
        if old is None:
            raise NotFound("no such sample")
        if not old.is_manual:
            raise InvalidInput("change imported samples where they came from")
        sample = edited(old, **changes)  # validated again on construction
        _not_future(sample.start_at, now)
        if sample.start_at != old.start_at:
            other = await uow.health.find_manual(user_id, sample.kind, sample.start_at)
            if other is not None and other.id != sample.id:
                raise Conflict("you already have an entry for that moment")
        await uow.health.update_sample(sample)
        await note_health_write(uow, user_id)
        await uow.commit()
    return sample


async def delete_sample(
    uow: UnitOfWork, user_id: UserId, sample_id: UUID, *, now: datetime
) -> None:
    """Delete any sample. It never needs consent: the user can always remove their data."""
    del now  # kept so every function here has the same shape
    async with uow:
        if not await uow.health.delete_sample(user_id, sample_id):
            raise NotFound("no such sample")
        await uow.commit()


async def samples(
    uow: UnitOfWork,
    user_id: UserId,
    kind: SampleKind | None = None,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = MAX_SAMPLES,
    now: datetime,
) -> list[Sample]:
    """Samples that started in ``[start, end)``, newest first: the last 30 days by default."""
    if not 1 <= limit <= MAX_SAMPLES:
        raise InvalidInput(f"limit is between 1 and {MAX_SAMPLES}")
    stop = end or now + FUTURE_SLACK
    first = start or stop - DEFAULT_WINDOW
    if first >= stop:
        raise InvalidInput("the range starts after it ends")
    async with uow:
        return await uow.health.list_samples(user_id, kind=kind, start=first, end=stop, limit=limit)


async def latest(
    uow: UnitOfWork, user_id: UserId, kind: SampleKind, *, now: datetime
) -> Sample | None:
    """The newest sample of a kind that has started by now."""
    async with uow:
        return await uow.health.latest_sample(user_id, kind, until=now)


async def profile(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> HealthProfile | None:
    del now
    async with uow:
        return await uow.health.get_profile(user_id)


@dataclass(frozen=True, slots=True)
class ProfileSaved:
    profile: HealthProfile
    gate: Gate  # whether a weight-loss goal is allowed for this person now


async def save_profile(
    uow: UnitOfWork, user_id: UserId, *, now: datetime, **fields: Any
) -> HealthProfile:
    """``save_profile_checked`` for callers that only need the stored profile."""
    return (await save_profile_checked(uow, user_id, now=now, **fields)).profile


async def save_profile_checked(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    sex_for_equations: Sex = Sex.UNSPECIFIED,
    birth_year: int | None = None,
    height_cm: Decimal | None = None,
    activity_level: ActivityLevel | None = None,
    goal: Goal = Goal.MAINTAIN,
    target_rate_pct_per_week: Decimal | None = None,
    numbers_free: bool | None = None,
    ed_history: bool = False,
    unit_system: UnitSystem = UnitSystem.METRIC,
    confirm_ed_override: bool = False,
    now: datetime,
) -> ProfileSaved:
    """Replace the user's profile. Figures are checked for input errors. ``numbers_free``
    follows ``ed_history`` unless it is given.

    A "lose" goal for someone the safety gates block (under 18, BMI under 18.5, an unknown age
    or BMI, or an eating-disorder history without ``confirm_ed_override``) still saves the
    profile, but the goal is stored as "maintain" with no target rate, and the gate's reason
    comes back with it."""
    new = HealthProfile(
        user_id,
        sex_for_equations,
        birth_year,
        height_cm,
        activity_level,
        goal,
        target_rate_pct_per_week,
        ed_history if numbers_free is None else numbers_free,
        ed_history,
        unit_system,
        now,
    ).check(this_year=now.year)
    async with uow:
        await require_consent(uow, user_id, None)
        weight = await uow.health.latest_sample(user_id, SampleKind.WEIGHT, until=now)
        gate = weight_loss_allowed(
            safe_age(new.birth_year, now.year),
            bmi_of(weight.weight_kg if weight else None, new.height_cm),
            new.ed_history,
            ed_override_confirmed=confirm_ed_override,
        )
        if new.goal is Goal.LOSE and not gate.allowed:
            new = replace(new, goal=Goal.MAINTAIN, target_rate_pct_per_week=None)
        await uow.health.save_profile(new)
        await note_health_write(uow, user_id)
        await uow.commit()
    return ProfileSaved(new, gate)


# --- a profile changed from chat, with Undo -------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileUpdated:
    saved: ProfileSaved
    previous: HealthProfile | None
    undo_token: str
    asked_goal: Goal  # the goal the user asked for (what is stored may differ: see the gate)


async def update_profile(
    new_uow: Callable[[], UnitOfWork],
    user_id: UserId,
    *,
    now: datetime,
    sex_for_equations: Sex | None = None,
    birth_year: int | None = None,
    height_cm: Decimal | None = None,
    activity_level: ActivityLevel | None = None,
    goal: Goal | None = None,
    target_rate_pct_per_week: Decimal | None = None,
    numbers_free: bool | None = None,
    ed_history: bool | None = None,
) -> ProfileUpdated:
    """Change only the fields given (the rest stay as they were) through
    ``save_profile_checked``, so the safety gates and floors apply, and keep the profile as it
    was for ``undo_profile``. A loss goal the gates block is stored as "maintain"; the saved
    result carries the gate's reason."""
    previous = await profile(new_uow(), user_id, now=now)
    old = previous
    new_ed = old.ed_history if ed_history is None and old else bool(ed_history)
    kept_goal = old.goal if old else Goal.MAINTAIN
    asked = goal if goal is not None else kept_goal
    rate = target_rate_pct_per_week
    if rate is None and goal is None and old:
        rate = old.target_rate_pct_per_week
    # Telling Prime about an eating-disorder history turns numbers off, as it does in the app;
    # otherwise the choice is kept.
    hide = numbers_free
    if hide is None:
        hide = True if ed_history else (old.numbers_free if old else None)
    saved = await save_profile_checked(
        new_uow(),
        user_id,
        sex_for_equations=sex_for_equations or (old.sex_for_equations if old else Sex.UNSPECIFIED),
        birth_year=birth_year if birth_year is not None else (old.birth_year if old else None),
        height_cm=height_cm if height_cm is not None else (old.height_cm if old else None),
        activity_level=activity_level or (old.activity_level if old else None),
        goal=asked,
        target_rate_pct_per_week=rate,
        numbers_free=hide,
        ed_history=new_ed,
        unit_system=old.unit_system if old else UnitSystem.METRIC,
        # A goal the user already confirmed in the app, despite the history they gave, stays.
        confirm_ed_override=bool(old and old.ed_history and new_ed and old.goal is Goal.LOSE),
        now=now,
    )
    token = uuid4().hex
    async with new_uow() as uow:
        await uow.health.add_profile_undo(user_id, token, previous, now)
        await uow.commit()
    return ProfileUpdated(saved, previous, token, asked)


async def undo_profile(uow: UnitOfWork, user_id: UserId, token: str, *, now: datetime) -> bool:
    """Put the profile back as it was before the change this token names; False when the token
    is unknown, used or over 30 minutes old."""
    async with uow:
        found, previous = await uow.health.take_profile_undo(user_id, token, now=now)
        if not found:
            return False
        if previous is None:
            await uow.health.delete_profile(user_id)
        else:
            await require_consent(uow, user_id, None)
            await uow.health.save_profile(previous)
        await uow.commit()
    return True
