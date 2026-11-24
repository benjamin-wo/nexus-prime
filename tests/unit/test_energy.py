"""Weight trend, adaptive expenditure and targets: golden figures worked by hand."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from nexus.domain.energy import (
    ExpenditureEstimate,
    SafeTargets,
    TargetProposal,
    TrendPoint,
    adaptive_expenditure,
    estimate_from_profile,
    fibre_g,
    mifflin_st_jeor,
    targets,
    trend_rate,
    weight_trend,
)
from nexus.domain.health import ActivityLevel, Goal, HealthProfile, Sex, UnitSystem
from nexus.domain.ledger import UserId

D = Decimal
DAY1 = date(2026, 1, 1)


def at(day: int, hour: int = 8) -> datetime:
    return datetime.combine(
        DAY1 + timedelta(days=day - 1), datetime.min.time(), tzinfo=UTC
    ).replace(hour=hour)


def test_trend_golden_values_with_gaps_and_duplicates() -> None:
    # Day 1 has two weigh-ins (80.4 and 79.6): their mean, 80.0, starts the trend.
    # Day 2, 79.5, alpha 0.1:           80 + 0.1 * (79.5 - 80)               = 79.95
    # Day 3 is missed. Day 4, 79.0, a 2-day gap, alpha 1 - 0.9^2 = 0.19:
    #                                   79.95 + 0.19 * (79.0 - 79.95)        = 79.7695 -> 79.770
    # Day 5, 80.2, alpha 0.1:           79.7695 + 0.1 * (80.2 - 79.7695)     = 79.81255 -> 79.813
    # Days 6 and 7 are missed. Day 8, 79.0, a 3-day gap, alpha 1 - 0.9^3 = 0.271:
    #                       79.81255 + 0.271 * (79.0 - 79.81255) = 79.59234895 -> 79.592
    samples = [
        (at(1, 7), D("80.4")),
        (at(1, 21), D("79.6")),
        (at(2), D("79.5")),
        (at(4), D("79.0")),
        (at(5), D("80.2")),
        (at(8), D("79.0")),
    ]
    got = weight_trend(samples, tz=UTC)
    assert [(p.date - DAY1).days + 1 for p in got] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [p.scale_kg for p in got] == [
        D("80.000"), D("79.500"), None, D("79.000"), D("80.200"), None, None, D("79.000"),
    ]  # fmt: skip
    assert [p.trend_kg for p in got] == [
        D("80.000"), D("79.950"), D("79.950"), D("79.770"), D("79.813"), D("79.813"),
        D("79.813"), D("79.592"),
    ]  # fmt: skip


def test_a_gap_equals_that_many_single_day_steps_over_thirty_days() -> None:
    days = [1, 2, 4, 5, 6, 9, 10, 13, 14, 15, 19, 22, 23, 24, 28, 30]
    kgs = [
        D(x)
        for x in (
            "82.0 81.2 81.9 80.7 81.1 80.3 80.9 80.0 79.8 80.4 79.5 79.9 79.2 79.6 78.8 79.1"
        ).split()
    ]
    got = weight_trend([(at(d), k) for d, k in zip(days, kgs, strict=True)], tz=UTC)
    assert len(got) == 30
    trend, previous = kgs[0], days[0]
    expected = {days[0]: trend}
    for d, k in list(zip(days, kgs, strict=True))[1:]:
        for _ in range(d - previous):  # each missed day also smooths toward the next reading
            trend += D("0.1") * (k - trend)
        expected[d], previous = trend, d
    for p in got:
        if p.scale_kg is not None:
            assert abs(p.trend_kg - expected[(p.date - DAY1).days + 1]) <= D("0.001")


def test_trend_uses_the_users_day_not_utc() -> None:
    sgt = timedelta(hours=8)
    from datetime import timezone

    tz = timezone(sgt)
    late = datetime(2026, 1, 1, 17, 0, tzinfo=UTC)  # 01:00 on 2 Jan in Singapore
    assert weight_trend([(late, D("70"))], tz=tz)[0].date == date(2026, 1, 2)
    assert weight_trend([], tz=tz) == []


def _line(n: int, step: str, scale_every: int = 1) -> list[TrendPoint]:
    return [
        TrendPoint(DAY1 + timedelta(days=i), D("80") if i % scale_every == 0 else None,
                   D("80") + D(step) * i)
        for i in range(n)
    ]  # fmt: skip


def test_trend_rate_on_a_straight_line() -> None:
    # 80.0 falling 0.1 a day for 10 days: slope -0.1/day = -0.7 kg a week; the last trend is
    # 79.1, so -0.7 / 79.1 = -0.885% -> -0.88.
    assert trend_rate(_line(10, "-0.1")) == (D("-0.700"), D("-0.88"))
    assert trend_rate(_line(10, "0")) == (D("0.000"), D("0.00"))


def test_trend_rate_needs_four_weigh_ins_in_the_window() -> None:
    assert trend_rate([]) is None
    assert trend_rate(_line(10, "-0.1", scale_every=4)) is None  # days 0, 4, 8: three
    assert trend_rate(_line(10, "-0.1", scale_every=3)) is not None  # days 0, 3, 6, 9
    # Only the last 14 days count: a long gap leaves too few.
    old = _line(5, "-0.1")
    assert trend_rate([*old, TrendPoint(DAY1 + timedelta(days=60), D("70"), D("70"))]) is None


def test_mifflin_st_jeor_worked_examples() -> None:
    # Man, 30 y, 80 kg, 180 cm: 800 + 1125 - 150 + 5 = 1780.
    assert mifflin_st_jeor(Sex.MALE, D(80), D(180), 30) == D(1780)
    # Woman, 40 y, 65 kg, 165 cm: 650 + 1031.25 - 200 - 161 = 1320.25.
    assert mifflin_st_jeor(Sex.FEMALE, D(65), D(165), 40) == D("1320.25")
    # Unspecified uses the mean constant, (5 - 161) / 2 = -78: 800 + 1125 - 150 - 78.
    assert mifflin_st_jeor(Sex.UNSPECIFIED, D(80), D(180), 30) == D(1697)


def profile(**kw: object) -> HealthProfile:
    base: dict[str, object] = {
        "user_id": UserId(uuid4()), "sex_for_equations": Sex.MALE, "birth_year": 1996,
        "height_cm": D(180), "activity_level": ActivityLevel.MODERATE, "goal": Goal.LOSE,
        "target_rate_pct_per_week": D("0.5"), "numbers_free": False, "ed_history": False,
        "unit_system": UnitSystem.METRIC, "updated_at": at(1),
    }  # fmt: skip
    return HealthProfile(**{**base, **kw})  # type: ignore[arg-type]


def test_the_profile_estimate_applies_the_activity_factor() -> None:
    assert estimate_from_profile(profile(), D(80), this_year=2026) == D(2759)  # 1780 * 1.55
    for level, factor in zip(ActivityLevel, ["1.2", "1.375", "1.55", "1.725", "1.9"], strict=True):
        got = estimate_from_profile(profile(activity_level=level), D(80), this_year=2026)
        assert got == (D(1780) * D(factor)).quantize(D(1), rounding="ROUND_HALF_UP")
    assert estimate_from_profile(profile(height_cm=None), D(80), this_year=2026) is None
    assert estimate_from_profile(profile(activity_level=None), D(80), this_year=2026) is None


END = date(2026, 3, 1)


def span(start_kg: str, end_kg: str, *, days: int = 21) -> list[TrendPoint]:
    return [
        TrendPoint(END - timedelta(days=days), D(start_kg), D(start_kg)),
        TrendPoint(END, D(end_kg), D(end_kg)),
    ]


def intake(kcal: int, *, skip: set[int] = frozenset(), days: int = 21) -> dict[date, Decimal]:  # type: ignore[assignment]
    return {END - timedelta(days=i): D(kcal) for i in range(days) if i not in skip}


def test_steady_weight_means_expenditure_equals_intake() -> None:
    got = adaptive_expenditure(intake(2000), span("80", "80"), prior_kcal=D(2400))
    assert (got.kcal, got.confidence, got.days_used, got.paused_reason) == (D(2000), D(1), 21, None)
    assert got.kcal_range == (D(1900), D(2100))  # 5% at full confidence


def test_losing_half_a_kilo_a_week_adds_550() -> None:
    # 2000 - 7700 * (-1.5 kg) / 21 days = 2000 + 550.
    got = adaptive_expenditure(intake(2000), span("80", "78.5"), prior_kcal=D(2400))
    assert got.kcal == D(2550)
    gain = adaptive_expenditure(intake(2000), span("80", "81.5"), prior_kcal=D(2400))
    assert gain.kcal == D(1450)


def test_pause_rules_return_the_prior_with_a_reason() -> None:
    four_of_seven = adaptive_expenditure(
        intake(2000, skip={0, 1, 2, 3}), span("80", "80"), prior_kcal=D(2400)
    )
    assert four_of_seven.kcal == D(2400) and four_of_seven.paused_reason is not None
    assert "3 of the last 7" in four_of_seven.paused_reason
    assert four_of_seven.kcal_range == (D(2040), D(2760))  # 15% with no confidence
    three_of_seven = adaptive_expenditure(
        intake(2000, skip={0, 1, 2}), span("80", "80"), prior_kcal=D(2400)
    )
    assert three_of_seven.paused_reason is None  # three missing is still allowed
    nine = adaptive_expenditure(intake(2000, days=9), span("80", "80"), prior_kcal=D(2400))
    assert nine.kcal == D(2400) and "fewer than 10" in (nine.paused_reason or "")
    ten = adaptive_expenditure(intake(2000, days=10), span("80", "80"), prior_kcal=D(2400))
    assert ten.paused_reason is None
    short = adaptive_expenditure(intake(2000), span("80", "80", days=3), prior_kcal=D(2400))
    assert short.paused_reason is not None and "week" in short.paused_reason
    assert adaptive_expenditure({}, [], prior_kcal=D(2400)).paused_reason == "no weigh-ins yet"
    zero_days = {d: D(0) for d in intake(2000)}  # a zero is not a logged day
    assert adaptive_expenditure(zero_days, span("80", "80"), prior_kcal=D(2400)).paused_reason


def test_low_confidence_blends_toward_the_prior() -> None:
    # 14 of 21 days logged (the last 7 all logged): confidence 2/3; raw 2000, prior 2300:
    # 2/3 * 2000 + 1/3 * 2300 = 2100.
    got = adaptive_expenditure(
        intake(2000, skip=set(range(10, 17))), span("80", "80"), prior_kcal=D(2300)
    )
    assert got.days_used == 14 and got.paused_reason is None
    assert got.kcal == D(2100)
    assert D("0.66") < got.confidence < D("0.67")


def test_an_update_moves_at_most_100_kcal() -> None:
    steady = span("80", "80")
    assert adaptive_expenditure(
        intake(2000), steady, prior_kcal=D(2000), previous_kcal=D(1800)
    ).kcal == D(1900)
    assert adaptive_expenditure(
        intake(2000), steady, prior_kcal=D(2000), previous_kcal=D(2300)
    ).kcal == D(2200)
    assert adaptive_expenditure(
        intake(2000), steady, prior_kcal=D(2000), previous_kcal=D(1950)
    ).kcal == D(2000)


class Recorder:
    def __init__(self, floor: int = 0) -> None:
        self.calls: list[TargetProposal] = []
        self.floor = D(floor)

    def __call__(self, proposal: TargetProposal, /) -> SafeTargets:
        self.calls.append(proposal)
        if proposal.kcal < self.floor:
            return SafeTargets(self.floor, D("0.2"), ("raised to the floor",))
        return SafeTargets(proposal.kcal, proposal.rate_pct_per_week)


def est(kcal: int) -> ExpenditureEstimate:
    return ExpenditureEstimate(D(kcal), D(0), 0, "x", (D(kcal) - 100, D(kcal) + 100))


def test_targets_pass_the_proposal_through_the_safety_step() -> None:
    # 0.5% of 80 kg = 0.4 kg a week; x 7700 / 7 = 440 kcal a day off 2500 = 2060.
    safety = Recorder()
    got = targets(profile(), est(2500), D(80), D("0.5"), safety)
    first = safety.calls[0]
    assert (first.expenditure_kcal, first.rate_pct_per_week, first.kcal, first.weight_kg) == (
        D(2500), D("-0.5"), D(2060), D(80),
    )  # fmt: skip
    assert len(safety.calls) == 3  # the figure, then the low and high of its range
    # the low and high expenditure (2400, 2600) take the same 440 off: 1960 and 2160
    assert got.kcal == D(2060) and got.kcal_range == (D(1960), D(2160))
    assert got.protein_g == D(128)  # 1.6 g x 80 kg
    assert got.fibre_g == D(29)  # 14 g x 2.06 = 28.84 -> 29
    assert got.notes == ()


def test_the_safety_step_can_change_the_result() -> None:
    got = targets(profile(), est(2500), D(80), D("0.5"), Recorder(floor=2200))
    assert got.kcal == D(2200) and got.rate_pct_per_week == D("0.2")
    assert got.notes == ("raised to the floor",)
    assert got.fibre_g == D(31)  # 14 x 2.2 = 30.8


def test_goal_sets_the_direction_of_the_adjustment() -> None:
    for goal, signed in [
        (Goal.GAIN, D("0.5")), (Goal.MAINTAIN, D(0)), (Goal.PERFORMANCE, D(0)),
    ]:  # fmt: skip
        safety = Recorder()
        got = targets(profile(goal=goal), est(2500), D(80), D("0.5"), safety)
        assert safety.calls[0].rate_pct_per_week == signed
        assert got.kcal == D(2500) + (D(440) if signed else D(0))


def test_fibre_has_a_floor() -> None:
    assert fibre_g(D(1500)) == D(25)  # 21 g would be less than the floor
    assert fibre_g(D(2500)) == D(35)
