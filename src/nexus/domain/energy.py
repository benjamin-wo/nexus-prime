"""Weight trend, adaptive energy expenditure and daily targets. Pure rules, no I/O, all Decimal.

Sources (from the Nexus Health research report, section C):

* Hacker's Diet (John Walker), "Signal and Noise": the weight trend is an exponentially
  smoothed average, ``trend_t = trend_{t-1} + 0.1 * (w_t - trend_{t-1})``, about a 20-day
  moving average. For irregular weigh-ins the same idea, time-aware, is
  ``alpha_eff = 1 - (1 - alpha) ** days`` (the report's inference from the Hacker's Diet).
* Hall 2008 and Hall & Chow 2013 (NIH): 7,700 kcal per kg is the working energy density of
  body-weight change. It suits people with more body fat and overstates it for lean people,
  and it ignores dynamic adaptation; both matter less for a rolling back-calculation than for
  long-range forecasts.
* MacroFactor's public explanations (help centre, "Expenditure V3"): expenditure is a
  deterministic back-calculation from logged intake and the weight trend; updates pause when
  more than 3 of 7 days are unlogged; an unlogged day is never 0 kcal; each update is capped.
  Their accuracy figures are self-reported.
* Mifflin et al. 1990 (Am J Clin Nutr 51:241): the resting-rate equation. Frankenfield 2003
  found it off by more than 10% for 22% of people, so every estimate here carries a range.
* Morton et al. 2018 (meta-analysis of 49 RCTs): no further fat-free-mass gain above about
  1.62 g of protein per kg a day; the default is 1.6.

Nothing here is medical advice. Whether a target is safe is decided by an injected safety
step (``SafetyStep``), never here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from nexus.domain.health import ActivityLevel, Goal, HealthProfile, Sex

D = Decimal
_KG = D("0.001")
_PCT = D("0.01")
_ONE = D(1)

# Hacker's Diet: 10% smoothing per day.
TREND_ALPHA = D("0.1")
# Hall 2008 / Hall & Chow 2013: working energy density of weight change, kcal per kg.
KCAL_PER_KG = D(7700)
# Window for the rate; the report asks for 3-4 weigh-ins a week before stating one.
RATE_DAYS = 14
RATE_MIN_WEIGH_INS = 4

# Mifflin-St Jeor (1990): kcal/day = 10 kg + 6.25 cm - 5 age + constant.
MIFFLIN_SEX_CONSTANT: dict[Sex, Decimal] = {Sex.MALE: D(5), Sex.FEMALE: D(-161)}
# "Unspecified" is the mean of the two constants, (5 - 161) / 2 = -78: the equation's
# prediction for a person of unknown sex, wrong by at most 83 kcal either way.
MIFFLIN_SEX_CONSTANT[Sex.UNSPECIFIED] = (
    MIFFLIN_SEX_CONSTANT[Sex.MALE] + MIFFLIN_SEX_CONSTANT[Sex.FEMALE]
) / 2
# The usual five activity factors applied to the resting rate (as in the report's 1.2-1.9).
ACTIVITY_FACTOR: dict[ActivityLevel, Decimal] = {
    ActivityLevel.SEDENTARY: D("1.2"),
    ActivityLevel.LIGHT: D("1.375"),
    ActivityLevel.MODERATE: D("1.55"),
    ActivityLevel.ACTIVE: D("1.725"),
    ActivityLevel.VERY_ACTIVE: D("1.9"),
}

# Adaptive expenditure.
DEFAULT_WINDOW_DAYS = 21  # the report's rolling 14-28 days
RECENT_DAYS = 7
MAX_UNLOGGED_RECENT = 3  # MacroFactor V3: pause when more than 3 of 7 days are unlogged
MIN_LOGGED_DAYS = 10
MIN_SPAN_DAYS = 7  # a trend shorter than a week says little about energy balance
MAX_STEP_KCAL = D(100)  # the report: cap each update at about 50-100 kcal
# Design proposals, not published figures: the half-width of the range as a share of the
# estimate. 15% with no logging (the report's "10-15%" for the Mifflin start), 5% when every
# day of the window is logged.
UNCERTAINTY_NO_DATA = D("0.15")
UNCERTAINTY_FULL_DATA = D("0.05")

# Targets.
PROTEIN_G_PER_KG = D("1.6")  # Morton 2018
# CHECK SOURCE: 14 g per 1,000 kcal is recalled from memory in the report, not verified.
FIBRE_G_PER_1000_KCAL = D(14)
FIBRE_FLOOR_G = D(25)  # EFSA 2010: 25 g a day
DEFAULT_LOSS_RATE_PCT = D("0.5")  # Helms 2014: 0.5-1% a week; the gentler end
# A practitioner heuristic in the report (0.25-0.5%); no primary source.
DEFAULT_GAIN_RATE_PCT = D("0.25")


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """One day: the day's scale weight (None when not weighed) and the trend on that day."""

    date: date
    scale_kg: Decimal | None
    trend_kg: Decimal


