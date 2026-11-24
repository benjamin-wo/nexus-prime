"""Health's safety layer, applied: the one door for targets, the current safety state, and the
pre-check for messages.

- ``check_targets`` is the single entry point any target-setting code must call. It applies the
  gates, the calorie floor, the rate cap and the protein rules (``domain/health_safety.py``) and
  returns adjusted targets with reason codes. Code that sets calories, a loss rate or protein
  without going through it is a bug.
- ``assess`` reads the stored data and says which signals are active, whether calorie-target
  features are suspended, and which signposts to show. Intake data does not exist yet, so the
  intake source is an injected provider (``no_intake`` for now). The weekly trend defaults to a
  plain bucket-mean of the weights; the energy module's trend plugs in as ``weekly_trend``, and
  its resting rate as ``bmr_kcal``.
- ``precheck_message`` wraps ``red_flags``. HOW IT IS TO BE USED (not wired in yet): the agent
  graph calls it on the user's message before any health answer. If it returns a ``RedFlag``,
  the graph replies with ``flag.text`` (and ``flag.signposts``) verbatim and skips the model;
  for an eating-disorder flag it also calls ``assess(..., flagged_language=True, record=True)``
  so calorie-target tools are off. Calorie-target tools must also call ``assess`` (or
  ``check_targets``) and refuse when ``suspended`` is true.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from nexus.application.ports import UnitOfWork
from nexus.domain.health import Goal, HealthProfile, SampleKind, Sex
from nexus.domain.health_safety import (
    ADULT_AGE,
    PROTEIN_DEFAULT,
    Gate,
    IntakeDay,
    ReasonCode,
    RedFlag,
    Signal,
    bmi_of,
    calorie_floor,
    clamp_rate,
    ed_signals,
    protein_per_kg,
    protein_target_g,
    rate_for_floor,
    red_flags,
    safe_age,
    signposts_for,
    weekly_trend_history,
    weight_loss_allowed,
)
from nexus.domain.health_texts import Signpost
from nexus.domain.ledger import UserId

TREND_WEEKS = 4
WEIGH_IN_WINDOW = timedelta(hours=24)
# A signal that fired again within this long of its last record is not a new check-in.
CHECK_IN_REPEAT = timedelta(days=30)
WEIGHT_LOOKBACK = timedelta(days=7 * (TREND_WEEKS + 1))


class IntakeProvider(Protocol):
    """Logged daily intake, newest last. Food logging does not exist yet; whatever adds it
    supplies this. ``floor_kcal`` is the floor to stamp on each day."""

    async def __call__(
        self, uow: UnitOfWork, user_id: UserId, *, now: datetime, floor_kcal: int
    ) -> Sequence[IntakeDay]: ...


async def no_intake(
    uow: UnitOfWork, user_id: UserId, *, now: datetime, floor_kcal: int
) -> Sequence[IntakeDay]:
    return []


type TrendProvider = Callable[
    [UnitOfWork, UserId, datetime], Awaitable[Sequence[Decimal | None]]
]  # weekly percent change in body weight, oldest first, loss negative


@dataclass(frozen=True, slots=True)
class SafetyState:
    signals: tuple[Signal, ...]
    numbers_free: bool
    ed_history: bool
    weight_loss_gate: Gate
    floor_kcal: int
    suspended: bool  # calorie-target features are off
    reasons: tuple[ReasonCode, ...]  # why they are
    signposts: tuple[Signpost, ...]
    new_signals: tuple[Signal, ...]  # signals first recorded by this call (a check-in is due)


@dataclass(frozen=True, slots=True)
class TargetProposal:
    """What target-setting code wants to set. Nothing is trusted."""

    goal: Goal
    rate_pct_per_week: Decimal | None = None
    calories_kcal: int | None = None
    protein_g_per_kg: Decimal = PROTEIN_DEFAULT
    weight_kg: Decimal | None = None  # the latest weigh-in when left out
    tdee_kcal: Decimal | None = None  # an expenditure estimate, to fit a rate to the floor
    bmr_kcal: Decimal | None = None  # the resting rate, when known
    confirm_ed_override: bool = (
        False  # the user explicitly confirmed a loss goal despite ED history
    )


@dataclass(frozen=True, slots=True)
class SafeTargets:
    goal: Goal
    rate_pct_per_week: Decimal | None
    calories_kcal: int | None
    protein_g: int | None
    protein_g_per_kg: Decimal | None
    floor_kcal: int
    suspended: bool  # no numbers were set
    reasons: tuple[ReasonCode, ...]
    signposts: tuple[Signpost, ...]


async def _profile_facts(
    uow: UnitOfWork, user_id: UserId, now: datetime
) -> tuple[HealthProfile | None, Decimal | None]:
    profile = await uow.health.get_profile(user_id)
    weight = await uow.health.latest_sample(user_id, SampleKind.WEIGHT, until=now)
    return profile, weight.weight_kg if weight else None


async def _weights(
    uow: UnitOfWork, user_id: UserId, now: datetime
) -> list[tuple[datetime, Decimal]]:
    found = await uow.health.list_samples(
        user_id,
        kind=SampleKind.WEIGHT,
        start=now - WEIGHT_LOOKBACK,
        end=now + timedelta(seconds=1),
        limit=1000,
    )
    return [(s.start_at, kg) for s in found if (kg := s.weight_kg) is not None]


async def _assess(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    now: datetime,
    intake: IntakeProvider,
    weekly_trend: TrendProvider | None,
    bmr_kcal: Decimal | None,
    flagged_language: bool,
    record: bool,
    override: bool = False,
) -> SafetyState:
    profile, weight_kg = await _profile_facts(uow, user_id, now)
    sex = profile.sex_for_equations if profile else Sex.UNSPECIFIED
    ed_history = bool(profile and profile.ed_history)
    numbers_free = bool(profile and profile.numbers_free)
    age = safe_age(profile.birth_year if profile else None, now.year)
    gate = weight_loss_allowed(
        age,
        bmi_of(weight_kg, profile.height_cm if profile else None),
        ed_history,
        ed_override_confirmed=override,
    )
    floor = calorie_floor(sex, bmr_kcal)
    weights = await _weights(uow, user_id, now)
    if weekly_trend is not None:
        trend = list(await weekly_trend(uow, user_id, now))
    else:
        trend = weekly_trend_history(
            [(at.date(), kg) for at, kg in weights], now.date(), weeks=TREND_WEEKS
        )
    weigh_ins = sum(1 for at, _ in weights if now - WEIGH_IN_WINDOW < at <= now)
    days = await intake(uow, user_id, now=now, floor_kcal=floor)
    signals = tuple(ed_signals(days, trend, weigh_ins, flagged_language))

    new: list[Signal] = []
    if record:
        for signal in signals:
            last = await uow.health.last_safety_event(user_id, signal.value)
            if last is None or now - last >= CHECK_IN_REPEAT:
                await uow.health.add_safety_event(user_id, signal.value, now)
                new.append(signal)
        if new:
            await uow.commit()

    reasons: list[ReasonCode] = []
    if signals:
        reasons.append(ReasonCode.SUSPENDED_ED_SIGNAL)
    if numbers_free:
        reasons.append(ReasonCode.SUSPENDED_NUMBERS_FREE)
    if ed_history:
        reasons.append(ReasonCode.SUSPENDED_ED_HISTORY)
    show_help = bool(signals) or ed_history
    return SafetyState(
        signals=signals,
        numbers_free=numbers_free,
        ed_history=ed_history,
        weight_loss_gate=gate,
        floor_kcal=floor,
        suspended=bool(reasons),
        reasons=tuple(reasons),
        signposts=signposts_for(under_18=age is not None and age < ADULT_AGE) if show_help else (),
        new_signals=tuple(new),
    )


async def assess(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    now: datetime,
    intake: IntakeProvider = no_intake,
    weekly_trend: TrendProvider | None = None,
    bmr_kcal: Decimal | None = None,
    flagged_language: bool = False,
    record: bool = False,
) -> SafetyState:
    """The user's current safety state. Calorie-target features are suspended when any signal is
    active, ``numbers_free`` is on, or there is an eating-disorder history. With ``record``,
    a signal not seen in the last 30 days is stored (kind and time only) and listed in
    ``new_signals``, so the UI can show one soft check-in."""
    async with uow:
        return await _assess(
            uow,
            user_id,
            now=now,
            intake=intake,
            weekly_trend=weekly_trend,
            bmr_kcal=bmr_kcal,
            flagged_language=flagged_language,
            record=record,
        )


async def check_targets(
    uow: UnitOfWork,
    user_id: UserId,
    proposed: TargetProposal,
    *,
    now: datetime,
    intake: IntakeProvider = no_intake,
    weekly_trend: TrendProvider | None = None,
) -> SafeTargets:
    """Apply every rule to a proposed target and return what may be set.

    Order: suspension (signals, numbers-free, ED history without the user's confirmed
    override) returns no numbers at all; then the loss gates (a blocked "lose" becomes
    "maintain"); then the rate cap; then, with an expenditure estimate, the rate is slowed until
    calories sit on the floor; then the floor itself; then protein."""
    async with uow:
        state = await _assess(
            uow,
            user_id,
            now=now,
            intake=intake,
            weekly_trend=weekly_trend,
            bmr_kcal=proposed.bmr_kcal,
            flagged_language=False,
            record=False,
            override=proposed.confirm_ed_override,
        )
        profile, latest_kg = await _profile_facts(uow, user_id, now)
    floor = state.floor_kcal
    overridden = (
        proposed.confirm_ed_override
        and state.ed_history
        and not state.numbers_free
        and not state.signals
    )
    reasons = [
        r for r in state.reasons if not (overridden and r is ReasonCode.SUSPENDED_ED_HISTORY)
    ]
    if reasons:
        return SafeTargets(
            proposed.goal if proposed.goal is not Goal.LOSE else Goal.MAINTAIN,
            None,
            None,
            None,
            None,
            floor,
            True,
            tuple(reasons),
            state.signposts,
        )

    goal = proposed.goal
    out: list[ReasonCode] = []
    rate = proposed.rate_pct_per_week
    if goal is Goal.LOSE and not state.weight_loss_gate.allowed:
        out.append(state.weight_loss_gate.reason)
        goal, rate = Goal.MAINTAIN, None
    elif goal is Goal.LOSE:
        if state.weight_loss_gate.reason is not ReasonCode.OK:
            out.append(state.weight_loss_gate.reason)
        bmi = bmi_of(proposed.weight_kg or latest_kg, profile.height_cm if profile else None)
        age = safe_age(profile.birth_year if profile else None, now.year)
        decision = clamp_rate(goal, rate, bmi, age)
        rate = decision.rate
        if decision.reason is not ReasonCode.OK:
            out.append(decision.reason)

    weight = proposed.weight_kg or latest_kg
    calories = proposed.calories_kcal
    if goal is Goal.LOSE and rate is not None and proposed.tdee_kcal is not None and weight:
        rate, fitted, slowed = rate_for_floor(proposed.tdee_kcal, weight, rate, floor)
        if slowed:
            out.append(ReasonCode.RATE_SLOWED_FOR_FLOOR)
        calories = fitted if calories is None or slowed else calories
    if calories is not None and calories < floor:
        calories = floor
        out.append(ReasonCode.FLOOR_APPLIED)

    protein_g = protein_kg = None
    if weight:
        deficit = goal is Goal.LOSE
        protein_kg = protein_per_kg(proposed.protein_g_per_kg, in_deficit=deficit)
        protein_g = protein_target_g(weight, proposed.protein_g_per_kg, in_deficit=deficit)
        if protein_kg > proposed.protein_g_per_kg:
            out.append(ReasonCode.PROTEIN_RAISED)
        elif protein_kg < proposed.protein_g_per_kg:
            out.append(ReasonCode.PROTEIN_LOWERED)
    return SafeTargets(
        goal, rate, calories, protein_g, protein_kg, floor, False, tuple(out), state.signposts
    )


def precheck_message(text: str) -> RedFlag | None:
    """The red flag in a message, if any. See the module docstring for how the agent uses it."""
    return red_flags(text)
