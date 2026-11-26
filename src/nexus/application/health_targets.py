"""Daily targets with the safety layer applied: the one place calorie targets are produced for
users.

``energy.current_targets`` stays a pure step over an injected ``SafetyStep``; that step is
synchronous, while the real safety layer reads the user's data. So this module records the
proposals the step is asked about, runs each through ``health_safety.check_targets``, and replays
the results. If the safety state says calorie targets are suspended (a signal, numbers-free mode
or an eating-disorder history) it returns no targets, only the signposts.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from nexus.application import energy as energy_cases
from nexus.application import health_safety as safety_cases
from nexus.application import nutrition as nutrition_cases
from nexus.application.ports import UnitOfWork
from nexus.domain import energy as energy_domain
from nexus.domain.health import Goal, HealthProfile
from nexus.domain.health_safety import IntakeDay, ReasonCode, Signal
from nexus.domain.health_texts import Signpost
from nexus.domain.ledger import UserId

D = Decimal
INTAKE_LOOKBACK_DAYS = 14  # the latest 7 logged days of these are what the signal reads
TREND_WEEKS = 4
MIN_WEIGH_INS_PER_WEEK = 2

_NOTES: dict[ReasonCode, str] = {
    ReasonCode.UNDER_18: "No weight-loss target is set under 18.",
    ReasonCode.LOW_BMI: "No weight-loss target is set at a BMI under 18.5.",
    ReasonCode.AGE_UNKNOWN: "Add your birth year before a weight-loss target can be set.",
    ReasonCode.BMI_UNKNOWN: "Add your height before a weight-loss target can be set.",
    ReasonCode.ED_HISTORY: "No weight-loss target is set because of your history.",
    ReasonCode.RATE_DEFAULTED: "A steady default pace was used.",
    ReasonCode.RATE_RAISED_TO_MINIMUM: "The pace was raised to the gentlest setting.",
    ReasonCode.RATE_HARD_CAP: "The pace was held to 1% of body weight a week.",
    ReasonCode.RATE_LEAN_LIMIT: "The pace was held to 0.5% of body weight a week.",
    ReasonCode.RATE_SLOWED_FOR_FLOOR: "The pace was slowed so calories stay at a safe minimum.",
    ReasonCode.FLOOR_APPLIED: "Calories were raised to a safe minimum.",
}


@dataclass(frozen=True, slots=True)
class SafeOverview:
    """``energy`` is the estimate behind the targets. ``targets`` is None when there is no
    estimate or when ``suspended`` (then the signposts say where to get help)."""

    overview: energy_cases.TargetsOverview
    suspended: bool
    signposts: tuple[Signpost, ...]
    new_signals: tuple[Signal, ...]
    check_in: bool  # a signal was newly recorded: show one soft check-in


def weekly_pct_history(
    trend: list[energy_domain.TrendPoint], today: date, *, weeks: int = TREND_WEEKS
) -> list[Decimal | None]:
    """The trend's percent change over each of the last ``weeks`` weeks, oldest first and
    signed (loss is negative). A week with fewer than two weigh-ins, or one that starts before
    the first weigh-in, is None."""
    if not trend:
        return [None] * weeks

    def on(day: date) -> Decimal:
        value = trend[0].trend_kg
        for p in trend:
            if p.date > day:
                break
            value = p.trend_kg
        return value

    out: list[Decimal | None] = []
    for k in range(weeks - 1, -1, -1):
        end = today - timedelta(days=7 * k)
        begin = end - timedelta(days=7)
        weighed = sum(1 for p in trend if p.scale_kg is not None and begin < p.date <= end)
        if trend[0].date > begin or weighed < MIN_WEIGH_INS_PER_WEEK:
            out.append(None)
            continue
        old = on(begin)
        out.append(((on(end) - old) / old * 100).quantize(D("0.01")))
    return out


def _bmr(profile: HealthProfile | None, weight_kg: Decimal | None, year: int) -> Decimal | None:
    """The Mifflin resting rate H3 builds its estimate on, or None when it cannot be."""
    if (
        profile is None
        or weight_kg is None
        or profile.height_cm is None
        or profile.birth_year is None
    ):
        return None
    return energy_domain.mifflin_st_jeor(
        profile.sex_for_equations, weight_kg, profile.height_cm, year - profile.birth_year
    )


def _intake_for_safety(
    uow_factory: Callable[[], UnitOfWork],
) -> safety_cases.IntakeProvider:
    """Adapts ``nutrition.intake_provider`` (daily kcal for logged days) to the safety layer's
    ``IntakeDay`` list. Today is left out: a day half logged is not a day under the floor."""
    daily = nutrition_cases.intake_provider(uow_factory)

    async def provider(
        uow: UnitOfWork, user_id: UserId, *, now: datetime, floor_kcal: int
    ) -> Sequence[IntakeDay]:
        user = await uow.ledger.get_user(user_id)
        today = now.astimezone(ZoneInfo(user.timezone if user else "UTC")).date()
        found = await daily(user_id, today - timedelta(days=INTAKE_LOOKBACK_DAYS), today)
        return [
            IntakeDay(day, int(kcal.to_integral_value()), floor_kcal)
            for day, kcal in sorted(found.items())
            if day < today and kcal > 0
        ]

    return provider


async def safe_targets(
    uow_factory: Callable[[], UnitOfWork], user_id: UserId, *, now: datetime, record: bool = True
) -> SafeOverview:
    """Today's targets through the safety layer. With ``record`` a signal seen for the first
    time (in 30 days) is stored once and listed in ``new_signals``."""
    intake = nutrition_cases.intake_provider(uow_factory)
    energy, profile, trend = await energy_cases.energy_state(
        uow_factory(), user_id, now=now, intake_provider=intake
    )
    user = await _user_zone(uow_factory(), user_id)
    today = now.astimezone(user).date()
    weight = trend[-1].trend_kg if trend else None
    bmr = _bmr(profile, weight, today.year)
    history = weekly_pct_history(trend, today)

    async def weekly(uow: UnitOfWork, uid: UserId, at: datetime) -> list[Decimal | None]:
        return history

    state = await safety_cases.assess(
        uow_factory(),
        user_id,
        now=now,
        intake=_intake_for_safety(uow_factory),
        weekly_trend=weekly,
        bmr_kcal=bmr,
        record=record,
    )
    hidden = energy.hidden

    def done(result: energy_domain.Targets | None, suspended: bool) -> SafeOverview:
        return SafeOverview(
            energy_cases.TargetsOverview(result, energy, hidden),
            suspended,
            state.signposts,
            state.new_signals,
            bool(state.new_signals),
        )

    if state.suspended or energy.estimate is None or profile is None or not trend:
        return done(None, state.suspended)

    # Record what the pure step asks, put each proposal through the safety layer, replay.
    asked: list[energy_domain.TargetProposal] = []

    def record_step(p: energy_domain.TargetProposal) -> energy_domain.SafeTargets:
        asked.append(p)
        return energy_domain.SafeTargets(p.kcal, p.rate_pct_per_week)

    rate = energy_domain.default_rate_pct(profile)
    energy_domain.targets(profile, energy.estimate, trend[-1].trend_kg, rate, record_step)
    answers: dict[Decimal, energy_domain.SafeTargets] = {}
    for p in asked:
        if p.expenditure_kcal in answers:
            continue
        checked = await safety_cases.check_targets(
            uow_factory(),
            user_id,
            _proposal(p, profile.goal, bmr),
            now=now,
            intake=_intake_for_safety(uow_factory),
            weekly_trend=weekly,
        )
        if checked.suspended:
            return done(None, True)
        answers[p.expenditure_kcal] = _adapt(p, checked)

    def replay(p: energy_domain.TargetProposal) -> energy_domain.SafeTargets:
        return answers[p.expenditure_kcal]

    result = energy_domain.targets(profile, energy.estimate, trend[-1].trend_kg, rate, replay)
    return done(result, False)


async def _user_zone(uow: UnitOfWork, user_id: UserId) -> ZoneInfo:
    async with uow:
        user = await uow.ledger.get_user(user_id)
    return ZoneInfo(user.timezone if user else "UTC")


def _proposal(
    p: energy_domain.TargetProposal, goal: Goal, bmr: Decimal | None
) -> safety_cases.TargetProposal:
    """H3's proposal in H2's terms. A loss is asked for as a rate, so the safety layer fits
    the calories to the rate it allows; anything else is asked for as calories."""
    if goal is Goal.LOSE:
        return safety_cases.TargetProposal(
            goal,
            rate_pct_per_week=-p.rate_pct_per_week,
            weight_kg=p.weight_kg,
            tdee_kcal=p.expenditure_kcal,
            bmr_kcal=bmr,
        )
    return safety_cases.TargetProposal(
        goal, calories_kcal=int(p.kcal.to_integral_value()), weight_kg=p.weight_kg, bmr_kcal=bmr
    )


def _adapt(
    p: energy_domain.TargetProposal, checked: safety_cases.SafeTargets
) -> energy_domain.SafeTargets:
    notes = tuple(_NOTES[r] for r in checked.reasons if r in _NOTES)
    if checked.goal is Goal.LOSE and checked.calories_kcal is not None:
        return energy_domain.SafeTargets(
            D(checked.calories_kcal), -(checked.rate_pct_per_week or D(0)), notes
        )
    if p.rate_pct_per_week < 0 and checked.goal is not Goal.LOSE:
        # A loss the gates turned into "maintain": hold at expenditure, never under the floor.
        kcal = D(max(int(p.expenditure_kcal.to_integral_value()), checked.floor_kcal))
        return energy_domain.SafeTargets(kcal, D(0), notes)
    kcal = D(checked.calories_kcal) if checked.calories_kcal is not None else p.kcal
    return energy_domain.SafeTargets(kcal, p.rate_pct_per_week, notes)


__all__ = ["SafeOverview", "safe_targets", "weekly_pct_history"]
