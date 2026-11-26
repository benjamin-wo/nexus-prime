"""Health's safety layer: floors, rate caps, gates, eating-disorder signals and red flags.

Pure and table-driven, with no I/O and no model. Everything here holds whatever the model says:
the application layer (``application/health_safety.py``) is the only way target-setting code
reaches these rules. Wellness only (ADR 0001, ADR 0004): nothing here diagnoses anything.

Rules and thresholds come from the research report "Nexus Health wearables nutrition agent",
"Product rules" and section C. The eating-disorder thresholds are design proposals; the report
says no validated in-app thresholds exist. Reasons are codes (``ReasonCode``), never prose.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import StrEnum
from itertools import pairwise

from nexus.domain.health import Goal, Sex
from nexus.domain.health_texts import (
    ED_SIGNPOSTS,
    ED_SIGNPOSTS_UNDER_18,
    SIGNPOST_EMERGENCY,
    SIGNPOST_SOS,
    TEXT_EATING_DISORDER,
    TEXT_EMERGENCY,
    TEXT_JOINT,
    TEXT_MEDICATION,
    TEXT_NUMBNESS,
    TEXT_PAIN,
    TEXT_PREGNANCY,
    TEXT_SUICIDE,
    Signpost,
)

D = Decimal


class ReasonCode(StrEnum):
    """Why a rule changed or refused something. Channels map these to words."""

    OK = "ok"
    # gates
    UNDER_18 = "under_18"
    LOW_BMI = "low_bmi"
    ED_HISTORY = "ed_history"
    ED_OVERRIDDEN = "ed_overridden"
    AGE_UNKNOWN = "age_unknown"
    BMI_UNKNOWN = "bmi_unknown"
    # rate
    RATE_DEFAULTED = "rate_defaulted"
    RATE_RAISED_TO_MINIMUM = "rate_raised_to_minimum"
    RATE_HARD_CAP = "rate_hard_cap"
    RATE_LEAN_LIMIT = "rate_lean_limit"
    RATE_NOT_APPLICABLE = "rate_not_applicable"
    RATE_SLOWED_FOR_FLOOR = "rate_slowed_for_floor"
    # calories and protein
    FLOOR_APPLIED = "floor_applied"
    PROTEIN_RAISED = "protein_raised"
    PROTEIN_LOWERED = "protein_lowered"
    # calorie-target features switched off
    SUSPENDED_ED_SIGNAL = "suspended_ed_signal"
    SUSPENDED_NUMBERS_FREE = "suspended_numbers_free"
    SUSPENDED_ED_HISTORY = "suspended_ed_history"


# --- calorie floor ---------------------------------------------------------------------------

FLOOR_FEMALE_KCAL = 1200
FLOOR_MALE_KCAL = 1500
FLOOR_UNSPECIFIED_KCAL = 1500  # the higher one when we don't know


def calorie_floor(sex: Sex, bmr_kcal: Decimal | None) -> int:
    """The least a daily target may be: max(1200 female, 1500 male or unspecified, the resting
    rate when known). A resting rate with a fraction rounds up."""
    base = FLOOR_FEMALE_KCAL if sex is Sex.FEMALE else FLOOR_MALE_KCAL
    if bmr_kcal is None:
        return base
    return max(base, int(bmr_kcal.to_integral_value(rounding=ROUND_CEILING)))


# --- rate ------------------------------------------------------------------------------------

RATE_PRESETS = (D("0.25"), D("0.5"), D("0.75"))  # percent of body weight per week
RATE_DEFAULT = D("0.5")
RATE_HARD_CAP = D("1.0")
# Lean users get 0.5 %/week at most. BMI below 22 is a conservative proxy for "lean": we have no
# body-fat figure, and a rate that suits a heavier person takes proportionally more from a
# smaller frame. It is a convention, not a clinical cut-off.
LEAN_BMI = D(22)
LEAN_MAX_RATE = D("0.5")
KCAL_PER_KG = D(7700)  # the usual energy figure for a kilogram of body weight change


@dataclass(frozen=True, slots=True)
class RateDecision:
    """The weekly loss rate allowed (percent of body weight) and why. ``rate`` is None when no
    loss rate applies."""

    rate: Decimal | None
    reason: ReasonCode


def clamp_rate(
    goal: Goal, requested: Decimal | None, bmi: Decimal | None, age: int | None
) -> RateDecision:
    """The weekly loss rate allowed for this request.

    Only a loss goal has a rate here. Under 18 or BMI below 18.5 there is none (the gates say
    so too). Above the hard cap it is cut to the cap, and for a lean user (BMI below
    ``LEAN_BMI``) to ``LEAN_MAX_RATE``. A missing rate becomes the default (or the lean limit);
    a rate of zero or less is raised to the smallest preset."""
    if goal is not Goal.LOSE:
        return RateDecision(requested, ReasonCode.RATE_NOT_APPLICABLE)
    if age is not None and age < ADULT_AGE:
        return RateDecision(None, ReasonCode.UNDER_18)
    if bmi is not None and bmi < MIN_BMI_FOR_LOSS:
        return RateDecision(None, ReasonCode.LOW_BMI)
    lean = bmi is not None and bmi < LEAN_BMI
    limit = LEAN_MAX_RATE if lean else RATE_HARD_CAP
    if requested is None:
        return RateDecision(RATE_DEFAULT, ReasonCode.RATE_DEFAULTED)
    if requested <= 0:
        return RateDecision(RATE_PRESETS[0], ReasonCode.RATE_RAISED_TO_MINIMUM)
    if requested > limit:
        return RateDecision(limit, ReasonCode.RATE_LEAN_LIMIT if lean else ReasonCode.RATE_HARD_CAP)
    return RateDecision(requested, ReasonCode.OK)


def calories_for_rate(tdee_kcal: Decimal, weight_kg: Decimal, rate_pct: Decimal) -> int:
    """Daily calories that lose ``rate_pct`` of body weight a week from an expenditure estimate."""
    weekly_kg = weight_kg * rate_pct / 100
    return int((tdee_kcal - weekly_kg * KCAL_PER_KG / 7).to_integral_value(rounding=ROUND_HALF_UP))


def rate_for_floor(
    tdee_kcal: Decimal, weight_kg: Decimal, rate_pct: Decimal, floor_kcal: int
) -> tuple[Decimal, int, bool]:
    """Fit a loss rate to the floor: (rate, daily calories, slowed). If the deficit would put
    calories under the floor, the rate is slowed until they sit on it (never below zero)."""
    calories = calories_for_rate(tdee_kcal, weight_kg, rate_pct)
    if calories >= floor_kcal:
        return rate_pct, calories, False
    room = max(tdee_kcal - floor_kcal, D(0))
    slowed = (room * 7 / KCAL_PER_KG / weight_kg * 100).quantize(D("0.01"), rounding=ROUND_DOWN)
    return slowed, max(calories_for_rate(tdee_kcal, weight_kg, slowed), floor_kcal), True


# --- protein ---------------------------------------------------------------------------------

PROTEIN_DEFAULT = D("1.6")  # g per kg of body weight
PROTEIN_MIN = D("1.4")
PROTEIN_MAX = D("2.2")
PROTEIN_DEFICIT_FLOOR = D("1.2")  # never lower than this in a deficit, whatever else changes


def protein_per_kg(choice: Decimal = PROTEIN_DEFAULT, *, in_deficit: bool = False) -> Decimal:
    """The g/kg used: the choice held to the selectable range 1.4-2.2 (and, in a deficit, never
    under 1.2, which the range already guarantees)."""
    per_kg = min(max(choice, PROTEIN_MIN), PROTEIN_MAX)
    return max(per_kg, PROTEIN_DEFICIT_FLOOR) if in_deficit else per_kg


def protein_target_g(
    weight_kg: Decimal, choice: Decimal = PROTEIN_DEFAULT, *, in_deficit: bool = False
) -> int:
    """Daily protein in whole grams for a body weight."""
    grams = weight_kg * protein_per_kg(choice, in_deficit=in_deficit)
    return int(grams.to_integral_value(rounding=ROUND_HALF_UP))


# --- gates -----------------------------------------------------------------------------------

ADULT_AGE = 18
MIN_BMI_FOR_LOSS = D("18.5")


@dataclass(frozen=True, slots=True)
class Gate:
    allowed: bool
    reason: ReasonCode


def weight_loss_allowed(
    age: int | None,
    bmi: Decimal | None,
    ed_history: bool,
    *,
    ed_override_confirmed: bool = False,
) -> Gate:
    """May this person have a weight-loss or deficit goal?

    No under 18 and none at BMI below 18.5, and no override for either. An unknown age or BMI
    also blocks: we won't guess our way into a loss goal. An eating-disorder history blocks
    unless the user explicitly confirms an override."""
    if age is None:
        return Gate(False, ReasonCode.AGE_UNKNOWN)
    if age < ADULT_AGE:
        return Gate(False, ReasonCode.UNDER_18)
    if bmi is None:
        return Gate(False, ReasonCode.BMI_UNKNOWN)
    if bmi < MIN_BMI_FOR_LOSS:
        return Gate(False, ReasonCode.LOW_BMI)
    if ed_history:
        if ed_override_confirmed:
            return Gate(True, ReasonCode.ED_OVERRIDDEN)
        return Gate(False, ReasonCode.ED_HISTORY)
    return Gate(True, ReasonCode.OK)


def bmi_of(weight_kg: Decimal | None, height_cm: Decimal | None) -> Decimal | None:
    if weight_kg is None or height_cm is None or height_cm <= 0 or weight_kg <= 0:
        return None
    metres = height_cm / 100
    return (weight_kg / (metres * metres)).quantize(D("0.1"), rounding=ROUND_HALF_UP)


def safe_age(birth_year: int | None, this_year: int) -> int | None:
    """The youngest the person could be this year. Only a birth year is stored, so someone
    born in 2008 is treated as 17 throughout 2026 and counts as 18 only from 2027."""
    return None if birth_year is None else this_year - birth_year - 1


# --- eating-disorder signals -----------------------------------------------------------------


class Signal(StrEnum):
    INTAKE_BELOW_FLOOR = "intake_below_floor"
    RAPID_LOSS = "rapid_loss"
    MANY_WEIGH_INS = "many_weigh_ins"
    COMPENSATING_LANGUAGE = "compensating_language"


# Thresholds from the report's section C (Eating-disorder safeguards must be code, not prompt)
# and Product rules. The report is explicit that these are design proposals: no validated
# in-app thresholds exist. They are meant to trigger a soft check-in, never a diagnosis.
SIGNAL_WINDOW_DAYS = 7  # "the last 7 logged days"
SIGNAL_FLOOR_BREACH_DAYS = 3  # floor breaches on 3 or more of them
SIGNAL_LOSS_PCT_PER_WEEK = D(1)  # loss strictly above 1 % of body weight a week
SIGNAL_LOSS_WEEKS = 2  # for 2 or more consecutive weeks
SIGNAL_MAX_WEIGH_INS_PER_DAY = 3  # more than 3 in a day


@dataclass(frozen=True, slots=True)
class IntakeDay:
    """One logged day of intake against the floor that applied to it."""

    day: date
    kcal: int
    floor_kcal: int


def ed_signals(
    intake_days: Sequence[IntakeDay],
    weight_trend_pct_per_week_history: Sequence[Decimal | None],
    weigh_ins_today: int,
    flagged_language: bool,
) -> list[Signal]:
    """The signals active now, in a fixed order.

    ``intake_days``: logged days (any order); the latest 7 count, and a day breaches the floor
    when kcal is below it (at the floor is fine). ``weight_trend_pct_per_week_history``: percent
    change in body weight per week, oldest first and signed (loss is negative); None is a week
    with no estimate, which breaks a run. Only the run of weeks ending now counts: loss above 1
    percent a week for 2 or more consecutive weeks. ``weigh_ins_today``: more than 3 fires."""
    signals: list[Signal] = []
    latest = sorted(intake_days, key=lambda d: d.day)[-SIGNAL_WINDOW_DAYS:]
    if sum(1 for d in latest if d.kcal < d.floor_kcal) >= SIGNAL_FLOOR_BREACH_DAYS:
        signals.append(Signal.INTAKE_BELOW_FLOOR)
    run = 0
    for week in reversed(weight_trend_pct_per_week_history):
        if week is None or -week <= SIGNAL_LOSS_PCT_PER_WEEK:
            break
        run += 1
    if run >= SIGNAL_LOSS_WEEKS:
        signals.append(Signal.RAPID_LOSS)
    if weigh_ins_today > SIGNAL_MAX_WEIGH_INS_PER_DAY:
        signals.append(Signal.MANY_WEIGH_INS)
    if flagged_language:
        signals.append(Signal.COMPENSATING_LANGUAGE)
    return signals


def weekly_trend_history(
    weights: Sequence[tuple[date, Decimal]], today: date, *, weeks: int = 4, min_per_week: int = 2
) -> list[Decimal | None]:
    """A plain stand-in for the energy module's trend: percent change between the mean weights
    of consecutive 7-day buckets ending today, oldest first. A bucket needs ``min_per_week``
    weights to count (fewer reads as noise), else its change is None."""
    buckets: list[list[Decimal]] = [[] for _ in range(weeks + 1)]
    for day, kg in weights:
        index = (today - day).days // 7
        if 0 <= index <= weeks:
            buckets[index].append(kg)
    means: list[Decimal | None] = [
        sum(b, D(0)) / len(b) if len(b) >= min_per_week else None for b in buckets
    ]
    history: list[Decimal | None] = []
    for newer, older in pairwise(means):
        if newer is None or older is None:
            history.append(None)
        else:
            history.append(((newer - older) / older * 100).quantize(D("0.01")))
    return history[::-1]


# --- red flags -------------------------------------------------------------------------------


class RedFlagKind(StrEnum):
    SUICIDAL = "suicidal"
    CHEST = "chest"
    BREATHING = "breathing"
    FAINTING = "fainting"
    SHARP_PAIN = "sharp_pain"
    NUMBNESS = "numbness"
    JOINT_POP = "joint_pop"
    PREGNANCY = "pregnancy"
    MEDICATION = "medication"
    EATING_DISORDER = "eating_disorder"


class Severity(StrEnum):
    EMERGENCY = "emergency"  # call 995 now
    SEE_PROFESSIONAL = "see_professional"  # stop and see someone qualified


@dataclass(frozen=True, slots=True)
class RedFlag:
    kind: RedFlagKind
    severity: Severity
    text: str  # the fixed referral, shown as it is
    signposts: tuple[Signpost, ...]


_TEXTS: dict[RedFlagKind, tuple[Severity, str, tuple[Signpost, ...]]] = {
    RedFlagKind.SUICIDAL: (Severity.EMERGENCY, TEXT_SUICIDE, (SIGNPOST_EMERGENCY, SIGNPOST_SOS)),
    RedFlagKind.CHEST: (Severity.EMERGENCY, TEXT_EMERGENCY, (SIGNPOST_EMERGENCY,)),
    RedFlagKind.BREATHING: (Severity.EMERGENCY, TEXT_EMERGENCY, (SIGNPOST_EMERGENCY,)),
    RedFlagKind.FAINTING: (Severity.EMERGENCY, TEXT_EMERGENCY, (SIGNPOST_EMERGENCY,)),
    RedFlagKind.SHARP_PAIN: (Severity.SEE_PROFESSIONAL, TEXT_PAIN, ()),
    RedFlagKind.NUMBNESS: (Severity.SEE_PROFESSIONAL, TEXT_NUMBNESS, ()),
    RedFlagKind.JOINT_POP: (Severity.SEE_PROFESSIONAL, TEXT_JOINT, ()),
    RedFlagKind.PREGNANCY: (Severity.SEE_PROFESSIONAL, TEXT_PREGNANCY, ()),
    RedFlagKind.MEDICATION: (Severity.SEE_PROFESSIONAL, TEXT_MEDICATION, ()),
    RedFlagKind.EATING_DISORDER: (
        Severity.SEE_PROFESSIONAL,
        TEXT_EATING_DISORDER,
        ED_SIGNPOSTS_UNDER_18,
    ),
}


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in patterns)


@dataclass(frozen=True, slots=True)
class _Rule:
    kind: RedFlagKind
    any_of: tuple[re.Pattern[str], ...]
    unless: re.Pattern[str] | None = None  # a benign context that cancels the match
    also: re.Pattern[str] | None = None  # a second cue that must be present too


_BODY = (
    r"(?:hand|hands|arm|arms|leg|legs|foot|feet|finger|fingers|toe|toes|face|lip|lips|"
    r"cheek|jaw|thigh|thighs|tongue|side)"
)
_JOINT = (
    r"(?:knee|knees|shoulder|hip|ankle|elbow|wrist|joint|hamstring|back|achilles|neck|"
    r"groin|rib|ribs)"
)
_MEDS = (
    r"\b(?:medications?|meds|medicines?|prescriptions?|prescribed|antidepressants?|"
    r"blood thinners?|warfarin|metformin|insulin|statins?|inhalers?|steroids?|antibiotics?|"
    r"painkillers?|ibuprofen|paracetamol|beta[- ]?blockers?|supplements?|vitamins?|creatine|"
    r"pre-?workout|fat burners?|diet pills?|herbal|tcm)\b"
)
_MED_QUESTION = (
    r"\b(?:interact\w*|safe (?:to|with|for)|(?:ok|okay) to (?:take|mix|combine|have)|mix(?:ing)?|"
    r"combin(?:e|ing)|while (?:on|taking)|stop taking|should i (?:stop|skip|increase|reduce|"
    r"lower|change|double)|dose|dosage|side effects?)\b"
)
_MEAL = r"(?:what i (?:ate|had)|eating|my (?:meal|dinner|lunch|breakfast|binge)|food)"

# Order is priority: emergencies first, then the rest. The text is lowercased and its
# apostrophes straightened before matching; patterns use ``can'?t`` so "cant" matches too.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        RedFlagKind.SUICIDAL,
        _rx(
            r"\bsuicid(?:e|al)\b",
            r"\bkill(?:ing)? myself\b",
            r"\bend(?:ing)? (?:my (?:own )?life|it all)\b",
            r"\bwant(?:ed)? to die\b",
            r"\bdon'?t want to (?:live|be alive|be here anymore|exist)\b",
            r"\bno reason to (?:live|go on)\b",
            r"\bbetter off (?:dead|without me)\b",
            r"\b(?:hurt|harm)(?:ing)? myself\b",
            r"\bself[- ]?harm\w*\b",
        ),
    ),
    _Rule(
        RedFlagKind.CHEST,
        _rx(
            r"\bchest (?:pains?|tightness|pressure|discomfort)\b",
            r"\b(?:pains?|tightness|pressure|discomfort) (?:in|on|across|around) "
            r"(?:my |the )?chest\b",
            r"\bchest (?:is |feels? |has been |got |gets |very |so |damn |really |suddenly )*"
            r"(?:tight|heavy|squeez\w+|crushing)\b",
            r"\b(?:tight|heavy) (?:in|on) (?:my |the )?chest\b",
            r"\bmy chest (?:hurts?|aches?)\b",
            r"\bheart attack\b",
        ),
    ),
    _Rule(
        RedFlagKind.BREATHING,
        _rx(
            r"\b(?:can'?t|cannot|can not|couldn'?t|unable to) "
            r"(?:catch my |get my )?breath(?:e|ing)?\b",
            r"\b(?:hard|difficult|struggling|struggle|trouble|difficulty|problems?) "
            r"(?:to |with )?breathing?\b",
            r"\b(?:shortness of breath|short of breath|breathless)\b",
        ),
        # a blocked nose is not this; and breathlessness only counts at rest (below)
        unless=re.compile(r"\b(?:nose|nostrils?|stuffy|blocked|sinus)\b"),
    ),
    _Rule(
        RedFlagKind.FAINTING,
        _rx(
            r"\bfaint(?:ed|ing)\b",
            r"\b(?:feel|feels|feeling|felt|about to|going to|nearly|almost) faint\b",
            r"\b(?:passed|pass|passing) out\b",
            r"\bblack(?:ed|ing)? out\b",
            r"\blost consciousness\b",
            r"\bcollapsed\b",
        ),
    ),
    _Rule(
        RedFlagKind.SHARP_PAIN,
        _rx(
            r"\b(?:sharp|stabbing|shooting|severe|excruciating) (?:pains?|ache)\b",
            r"\bsharp \w+ pain\b",
            r"\b(?:pain|ache|hurt|hurts) (?:is |has been |keeps? |getting |gotten )*"
            r"(?:worse|worsening)\b",
            r"\bworsening (?:pain|ache)\b",
            r"\bpain (?:that )?(?:won'?t|doesn'?t|does not|will not|not) "
            r"(?:go away|goes away|stop|ease|improve)\b",
        ),
    ),
    _Rule(
        RedFlagKind.NUMBNESS,
        _rx(
            r"\b(?:numbness|tingling|pins and needles)\b",
            rf"\b(?:my |the )?{_BODY}\b.{{0,25}}\bnumb\b",
            rf"\bnumb(?:ness)? (?:in|on|down) (?:my |the |one )?{_BODY}\b",
            r"\bgoing numb\b",
            r"\b(?:went|gone) numb\b",
        ),
        # numb from the cold AC, or a tingling mouth from mala: common and not a flag
        unless=re.compile(
            r"\b(?:cold|freezing|ac|aircon|air[- ]?con|air conditioning|ice|icy|winter|"
            r"mala|spicy|sichuan|peppercorns?|dentist|anaesthe\w+|anesthe\w+)\b"
        ),
    ),
    _Rule(
        RedFlagKind.JOINT_POP,
        _rx(
            rf"\b{_JOINT}\b.{{0,30}}\b(?:pop|pops|popped|popping|snap|snaps|snapped|snapping|"
            rf"dislocated)\b",
            rf"\b(?:pop|pops|popped|popping|snap|snaps|snapped|snapping|dislocated)\b"
            rf".{{0,30}}\b{_JOINT}\b",
            r"\bpop(?:ped)? out of (?:place|socket|joint)\b",
            r"\bdislocat\w+\b",
        ),
        # "popped back to the gym" or "popped into the shops": an errand, not a joint
        unless=re.compile(
            r"\b(?:pops|popped|popping) (?:back|into|over|by|to|out to|in (?:at|for|to))\b"
        ),
    ),
    # Clicking alone, with no pain, is common and harmless: it needs a pain cue in the message,
    # and a pain that is denied ("but doesn't hurt") cancels it.
    _Rule(
        RedFlagKind.JOINT_POP,
        _rx(
            rf"\b{_JOINT}\b.{{0,30}}\b(?:click|clicks|clicked|clicking)\b",
            rf"\b(?:click|clicks|clicked|clicking)\b.{{0,30}}\b{_JOINT}\b",
        ),
        unless=re.compile(
            r"\b(?:don'?t|doesn'?t|do not|does not|not|no|without|never|isn'?t|aren'?t)\b"
            r"(?: \w+){0,2} (?:hurt\w*|pain\w*|ache\w*|sore\w*)\b|\bpainless\w*\b|\bpain-free\b"
        ),
        also=re.compile(
            r"\b(?:hurt|hurts|hurting|pain|painful|aches?|aching|sore|swollen|swelling)\b"
        ),
    ),
    _Rule(
        RedFlagKind.PREGNANCY,
        _rx(
            r"\bpregnan(?:t|cy)\b",
            r"\bpost-?partum\b",
            r"\bpost-?natal\b",
            r"\bbreast-?\s?feeding\b",
            r"\blactating\b",
            r"\btrying to conceive\b",
            r"\bexpecting (?:a baby|my (?:first|second|third|baby))\b",
            r"\b(?:gave|giving|given) birth\b",
            r"\bafter (?:the |my )?(?:birth|delivery|c-?section)\b",
            r"\bin confinement\b",
        ),
    ),
    _Rule(
        RedFlagKind.MEDICATION,
        _rx(
            _MED_QUESTION,
            r"\bwith (?:my|any|other|the) (?:[\w-]+ ){0,3}(?:medications?|meds|medicines?|pills|"
            r"prescriptions?|antidepressants?|blood thinners?|statins?|insulin|inhalers?)\b",
        ),
        also=re.compile(_MEDS),
    ),
    _Rule(
        RedFlagKind.EATING_DISORDER,
        _rx(
            r"\beating disorders?\b",
            r"\b(?:anorexi[ac]\w*|bulimi[ac]\w*|orthorexi\w*)\b",
            r"\bpurging\b",
            r"\bpurge[ds]? (?:after|up|what|my (?:food|meals?|dinner|lunch|breakfast)|the food)\b",
            r"\b(?:make|made|making|makes) myself (?:throw up|vomit|puke|sick)\b",
            r"\b(?:throw(?:ing)? up|vomit(?:ing)?|puk(?:e|ing)) (?:after (?:eating|meals?|dinner|"
            r"lunch|breakfast)|on purpose|what i (?:ate|had)|my food)\b",
            r"\b(?:laxatives?|diuretics?|diet pills?)\b.{0,50}\b(?:lose|losing|weight|skinny|thin|"
            r"after (?:eating|meals?)|binge|ate too much|cancel|make up for)\b",
            r"\bstarv(?:e|ing) myself\b",
            r"\bbinge[- ]?(?:eat\w*|purg\w*)\b",
            r"\bbinged? (?:and|then) (?:purge|puke|vomit|throw|fast|starv|restrict)\w*\b",
            r"\brestrict(?:ing)? (?:my )?(?:food|eating|calories)\b",
            rf"\b(?:compensat\w+ for|cancel(?:ling)? out|undo(?:ing)?|burn(?:ing)? off|"
            rf"work(?:ing)? off|punish(?:ing)? myself for) {_MEAL}\b",
        ),
    ),
)

_QUOTES = re.compile("[\u2019`\u00b4]")


def _normal(text: str) -> str:
    return " ".join(_QUOTES.sub("'", text.lower()).split())


# Breathlessness alone is common after effort; it only counts with a cue that it is at rest.
_AT_REST = re.compile(
    r"\b(?:at rest|resting|sitting|lying|sleeping|doing nothing|for no reason|out of nowhere|"
    r"suddenly|all of a sudden|walking slowly|while watching|in bed)\b"
)
_BREATHLESS = re.compile(r"\b(?:shortness of breath|short of breath|breathless)\b")


def _hit(rule: _Rule, text: str) -> bool:
    for pattern in rule.any_of:
        if not pattern.search(text):
            continue
        if rule.kind is RedFlagKind.BREATHING and _BREATHLESS.fullmatch(
            pattern.search(text).group(0)  # type: ignore[union-attr]
        ):
            if not _AT_REST.search(text):
                continue
        if rule.also is not None and not rule.also.search(text):
            continue
        if rule.unless is not None and rule.unless.search(text):
            continue
        return True
    return False


def red_flags(text: str) -> RedFlag | None:
    """The most urgent red flag in a message, or None.

    Deterministic: the text is lowercased and matched against word-boundary patterns, with
    Singapore English and common variants ("cannot breathe", "chest very tight", "cant").
    Emergencies come before see-a-professional flags. Judgement calls, all tested:

    - ``chest day``, ``pain au chocolat`` and ``I'm dying to try that place`` never match.
    - Numbness from the cold or the aircon, or a tingling mouth from mala, is not flagged.
    - Short of breath is flagged only with a cue that it is at rest; "can't breathe" always is,
      unless a blocked nose is mentioned.
    - Idioms such as "I could kill myself for eating that" are flagged: when the cost of a
      false negative is this high we accept the false positive.
    - A medication question needs both a medication or supplement term and a question cue."""
    normal = _normal(text)
    for rule in _RULES:
        if _hit(rule, normal):
            severity, referral, signposts = _TEXTS[rule.kind]
            return RedFlag(rule.kind, severity, referral, signposts)
    return None


def has_compensating_language(text: str) -> bool:
    """Whether the message discloses purging, laxative use or compensating for eating. This is
    the ``flagged_language`` input of ``ed_signals``."""
    flag = red_flags(text)
    if flag is not None and flag.kind is RedFlagKind.EATING_DISORDER:
        return True
    ed_rule = next(r for r in _RULES if r.kind is RedFlagKind.EATING_DISORDER)
    return _hit(ed_rule, _normal(text))


def signposts_for(*, under_18: bool) -> tuple[Signpost, ...]:
    return ED_SIGNPOSTS_UNDER_18 if under_18 else ED_SIGNPOSTS


# --- wording guard ---------------------------------------------------------------------------

# Words Health copy must not use (report, Product rules: Wording). Matched case-insensitively
# on word boundaries; ``tests/unit/test_health_wording.py`` scans the health copy for them.
BANNED_PHRASES: tuple[str, ...] = (
    "good food",
    "bad food",
    "clean eating",
    "junk",
    "cheat meal",
    "earn",
    "burn off",
    "ideal weight",
    "guilt-free",
    "metabolic damage",
    "obesity",
    "diabetes",
    "pcos",
)
_BANNED = tuple(
    (
        phrase,
        re.compile(
            r"\b" + re.escape(phrase) + (r"(?:s|ed|ing)?" if phrase == "earn" else "") + r"\b", re.I
        ),
    )
    for phrase in BANNED_PHRASES
)


def banned_phrases_in(text: str) -> list[str]:
    """The banned phrases found in ``text``."""
    return [phrase for phrase, pattern in _BANNED if pattern.search(text)]
