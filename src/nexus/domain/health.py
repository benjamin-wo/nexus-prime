"""Health foundation: body and activity samples, the wellness profile, and consent scopes.

Pure rules, no I/O. A sample is one measurement from any source (typed in, said in chat, or
synced from a phone or a brand's service). Its value is stored as entered, with its unit; weight
is converted in code with the same kg/lb rule Gym uses. Nothing here interprets a figure
medically: bounds only catch typos and broken devices.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

from nexus.domain.errors import ConsentRequired, InvalidInput
from nexus.domain.gym_training import WeightUnit, to_kg
from nexus.domain.ledger import UserId

# To be checked against HSA's clarification statement wording before store submission.
WELLNESS_STATEMENT = (
    "This product is not intended to diagnose, treat, mitigate, cure or prevent any disease or "
    "medical condition. It is intended for general wellness and lifestyle purposes only. If you "
    "have any medical concerns, please consult a qualified healthcare professional."
)

MILLI = Decimal("0.001")
MAX_SOURCE_NAME = 60
MAX_EXTERNAL_ID = 200
MAX_SAMPLE_SPAN_DAYS = 31  # a sleep or workout sample is a night or a session, not a month


class SampleKind(StrEnum):
    WEIGHT = "weight"
    BODY_FAT = "body_fat"
    STEPS = "steps"
    ACTIVE_ENERGY = "active_energy"
    RESTING_HEART_RATE = "resting_heart_rate"
    HRV = "hrv"
    SLEEP = "sleep"
    WORKOUT = "workout"


class SampleUnit(StrEnum):
    KG = "kg"
    LB = "lb"
    PERCENT = "percent"
    COUNT = "count"
    KCAL = "kcal"
    BPM = "bpm"
    MS = "ms"
    MIN = "min"


class SampleSource(StrEnum):
    MANUAL = "manual"  # typed into the app
    CHAT = "chat"  # said to Prime, in chat, voice or Telegram
    HEALTH_CONNECT = "health_connect"  # Android
    HEALTHKIT = "healthkit"  # iOS
    OAUTH = "oauth"  # a brand's service; ``source_name`` says which


class ConsentScope(StrEnum):
    AI_PROCESSING = "ai_processing"  # sending health data to the model provider
    SOURCE_HEALTH_CONNECT = "source:health_connect"
    SOURCE_HEALTHKIT = "source:healthkit"
    SOURCE_OAUTH = "source:oauth"
    MODEL_IMPROVEMENT = "model_improvement"


class Sex(StrEnum):
    """Used only to pick the constant in energy equations; never shown as a label, never sent
    anywhere else."""

    FEMALE = "female"
    MALE = "male"
    UNSPECIFIED = "unspecified"


class ActivityLevel(StrEnum):
    """The five activity multipliers of the Mifflin-St Jeor method."""

    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


class Goal(StrEnum):
    LOSE = "lose"
    MAINTAIN = "maintain"
    GAIN = "gain"
    PERFORMANCE = "performance"


class UnitSystem(StrEnum):
    METRIC = "metric"
    IMPERIAL = "imperial"


# Manual and chat entries are the user's own words and need only the master consent; the rest
# come from outside and each has its own scope.
MANUAL_SOURCES = frozenset({SampleSource.MANUAL, SampleSource.CHAT})
SOURCE_SCOPE: dict[SampleSource, ConsentScope] = {
    SampleSource.HEALTH_CONNECT: ConsentScope.SOURCE_HEALTH_CONNECT,
    SampleSource.HEALTHKIT: ConsentScope.SOURCE_HEALTHKIT,
    SampleSource.OAUTH: ConsentScope.SOURCE_OAUTH,
}

KIND_UNITS: dict[SampleKind, frozenset[SampleUnit]] = {
    SampleKind.WEIGHT: frozenset({SampleUnit.KG, SampleUnit.LB}),
    SampleKind.BODY_FAT: frozenset({SampleUnit.PERCENT}),
    SampleKind.STEPS: frozenset({SampleUnit.COUNT}),
    SampleKind.ACTIVE_ENERGY: frozenset({SampleUnit.KCAL}),
    SampleKind.RESTING_HEART_RATE: frozenset({SampleUnit.BPM}),
    SampleKind.HRV: frozenset({SampleUnit.MS}),
    SampleKind.SLEEP: frozenset({SampleUnit.MIN}),
    SampleKind.WORKOUT: frozenset({SampleUnit.MIN}),  # its duration
}
DEFAULT_UNIT: dict[SampleKind, SampleUnit] = {
    SampleKind.WEIGHT: SampleUnit.KG,
    SampleKind.BODY_FAT: SampleUnit.PERCENT,
    SampleKind.STEPS: SampleUnit.COUNT,
    SampleKind.ACTIVE_ENERGY: SampleUnit.KCAL,
    SampleKind.RESTING_HEART_RATE: SampleUnit.BPM,
    SampleKind.HRV: SampleUnit.MS,
    SampleKind.SLEEP: SampleUnit.MIN,
    SampleKind.WORKOUT: SampleUnit.MIN,
}
# Inclusive bounds in the kind's canonical unit (weight: kilograms).
BOUNDS: dict[SampleKind, tuple[Decimal, Decimal]] = {
    SampleKind.WEIGHT: (Decimal(20), Decimal(400)),
    SampleKind.BODY_FAT: (Decimal(2), Decimal(70)),
    SampleKind.STEPS: (Decimal(0), Decimal(200_000)),
    SampleKind.ACTIVE_ENERGY: (Decimal(0), Decimal(20_000)),
    SampleKind.RESTING_HEART_RATE: (Decimal(20), Decimal(250)),
    SampleKind.HRV: (Decimal(1), Decimal(500)),
    SampleKind.SLEEP: (Decimal(1), Decimal(1440)),
    SampleKind.WORKOUT: (Decimal(1), Decimal(1440)),
}
WHOLE_KINDS = frozenset({SampleKind.STEPS})  # counts, not measurements


def _clean(value: str | None, what: str, limit: int) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > limit:
        raise InvalidInput(f"{what} can be at most {limit} characters")
    return text


@dataclass(frozen=True, slots=True)
class Sample:
    """One measurement. ``end_at`` equals ``start_at`` for a point in time. Validated on
    construction, so ``dataclasses.replace`` re-checks an edit."""

    id: UUID
    user_id: UserId
    kind: SampleKind
    value: Decimal
    unit: SampleUnit
    start_at: datetime
    end_at: datetime
    source: SampleSource
    created_at: datetime
    source_name: str | None = None
    external_id: str | None = None

    def __post_init__(self) -> None:
        if self.unit not in KIND_UNITS[self.kind]:
            allowed = ", ".join(sorted(u.value for u in KIND_UNITS[self.kind]))
            raise InvalidInput(f"{self.kind.value} is measured in {allowed}, not {self.unit.value}")
        value = self.value
        if not isinstance(value, Decimal) or not value.is_finite():
            raise InvalidInput("that isn't a number")
        value = value.quantize(MILLI, rounding=ROUND_HALF_UP)
        if self.kind in WHOLE_KINDS and value != value.to_integral_value():
            raise InvalidInput(f"{self.kind.value} must be a whole number")
        low, high = BOUNDS[self.kind]
        in_range = low <= canonical(self.kind, value, self.unit) <= high
        if not in_range:
            what = self.kind.value.replace("_", " ")
            raise InvalidInput(
                f"a {what} between {low} and {high} {_bounds_unit(self.kind)} is expected"
            )
        object.__setattr__(self, "value", value)
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise InvalidInput("times need a time zone")
        if self.end_at < self.start_at:
            raise InvalidInput("a sample can't end before it starts")
        if (self.end_at - self.start_at).days > MAX_SAMPLE_SPAN_DAYS:
            raise InvalidInput(f"a sample can span at most {MAX_SAMPLE_SPAN_DAYS} days")
        name = _clean(self.source_name, "the source name", MAX_SOURCE_NAME)
        if (self.source is SampleSource.OAUTH) != (name is not None):
            raise InvalidInput("a source name goes with oauth samples, and only with them")
        object.__setattr__(self, "source_name", name)
        external = _clean(self.external_id, "the external id", MAX_EXTERNAL_ID)
        if external is not None and self.source in MANUAL_SOURCES:
            raise InvalidInput("typed and chat entries have no external id")
        object.__setattr__(self, "external_id", external)

    @property
    def is_manual(self) -> bool:
        return self.source in MANUAL_SOURCES

    @property
    def weight_kg(self) -> Decimal | None:
        """A weight in kilograms (exact, not rounded); None for other kinds."""
        if self.kind is not SampleKind.WEIGHT:
            return None
        return canonical(self.kind, self.value, self.unit)


def _bounds_unit(kind: SampleKind) -> str:
    return SampleUnit.KG.value if kind is SampleKind.WEIGHT else DEFAULT_UNIT[kind].value


def canonical(kind: SampleKind, value: Decimal, unit: SampleUnit) -> Decimal:
    """The value in the kind's canonical unit. Only weight has two; the kg/lb rule is Gym's."""
    if kind is SampleKind.WEIGHT:
        return to_kg(value, WeightUnit(unit.value))
    return value


def clean_unit(kind: SampleKind, unit: SampleUnit | None) -> SampleUnit:
    """The unit given, or the kind's usual one when none was."""
    return unit if unit is not None else DEFAULT_UNIT[kind]


