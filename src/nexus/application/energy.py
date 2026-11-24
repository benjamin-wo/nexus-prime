"""Weight trend, expenditure and daily targets, worked from the user's weigh-ins and profile.

Nothing is stored: every figure is computed from ``health_samples`` and the profile. Food
intake doesn't exist yet, so the expenditure takes an injected ``IntakeProvider`` (none by
default). With ``numbers_free`` on, everything is still computed, ``hidden`` is True, and the
API layer shows only the qualitative ``trend_words``.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from nexus.application.ports import UnitOfWork
from nexus.domain.energy import (
    RATE_DAYS,
    ExpenditureEstimate,
    SafetyStep,
    Targets,
    TrendPoint,
    adaptive_expenditure,
    default_rate_pct,
    estimate_from_profile,
    targets,
    trend_rate,
    weight_trend,
)
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.health import HealthProfile, SampleKind, Sex
from nexus.domain.health_texts import Signpost
from nexus.domain.ledger import UserId

MAX_DAYS = 365
WINDOW_DAYS = 21
CONFIDENCE_STEP = Decimal("0.01")
WARM_UP = timedelta(
    days=60
)  # earlier weigh-ins so a 90-day view isn't a cold start (0.9**60 ~ 0.002)
STEADY_PCT_PER_WEEK = Decimal("0.1")  # under this a week the trend is "steady" (design figure)
BASIS_PROFILE = "profile"
BASIS_LOGGED = "logged"
LABEL_PROFILE = "estimated from your profile"
LABEL_LOGGED = "worked out from your logged food and weight"

IntakeProvider = Callable[[UserId, date, date], Awaitable[dict[date, Decimal]]]
"""Daily logged kcal for the user from the first date to the last, both included."""


async def no_intake(user_id: UserId, first: date, last: date) -> dict[date, Decimal]:
    return {}


@dataclass(frozen=True, slots=True)
class WeightOverview:
    points: list[TrendPoint]  # the last ``days`` days
    trend_kg: Decimal | None
    rate: tuple[Decimal, Decimal] | None  # kg a week, percent a week
    rate_days: int
    last_weigh_in: tuple[datetime, Decimal] | None
    trend_words: str
    hidden: bool


@dataclass(frozen=True, slots=True)
class EnergyOverview:
    estimate: ExpenditureEstimate | None  # None until the profile and a weight allow one
    basis: str | None  # BASIS_PROFILE or BASIS_LOGGED
    label: str | None
    trend_words: str
    hidden: bool


@dataclass(frozen=True, slots=True)
class TargetsOverview:
    targets: Targets | None
    energy: EnergyOverview
    hidden: bool


def rate_words(rate: tuple[Decimal, Decimal] | None) -> str:
    """The trend in words alone: steady, slowly down, slowly up, or not enough data."""
    if rate is None:
        return "not enough weigh-ins yet to say"
    _, pct = rate
    if abs(pct) < STEADY_PCT_PER_WEEK:
        return "steady"
    return "slowly down" if pct < 0 else "slowly up"


def rate_sentence(rate: tuple[Decimal, Decimal] | None, days: int = RATE_DAYS) -> str | None:
    """ "about 0.4 kg a week down over the last 2 weeks", built from the numbers."""
    if rate is None:
        return None
    kg, pct = rate
    span = f"{days // 7} weeks" if days % 7 == 0 and days > 7 else f"{days} days"
    if abs(pct) < STEADY_PCT_PER_WEEK:
        return f"about steady over the last {span}"
    way = "down" if kg < 0 else "up"
    return f"about {abs(kg):.1f} kg a week {way} over the last {span}"


async def _context(
    uow: UnitOfWork, user_id: UserId, *, now: datetime, days: int
) -> tuple[HealthProfile | None, ZoneInfo, list[tuple[datetime, Decimal]]]:
    async with uow:
        user = await uow.ledger.get_user(user_id)
        if user is None:
            raise NotFound("user not found")
        found = await uow.health.list_samples(
            user_id,
            kind=SampleKind.WEIGHT,
            start=now - timedelta(days=days) - WARM_UP,
            end=now + timedelta(days=1),
            limit=1000,
        )
        profile = await uow.health.get_profile(user_id)
    weights = [(s.start_at, s.weight_kg) for s in found if s.weight_kg is not None]
    return profile, ZoneInfo(user.timezone), weights


async def weight_overview(
    uow: UnitOfWork, user_id: UserId, *, now: datetime, days: int = 90
) -> WeightOverview:
    """The trend over the last ``days`` days, today's trend, its weekly rate over the last 2
    weeks, and the last weigh-in."""
    if not 1 <= days <= MAX_DAYS:
        raise InvalidInput(f"days is between 1 and {MAX_DAYS}")
    profile, tz, weights = await _context(uow, user_id, now=now, days=days)
    everything = weight_trend(weights, tz=tz)
    first = now.astimezone(tz).date() - timedelta(days=days - 1)
    last = max(weights, key=lambda w: w[0]) if weights else None
    rate = trend_rate(everything)
    return WeightOverview(
        points=[p for p in everything if p.date >= first],
        trend_kg=everything[-1].trend_kg if everything else None,
        rate=rate,
        rate_days=RATE_DAYS,
        last_weigh_in=last,
        trend_words=rate_words(rate),
        hidden=bool(profile and profile.numbers_free),
    )


async def expenditure(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    now: datetime,
    intake_provider: IntakeProvider = no_intake,
) -> EnergyOverview:
    """Energy use: worked out from logged food and weight when there is enough of both,
    otherwise Mifflin-St Jeor x activity, labelled as estimated from the profile. The
    estimate is None when the profile lacks a height, birth year or activity level, or there
    is no weigh-in."""
    energy, _, _ = await _energy(uow, user_id, now, intake_provider)
    return energy


async def energy_state(
    uow: UnitOfWork, user_id: UserId, *, now: datetime, intake_provider: IntakeProvider = no_intake
) -> tuple[EnergyOverview, HealthProfile | None, list[TrendPoint]]:
    """The energy overview with the profile and the weight trend behind it."""
    return await _energy(uow, user_id, now, intake_provider)


async def _energy(
    uow: UnitOfWork, user_id: UserId, now: datetime, intake_provider: IntakeProvider
) -> tuple[EnergyOverview, HealthProfile | None, list[TrendPoint]]:
    profile, tz, weights = await _context(uow, user_id, now=now, days=90)
    trend = weight_trend(weights, tz=tz)
    words = rate_words(trend_rate(trend))
    hidden = bool(profile and profile.numbers_free)
    none = EnergyOverview(None, None, None, words, hidden), profile, trend
    if profile is None or not trend:
        return none
    today = now.astimezone(tz).date()
    prior = estimate_from_profile(profile, trend[-1].trend_kg, this_year=today.year)
    if prior is None:
        return none
    intake = await intake_provider(user_id, today - timedelta(days=WINDOW_DAYS), today)
    estimate = adaptive_expenditure(intake, trend, window=WINDOW_DAYS, prior_kcal=prior, end=today)
    logged = estimate.paused_reason is None
    basis, label = (BASIS_LOGGED, LABEL_LOGGED) if logged else (BASIS_PROFILE, LABEL_PROFILE)
    return EnergyOverview(estimate, basis, label, words, hidden), profile, trend


async def current_targets(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    now: datetime,
    intake_provider: IntakeProvider = no_intake,
    apply_safety: SafetyStep,
) -> TargetsOverview:
    """Today's calories, protein and fibre from the expenditure, the current trend weight and
    the profile's goal, passed through ``apply_safety``. None without an estimate."""
    energy, profile, trend = await _energy(uow, user_id, now, intake_provider)
    if energy.estimate is None or profile is None:
        return TargetsOverview(None, energy, energy.hidden)
    result = targets(
        profile, energy.estimate, trend[-1].trend_kg, default_rate_pct(profile), apply_safety
    )
    return TargetsOverview(result, energy, energy.hidden)