def weight_trend(samples: Sequence[tuple[datetime, Decimal]], *, tz: tzinfo) -> list[TrendPoint]:
    """A time-aware exponentially weighted trend, one point per day from the first weigh-in
    to the last (Hacker's Diet, smoothing 0.1 a day).

    Weigh-ins are grouped by their date in ``tz``; several on one day count as their **mean**
    (order-independent, and it damps a stray reading better than keeping the first). The trend
    starts at the first day's weight. After a gap of ``n`` days the next weigh-in moves it by
    ``alpha_eff = 1 - (1 - 0.1) ** n``, which is exactly ``n`` single days of smoothing toward
    one reading; days in between show the trend carried forward (``scale_kg`` None). Figures
    are rounded to grams on output only.
    """
    by_day: dict[date, list[Decimal]] = {}
    for at, kg in samples:
        by_day.setdefault(at.astimezone(tz).date(), []).append(kg)
    points: list[TrendPoint] = []
    trend = D(0)
    last: date | None = None
    for day in sorted(by_day):
        weights = by_day[day]
        scale = (sum(weights, D(0)) / len(weights)).quantize(_KG, rounding=ROUND_HALF_UP)
        if last is None:
            trend = scale
        else:
            gap = (day - last).days
            for i in range(1, gap):
                points.append(
                    TrendPoint(
                        last + timedelta(days=i), None, trend.quantize(_KG, rounding=ROUND_HALF_UP)
                    )
                )
            alpha = _ONE - (_ONE - TREND_ALPHA) ** gap
            trend += alpha * (scale - trend)
        points.append(TrendPoint(day, scale, trend.quantize(_KG, rounding=ROUND_HALF_UP)))
        last = day
    return points


def trend_rate(
    points: Sequence[TrendPoint], days: int = RATE_DAYS
) -> tuple[Decimal, Decimal] | None:
    """The trend's slope as (kg a week, percent of the current trend a week), from a
    least-squares line through the trend on weigh-in days in the last ``days`` days (ending at
    the last point). None with fewer than 4 weigh-ins in that window."""
    if not points:
        return None
    end = points[-1].date
    start = end - timedelta(days=days - 1)
    window = [p for p in points if p.scale_kg is not None and p.date >= start]
    if len(window) < RATE_MIN_WEIGH_INS:
        return None
    xs = [D((p.date - end).days) for p in window]
    ys = [p.trend_kg for p in window]
    n = D(len(window))
    sx, sy = sum(xs, D(0)), sum(ys, D(0))
    sxy = sum((x * y for x, y in zip(xs, ys, strict=True)), D(0))
    sxx = sum((x * x for x in xs), D(0))
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)  # kg a day; the days are distinct
    per_week = (slope * 7).quantize(_KG, rounding=ROUND_HALF_UP)
    current = points[-1].trend_kg
    pct = (per_week / current * 100).quantize(_PCT, rounding=ROUND_HALF_UP)
    return per_week, pct


def mifflin_st_jeor(sex: Sex, weight_kg: Decimal, height_cm: Decimal, age: int) -> Decimal:
    """Resting energy in kcal a day (Mifflin et al. 1990): 10 kg + 6.25 cm - 5 age + c, with
    c = +5 for men and -161 for women. For ``Sex.UNSPECIFIED`` c is the mean of the two,
    -78. Exact, not rounded."""
    return 10 * weight_kg + D("6.25") * height_cm - 5 * age + MIFFLIN_SEX_CONSTANT[sex]