def edited(sample: Sample, **changes: object) -> Sample:
    """``sample`` with ``changes`` applied and validated again. A point sample moved to a new
    start moves its end with it unless the end is changed too."""
    if "start_at" in changes and "end_at" not in changes and sample.end_at == sample.start_at:
        changes = {**changes, "end_at": changes["start_at"]}
    return replace(sample, **changes)  # type: ignore[arg-type]


# --- consent --------------------------------------------------------------------------------


def scope_for(source: SampleSource) -> ConsentScope | None:
    """The extra consent a source needs; None for typed and chat entries."""
    return SOURCE_SCOPE.get(source)


def check_consent(
    master_at: datetime | None, active: frozenset[ConsentScope], scope: ConsentScope | None
) -> None:
    """Raise ``ConsentRequired`` unless the master consent is given and, if ``scope`` is
    named, so is that scope."""
    if master_at is None:
        raise ConsentRequired("agree to Nexus keeping your health data first")
    if scope is not None and scope not in active:
        raise ConsentRequired(f"agree to {scope.value} first")


# --- the profile ----------------------------------------------------------------------------

MIN_BIRTH_YEAR = 1900
MIN_HEIGHT_CM = Decimal(50)
MAX_HEIGHT_CM = Decimal(260)
MAX_TARGET_RATE = Decimal(3)  # percent of body weight per week; a store bound, not a safe one
_RATE_STEP = Decimal("0.01")
_HEIGHT_STEP = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class HealthProfile:
    """What the energy and goal figures are worked from. A plain store: whether a goal is
    safe is decided elsewhere, not here."""

    user_id: UserId
    sex_for_equations: Sex  # used only for energy equations
    birth_year: int | None
    height_cm: Decimal | None
    activity_level: ActivityLevel | None
    goal: Goal
    target_rate_pct_per_week: Decimal | None
    numbers_free: bool
    ed_history: bool
    unit_system: UnitSystem
    updated_at: datetime

    def check(self, *, this_year: int) -> "HealthProfile":
        """This profile with its figures rounded, or ``InvalidInput``."""
        year = self.birth_year
        if year is not None and (isinstance(year, bool) or not MIN_BIRTH_YEAR <= year <= this_year):
            raise InvalidInput(f"a birth year is between {MIN_BIRTH_YEAR} and {this_year}")
        height = self.height_cm
        if height is not None:
            if not height.is_finite() or not MIN_HEIGHT_CM <= height <= MAX_HEIGHT_CM:
                raise InvalidInput(f"a height is between {MIN_HEIGHT_CM} and {MAX_HEIGHT_CM} cm")
            height = height.quantize(_HEIGHT_STEP, rounding=ROUND_HALF_UP)
        rate = self.target_rate_pct_per_week
        if rate is not None:
            if not rate.is_finite() or not 0 <= rate <= MAX_TARGET_RATE:
                raise InvalidInput(f"a weekly rate is between 0 and {MAX_TARGET_RATE} percent")
            rate = rate.quantize(_RATE_STEP, rounding=ROUND_HALF_UP)
        return replace(self, height_cm=height, target_rate_pct_per_week=rate)


# --- the AI provider shown next to the consent --------------------------------------------

# What we say when the settings don't name the provider: where each LLM_PROVIDER is served from.
PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "gemini": ("Google (Gemini)", "United States"),
    "openrouter": ("OpenRouter (routes to the model's provider)", "United States"),
    "deepseek": ("DeepSeek", "China"),
    "openai": ("OpenAI", "United States"),
}


def provider_disclosure(
    llm_provider: str, name: str | None, country: str | None
) -> tuple[str, str]:
    """The provider's name and country as the user is told them: the settings win, the
    provider in use fills the gaps."""
    known = PROVIDER_DEFAULTS.get(llm_provider, (llm_provider, "unknown"))
    return (name or known[0], country or known[1])