def missing_inputs(profile: HealthProfile | None) -> list[str]:
    """What the profile still needs before an estimate can be made: height, birth year, sex
    (``Sex.UNSPECIFIED`` is how an unset sex is stored) and activity level."""
    if profile is None:
        return ["height", "birth year", "sex", "activity level"]
    found = [
        ("height", profile.height_cm is not None),
        ("birth year", profile.birth_year is not None),
        ("sex", profile.sex_for_equations is not Sex.UNSPECIFIED),
        ("activity level", profile.activity_level is not None),
    ]
    return [name for name, present in found if not present]


def _kcal(value: Decimal) -> str:
    return f"{value:.0f}"


def energy_text(
    overview: TargetsOverview, *, suspended: bool, signposts: tuple[Signpost, ...]
) -> str:
    """The energy estimate for the model to quote, built from the figures: a range, how it was
    worked out, and today's targets when there are any. With numbers-free mode on it is words
    only; when calorie targets are suspended there are none and the signposts are listed."""
    energy = overview.energy
    lines: list[str] = []
    if overview.hidden:
        lines.append(
            f"Numbers-free mode is on, so no figures: your weight trend is {energy.trend_words}."
        )
    elif energy.estimate is not None:
        e = energy.estimate
        low, high = e.kcal_range
        lines.append(
            f"Daily energy use, {energy.label}: about {_kcal(low)}-{_kcal(high)} kcal "
            f"(point {_kcal(e.kcal)} kcal)."
        )
        if energy.basis == BASIS_LOGGED:
            lines.append(f"Based on {e.days_used} logged days.")
        lines.append(f"Weight trend: {energy.trend_words}.")
        t = overview.targets
        if t is not None and not suspended:
            lines.append(
                f"Today's targets: {_kcal(t.kcal)} kcal (range {_kcal(t.kcal_range[0])}-"
                f"{_kcal(t.kcal_range[1])}), {t.protein_g:.0f} g protein, {t.fibre_g:.0f} g fibre."
            )
            lines.extend(t.notes)
    if suspended:
        lines.append("Calorie targets are switched off, so there are none to give.")
        lines.extend(f"- {s.name}: {s.contact}. {s.note}" for s in signposts)
    return "\n".join(lines)