def estimate_from_profile(
    profile: HealthProfile, weight_kg: Decimal, *, this_year: int
) -> Decimal | None:
    """Mifflin-St Jeor times the activity factor, rounded to whole kcal; None until the
    profile has a height, a birth year and an activity level."""
    if profile.height_cm is None or profile.birth_year is None or profile.activity_level is None:
        return None
    rest = mifflin_st_jeor(
        profile.sex_for_equations, weight_kg, profile.height_cm, this_year - profile.birth_year
    )
    return _kcal(rest * ACTIVITY_FACTOR[profile.activity_level])


def _kcal(value: Decimal) -> Decimal:
    return value.quantize(_ONE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ExpenditureEstimate:
    """Daily energy use: the figure, how far to trust it (0 to 1), the logged days behind
    it, the range it probably lies in, and why it was held at the prior (None when it
    wasn't)."""

    kcal: Decimal
    confidence: Decimal
    days_used: int
    paused_reason: str | None
    kcal_range: tuple[Decimal, Decimal]


def _range(kcal: Decimal, confidence: Decimal) -> tuple[Decimal, Decimal]:
    share = UNCERTAINTY_NO_DATA - (UNCERTAINTY_NO_DATA - UNCERTAINTY_FULL_DATA) * confidence
    half = kcal * share
    return _kcal(kcal - half), _kcal(kcal + half)


def adaptive_expenditure(
    intake_by_day: dict[date, Decimal],
    trend: Sequence[TrendPoint],
    *,
    window: int = DEFAULT_WINDOW_DAYS,
    prior_kcal: Decimal,
    end: date | None = None,
    previous_kcal: Decimal | None = None,
) -> ExpenditureEstimate:
    """Expenditure worked back from what was eaten and how the trend moved (a deterministic
    back-calculation, as MacroFactor describes its own).

    The window is the ``window`` days ending on ``end`` (default: the trend's last day). Only
    days in ``intake_by_day`` with more than 0 kcal count as logged; an unlogged day is
    never treated as 0.

    * raw = mean logged intake - 7700 x (trend at the window's end - trend at the day before
      it) / days. If the trend starts inside the window the baseline is its first day.
    * Paused (the prior is returned, with a reason) when more than 3 of the last 7 days are
      unlogged, when fewer than 10 days are logged, or when the trend covers under 7 days.
    * confidence = logged days / days in the window (0 to 1); the result is the weighted mean
      ``confidence * raw + (1 - confidence) * prior``.
    * With ``previous_kcal`` the result moves at most 100 kcal from it (the report: cap each
      update at about 50-100 kcal).
    * The range is the estimate +/- a share that falls linearly from 15% (confidence 0) to 5%
      (confidence 1). These are design figures, not published ones.
    """
    if not trend:
        return _paused(prior_kcal, 0, "no weigh-ins yet")
    last = end or trend[-1].date
    baseline = max(last - timedelta(days=window), trend[0].date)
    days = (last - baseline).days
    logged = {d: k for d, k in intake_by_day.items() if baseline < d <= last and k > 0}
    if days < MIN_SPAN_DAYS:
        return _paused(prior_kcal, len(logged), "less than a week of weigh-ins in the window")
    recent = sum(1 for i in range(RECENT_DAYS) if last - timedelta(days=i) not in logged)
    if recent > MAX_UNLOGGED_RECENT:
        return _paused(
            prior_kcal, len(logged), "more than 3 of the last 7 days have no food logged"
        )
    if len(logged) < MIN_LOGGED_DAYS:
        return _paused(prior_kcal, len(logged), "fewer than 10 days of food logged")
    start_kg, end_kg = _trend_on(trend, baseline), _trend_on(trend, last)
    mean_intake = sum(logged.values(), D(0)) / len(logged)
    raw = mean_intake - KCAL_PER_KG * (end_kg - start_kg) / days
    confidence = min(_ONE, D(len(logged)) / days)
    blended = confidence * raw + (_ONE - confidence) * prior_kcal
    if previous_kcal is not None:
        blended = min(max(blended, previous_kcal - MAX_STEP_KCAL), previous_kcal + MAX_STEP_KCAL)
    kcal = _kcal(blended)
    return ExpenditureEstimate(kcal, confidence, len(logged), None, _range(kcal, confidence))


def _paused(prior: Decimal, days_used: int, reason: str) -> ExpenditureEstimate:
    return ExpenditureEstimate(prior, D(0), days_used, reason, _range(prior, D(0)))


def _trend_on(trend: Sequence[TrendPoint], day: date) -> Decimal:
    """The trend on a day, carried forward past the last point (the caller keeps ``day`` at
    or after the first)."""
    value = trend[0].trend_kg
    for p in trend:
        if p.date > day:
            break
        value = p.trend_kg
    return value


# --- targets ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetProposal:
    """What the safety step is asked to check. ``rate_pct_per_week`` is signed: negative to
    lose weight, positive to gain, 0 to hold."""

    profile: HealthProfile
    weight_kg: Decimal
    expenditure_kcal: Decimal
    rate_pct_per_week: Decimal
    kcal: Decimal  # expenditure plus the daily adjustment the rate asks for


@dataclass(frozen=True, slots=True)
class SafeTargets:
    """What the safety step allows: the calories and rate actually used, and neutral notes
    on anything it changed."""

    kcal: Decimal
    rate_pct_per_week: Decimal
    notes: tuple[str, ...] = ()


class SafetyStep(Protocol):
    def __call__(self, proposal: TargetProposal, /) -> SafeTargets: ...


@dataclass(frozen=True, slots=True)
class Targets:
    kcal: Decimal
    protein_g: Decimal
    fibre_g: Decimal
    kcal_range: tuple[Decimal, Decimal]
    rate_pct_per_week: Decimal  # after the safety step
    notes: tuple[str, ...]


def default_rate_pct(profile: HealthProfile) -> Decimal:
    """The weekly rate (a positive share of body weight) the profile asks for, or the
    default for its goal; 0 for maintain and performance."""
    if profile.goal not in (Goal.LOSE, Goal.GAIN):
        return D(0)
    if profile.target_rate_pct_per_week is not None:
        return profile.target_rate_pct_per_week
    return DEFAULT_LOSS_RATE_PCT if profile.goal is Goal.LOSE else DEFAULT_GAIN_RATE_PCT


def daily_adjustment(weight_kg: Decimal, rate_pct_per_week: Decimal) -> Decimal:
    """kcal a day for a weekly rate: rate/100 x weight x 7700 / 7 (signed like the rate)."""
    return rate_pct_per_week / 100 * weight_kg * KCAL_PER_KG / 7


def fibre_g(kcal: Decimal) -> Decimal:
    """14 g per 1,000 kcal, never under 25 g, to whole grams."""
    return max(FIBRE_FLOOR_G, (kcal * FIBRE_G_PER_1000_KCAL / 1000)).quantize(
        _ONE, rounding=ROUND_HALF_UP
    )


def targets(
    profile: HealthProfile,
    expenditure: ExpenditureEstimate,
    weight_kg: Decimal,
    rate_pct: Decimal,
    apply_safety: SafetyStep,
) -> Targets:
    """Daily calories, protein and fibre. ``rate_pct`` is the weekly rate as a positive
    share of body weight; its direction comes from the goal (lose: a deficit, gain: a
    surplus, otherwise none).

    The adjustment is rate x weight x 7700 / 7 applied to the expenditure, and the proposal
    goes through ``apply_safety`` (which may raise the calories or slow the rate). The range
    puts the expenditure's low and high through the same step, so it never leaves a floor.
    Protein is 1.6 g per kg of body weight; fibre per ``fibre_g``.
    """
    signed = {Goal.LOSE: -rate_pct, Goal.GAIN: rate_pct}.get(profile.goal, D(0))
    adjust = daily_adjustment(weight_kg, signed)

    def run(kcal: Decimal) -> SafeTargets:
        return apply_safety(TargetProposal(profile, weight_kg, kcal, signed, kcal + adjust))

    safe = run(expenditure.kcal)
    low, high = run(expenditure.kcal_range[0]), run(expenditure.kcal_range[1])
    kcal = _kcal(safe.kcal)
    return Targets(
        kcal,
        (PROTEIN_G_PER_KG * weight_kg).quantize(_ONE, rounding=ROUND_HALF_UP),
        fibre_g(kcal),
        (_kcal(low.kcal), _kcal(high.kcal)),
        safe.rate_pct_per_week,
        safe.notes,
    )
