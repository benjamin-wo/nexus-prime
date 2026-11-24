"""Health safety rules: floors, rates, protein, gates and eating-disorder signal thresholds, each
at the boundary and either side of it. Every figure is made up."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from nexus.domain.health import Goal, Sex
from nexus.domain.health_safety import (
    BANNED_PHRASES,
    PROTEIN_DEFICIT_FLOOR,
    PROTEIN_MAX,
    PROTEIN_MIN,
    RATE_HARD_CAP,
    IntakeDay,
    ReasonCode,
    Signal,
    banned_phrases_in,
    bmi_of,
    calorie_floor,
    calories_for_rate,
    clamp_rate,
    ed_signals,
    protein_per_kg,
    protein_target_g,
    rate_for_floor,
    safe_age,
    weekly_trend_history,
    weight_loss_allowed,
)

D = Decimal


@pytest.mark.parametrize(
    ("sex", "bmr", "floor"),
    [
        (Sex.FEMALE, None, 1200),
        (Sex.MALE, None, 1500),
        (Sex.UNSPECIFIED, None, 1500),
        (Sex.FEMALE, D(1199), 1200),
        (Sex.FEMALE, D(1200), 1200),
        (Sex.FEMALE, D(1201), 1201),
        (Sex.FEMALE, D("1200.2"), 1201),  # a fraction rounds up
        (Sex.MALE, D(1499), 1500),
        (Sex.MALE, D(1500), 1500),
        (Sex.MALE, D(1501), 1501),
        (Sex.UNSPECIFIED, D(1800), 1800),
    ],
)
def test_calorie_floor(sex: Sex, bmr: Decimal | None, floor: int) -> None:
    assert calorie_floor(sex, bmr) == floor


@pytest.mark.parametrize(
    ("goal", "requested", "bmi", "age", "rate", "reason"),
    [
        (Goal.LOSE, D("0.25"), D(25), 30, D("0.25"), ReasonCode.OK),
        (Goal.LOSE, D("0.5"), D(25), 30, D("0.5"), ReasonCode.OK),
        (Goal.LOSE, D("0.75"), D(25), 30, D("0.75"), ReasonCode.OK),
        (Goal.LOSE, D("0.9"), D(25), 30, D("0.9"), ReasonCode.OK),  # between presets is fine
        (Goal.LOSE, D("1.0"), D(25), 30, D("1.0"), ReasonCode.OK),  # exactly the cap
        (Goal.LOSE, D("1.01"), D(25), 30, RATE_HARD_CAP, ReasonCode.RATE_HARD_CAP),
        (Goal.LOSE, D(3), None, 30, RATE_HARD_CAP, ReasonCode.RATE_HARD_CAP),
        (Goal.LOSE, None, D(25), 30, D("0.5"), ReasonCode.RATE_DEFAULTED),
        (Goal.LOSE, D(0), D(25), 30, D("0.25"), ReasonCode.RATE_RAISED_TO_MINIMUM),
        (Goal.LOSE, D("-1"), D(25), 30, D("0.25"), ReasonCode.RATE_RAISED_TO_MINIMUM),
        # lean: BMI under 22 gets 0.5 at most; exactly 22 is not lean
        (Goal.LOSE, D("0.75"), D("21.9"), 30, D("0.5"), ReasonCode.RATE_LEAN_LIMIT),
        (Goal.LOSE, D("0.5"), D("21.9"), 30, D("0.5"), ReasonCode.OK),
        (Goal.LOSE, D("0.25"), D("21.9"), 30, D("0.25"), ReasonCode.OK),
        (Goal.LOSE, D("0.75"), D("22.0"), 30, D("0.75"), ReasonCode.OK),
        (Goal.LOSE, D("2"), D("21.9"), 30, D("0.5"), ReasonCode.RATE_LEAN_LIMIT),
        # gated: no rate at all
        (Goal.LOSE, D("0.5"), D(25), 17, None, ReasonCode.UNDER_18),
        (Goal.LOSE, D("0.5"), D(25), 18, D("0.5"), ReasonCode.OK),
        (Goal.LOSE, D("0.5"), D("18.4"), 30, None, ReasonCode.LOW_BMI),
        (Goal.LOSE, D("0.5"), D("18.5"), 30, D("0.5"), ReasonCode.OK),
        # not a loss goal: left alone
        (Goal.MAINTAIN, None, D(25), 30, None, ReasonCode.RATE_NOT_APPLICABLE),
        (Goal.GAIN, D("0.5"), D(25), 30, D("0.5"), ReasonCode.RATE_NOT_APPLICABLE),
    ],
)
def test_clamp_rate(
    goal: Goal,
    requested: Decimal | None,
    bmi: Decimal | None,
    age: int,
    rate: Decimal | None,
    reason: ReasonCode,
) -> None:
    decision = clamp_rate(goal, requested, bmi, age)
    assert (decision.rate, decision.reason) == (rate, reason)


@pytest.mark.parametrize(
    ("choice", "per_kg"),
    [
        (D("1.39"), PROTEIN_MIN),
        (D("1.4"), D("1.4")),
        (D("1.6"), D("1.6")),
        (D("2.2"), D("2.2")),
        (D("2.21"), PROTEIN_MAX),
        (D("0.5"), PROTEIN_MIN),
        (D(5), PROTEIN_MAX),
    ],
)
@pytest.mark.parametrize("deficit", [False, True])
def test_protein_range_and_deficit_floor(choice: Decimal, per_kg: Decimal, deficit: bool) -> None:
    got = protein_per_kg(choice, in_deficit=deficit)
    assert got == per_kg
    assert got >= PROTEIN_DEFICIT_FLOOR  # never below 1.2 g/kg, in a deficit or out of one


def test_protein_grams() -> None:
    assert protein_target_g(D(80)) == 128  # 1.6 g/kg
    assert protein_target_g(D(80), D("2.2")) == 176
    assert protein_target_g(D(80), D("1.0"), in_deficit=True) == 112  # held to 1.4
    assert protein_target_g(D("70.3")) == 112  # rounds to a whole gram


@pytest.mark.parametrize(
    ("age", "bmi", "ed", "allowed", "reason"),
    [
        (30, D(25), False, True, ReasonCode.OK),
        (18, D(25), False, True, ReasonCode.OK),  # exactly 18
        (17, D(25), False, False, ReasonCode.UNDER_18),
        (30, D("18.5"), False, True, ReasonCode.OK),  # exactly 18.5
        (30, D("18.4"), False, False, ReasonCode.LOW_BMI),
        (30, D(25), True, False, ReasonCode.ED_HISTORY),
        (None, D(25), False, False, ReasonCode.AGE_UNKNOWN),
        (30, None, False, False, ReasonCode.BMI_UNKNOWN),
        (17, D("18.4"), False, False, ReasonCode.UNDER_18),  # age is checked first
    ],
)
def test_weight_loss_gate(
    age: int | None, bmi: Decimal | None, ed: bool, allowed: bool, reason: ReasonCode
) -> None:
    gate = weight_loss_allowed(age, bmi, ed)
    assert (gate.allowed, gate.reason) == (allowed, reason)


def test_ed_history_override_needs_a_confirm_and_never_beats_age_or_bmi() -> None:
    ok = weight_loss_allowed(30, D(25), True, ed_override_confirmed=True)
    assert (ok.allowed, ok.reason) == (True, ReasonCode.ED_OVERRIDDEN)
    for age, bmi, reason in [(17, D(25), ReasonCode.UNDER_18), (30, D(18), ReasonCode.LOW_BMI)]:
        gate = weight_loss_allowed(age, bmi, True, ed_override_confirmed=True)
        assert (gate.allowed, gate.reason) == (False, reason)


def test_age_is_the_youngest_possible() -> None:
    assert safe_age(2008, 2026) == 17  # could turn 18 any time in 2026: not yet
    assert safe_age(2008, 2027) == 18
    assert safe_age(None, 2026) is None


def test_bmi() -> None:
    assert bmi_of(D(70), D(175)) == D("22.9")
    assert bmi_of(None, D(175)) is None
    assert bmi_of(D(70), None) is None
    assert bmi_of(D(70), D(0)) is None


# --- signals ----------------------------------------------------------------------------------

DAY0 = date(2026, 11, 1)


def days(*kcal: int, floor: int = 1500) -> list[IntakeDay]:
    return [IntakeDay(DAY0 + timedelta(days=i), k, floor) for i, k in enumerate(kcal)]


def signals(
    intake: list[IntakeDay] | None = None,
    trend: list[Decimal | None] | None = None,
    weigh_ins: int = 0,
    language: bool = False,
) -> list[Signal]:
    return ed_signals(intake or [], trend or [], weigh_ins, language)


def test_floor_breaches_on_three_of_the_last_seven_logged_days() -> None:
    assert signals(days(1499, 1499, 1500, 1500, 1500, 1500, 1500)) == []  # 2 breaches
    assert signals(days(1499, 1499, 1499, 1500, 1500, 1500, 1500)) == [Signal.INTAKE_BELOW_FLOOR]
    assert signals(days(1500, 1500, 1500)) == []  # at the floor is not under it
    assert signals(days(1499, 1499, 1499)) == [Signal.INTAKE_BELOW_FLOOR]  # fewer than 7 logged
    # only the latest 7 count: three old breaches fall out of the window
    assert signals(days(1000, 1000, 1000, 1500, 1500, 1500, 1500, 1500, 1500, 1500)) == []
    assert signals(days(1000, 1000, 1500, 1500, 1500, 1500, 1000, 1000)) == [
        Signal.INTAKE_BELOW_FLOOR
    ]
    assert signals(list(reversed(days(1499, 1499, 1499)))) == [Signal.INTAKE_BELOW_FLOOR]


def test_each_day_is_judged_against_its_own_floor() -> None:
    mixed = [IntakeDay(DAY0 + timedelta(days=i), 1300, 1200) for i in range(3)]
    assert signals(mixed) == []
    mixed[0] = IntakeDay(DAY0, 1300, 1500)
    assert signals(mixed) == []  # one breach only


@pytest.mark.parametrize(
    ("trend", "fires"),
    [
        ([D("-1.01"), D("-1.01")], True),
        ([D("-1.0"), D("-1.0")], False),  # exactly 1 percent is not above it
        ([D("-1.01"), D("-0.99")], False),
        ([D("-0.99"), D("-1.01")], False),  # only one week in the run ending now
        ([D("-2"), D("-1.5"), D("-3")], True),
        ([D("-2"), D("-2"), D("-0.5")], False),  # the run must end now
        ([D("-2"), None, D("-2")], False),  # a week with no estimate breaks the run
        ([D("-2"), D("-2"), None], False),
        ([D("1.5"), D("1.5")], False),  # gaining is not this signal
        ([D("-1.5")], False),
        ([], False),
    ],
)
def test_rapid_loss(trend: list[Decimal | None], fires: bool) -> None:
    assert (signals(trend=trend) == [Signal.RAPID_LOSS]) is fires


@pytest.mark.parametrize(("count", "fires"), [(0, False), (3, False), (4, True), (9, True)])
def test_many_weigh_ins(count: int, fires: bool) -> None:
    assert (signals(weigh_ins=count) == [Signal.MANY_WEIGH_INS]) is fires


def test_language_and_order_of_signals() -> None:
    assert signals(language=True) == [Signal.COMPENSATING_LANGUAGE]
    everything = signals(days(1000, 1000, 1000), [D(-2), D(-2)], weigh_ins=4, language=True)
    assert everything == [
        Signal.INTAKE_BELOW_FLOOR,
        Signal.RAPID_LOSS,
        Signal.MANY_WEIGH_INS,
        Signal.COMPENSATING_LANGUAGE,
    ]


def test_weekly_trend_history_from_weights() -> None:
    today = date(2026, 11, 28)

    def week(index: int, *kg: str) -> list[tuple[date, Decimal]]:
        return [(today - timedelta(days=7 * index + i), D(v)) for i, v in enumerate(kg)]

    weights = week(0, "98", "98") + week(1, "100", "100") + week(2, "102", "102")
    got = weekly_trend_history(weights, today, weeks=2)
    assert got == [D("-1.96"), D("-2.00")]  # oldest first
    # a week with a single weigh-in is noise, so it has no estimate
    thin = week(0, "98") + week(1, "100", "100")
    assert weekly_trend_history(thin, today, weeks=1) == [None]


# --- fitting the rate to the floor ------------------------------------------------------------


def test_calories_and_floor_fit() -> None:
    # 80 kg at 0.5 %/week is 0.4 kg a week: 440 kcal a day below 2400
    assert calories_for_rate(D(2400), D(80), D("0.5")) == 1960
    assert rate_for_floor(D(2400), D(80), D("0.5"), 1500) == (D("0.5"), 1960, False)
    rate, calories, slowed = rate_for_floor(D(1800), D(80), D("0.5"), 1500)
    assert slowed
    assert rate < D("0.5")
    assert calories >= 1500
    assert rate_for_floor(D(1400), D(80), D("0.5"), 1500) == (D("0.00"), 1500, True)
    # landing exactly on the floor is not slowed
    assert rate_for_floor(D(1960) + D(440), D(80), D("0.5"), 1960) == (D("0.5"), 1960, False)


def test_banned_phrase_scanner() -> None:
    assert banned_phrases_in("Cheat meal? That is junk, and a good food idea") == [
        "good food",
        "junk",
        "cheat meal",
    ]
    assert banned_phrases_in("Learn to earn your treat") == ["earn"]
    assert banned_phrases_in("Your earnings and a learner's permit") == []
    assert banned_phrases_in("Clean-eating") == []  # only the spaced form is listed
    assert len(set(BANNED_PHRASES)) == len(BANNED_PHRASES)
