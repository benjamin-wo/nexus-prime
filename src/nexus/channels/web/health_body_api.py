"""The Health foundation's API: body and activity samples, the wellness profile, and the
separate consents. Writing needs the user's consent (403 until they give it); the master
consent is Gym's ``/api/health/consent``."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import coach as coach_cases
from nexus.application import health as health_cases
from nexus.application import health_consent as consent_cases
from nexus.application import health_safety as safety_cases
from nexus.channels.web.health_api import _uuid, _weight
from nexus.channels.web.security import Auth, Runtime
from nexus.domain.coach import (
    MAX_DAYS,
    MAX_SESSION_MINUTES,
    MIN_DAYS,
    MIN_SESSION_MINUTES,
    Experience,
    Focus,
    TrainingProfile,
)
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.gym import Equipment
from nexus.domain.health import (
    WELLNESS_STATEMENT,
    ActivityLevel,
    ConsentScope,
    Goal,
    HealthProfile,
    Sample,
    SampleKind,
    SampleSource,
    SampleUnit,
    Sex,
    UnitSystem,
    provider_disclosure,
)
from nexus.domain.health_safety import Gate

router = APIRouter(prefix="/api/health")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- samples --------------------------------------------------------------------------------


class SampleIn(Model):
    kind: SampleKind
    value: str = Field(max_length=24)
    unit: SampleUnit | None = None  # the kind's usual unit when left out
    start_at: datetime | None = None  # now when left out
    end_at: datetime | None = None  # start_at when left out
    source: SampleSource = SampleSource.MANUAL
    source_name: str | None = Field(None, max_length=100)
    external_id: str | None = Field(None, max_length=300)


class SamplePatch(Model):
    value: str | None = Field(None, max_length=24)
    unit: SampleUnit | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


class SampleOut(Model):
    id: str
    kind: SampleKind
    value: str  # as entered, in ``unit``
    unit: SampleUnit
    value_kg: str | None  # weights only
    start_at: datetime
    end_at: datetime
    source: SampleSource
    source_name: str | None
    external_id: str | None
    created_at: datetime


def _sample(s: Sample) -> SampleOut:
    kg = s.weight_kg
    return SampleOut(
        id=str(s.id),
        kind=s.kind,
        value=str(s.value),
        unit=s.unit,
        value_kg=str(kg.quantize(Decimal("0.01"))) if kg is not None else None,
        start_at=s.start_at,
        end_at=s.end_at,
        source=s.source,
        source_name=s.source_name,
        external_id=s.external_id,
        created_at=s.created_at,
    )


def _number(value: str | None) -> Decimal:
    number = _weight(value)
    if number is None:
        raise InvalidInput("a value is needed")
    return number


@router.post("/samples", status_code=201)
async def log_sample(body: SampleIn, auth: Auth, web: Runtime) -> SampleOut:
    """Record a measurement. A typed or chat entry for the same kind and moment replaces the
    earlier one; an imported sample with a known source and external id updates it."""
    logged = await health_cases.log_sample(
        web.uow(),
        auth.user.id,
        body.kind,
        _number(body.value),
        unit=body.unit,
        start_at=body.start_at,
        end_at=body.end_at,
        source=body.source,
        source_name=body.source_name,
        external_id=body.external_id,
        now=web.clock(),
    )
    return _sample(logged)


@router.get("/samples")
async def samples(
    auth: Auth,
    web: Runtime,
    kind: SampleKind | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=health_cases.MAX_SAMPLES)] = health_cases.MAX_SAMPLES,
) -> list[SampleOut]:
    """Samples that started in ``[start, end)``, newest first; the last 30 days by default."""
    found = await health_cases.samples(
        web.uow(), auth.user.id, kind, start=start, end=end, limit=limit, now=web.clock()
    )
    return [_sample(s) for s in found]


@router.get("/samples/latest")
async def latest_sample(kind: SampleKind, auth: Auth, web: Runtime) -> SampleOut | None:
    found = await health_cases.latest(web.uow(), auth.user.id, kind, now=web.clock())
    return _sample(found) if found else None


@router.patch("/samples/{sample_id}")
async def edit_sample(sample_id: str, body: SamplePatch, auth: Auth, web: Runtime) -> SampleOut:
    changes: dict[str, Any] = {}
    for name in body.model_fields_set:
        value = getattr(body, name)
        if value is None:
            raise InvalidInput(f"{name} can't be cleared")
        changes[name] = _number(value) if name == "value" else value
    edited = await health_cases.edit_sample(
        web.uow(), auth.user.id, _uuid(sample_id, "sample"), changes, now=web.clock()
    )
    return _sample(edited)


@router.delete("/samples/{sample_id}", status_code=204)
async def delete_sample(sample_id: str, auth: Auth, web: Runtime) -> None:
    await health_cases.delete_sample(
        web.uow(), auth.user.id, _uuid(sample_id, "sample"), now=web.clock()
    )


# --- the profile ----------------------------------------------------------------------------


class ProfileIn(Model):
    sex_for_equations: Sex = Sex.UNSPECIFIED  # used only for energy equations
    birth_year: int | None = None
    height_cm: str | None = Field(None, max_length=16)
    activity_level: ActivityLevel | None = None
    goal: Goal = Goal.MAINTAIN
    target_rate_pct_per_week: str | None = Field(None, max_length=16)
    numbers_free: bool | None = None  # follows ed_history when left out
    ed_history: bool = False
    unit_system: UnitSystem = UnitSystem.METRIC
    # Explicitly confirm a loss goal despite an eating-disorder history. Never stored.
    confirm_ed_override: bool = False


class GateOut(Model):
    name: str
    allowed: bool
    reason: str  # a reason code, not prose


class SignpostOut(Model):
    name: str
    contact: str
    note: str


class SafetyOut(Model):
    gates: list[GateOut]
    suspended: bool  # calorie-target features are off
    signposts: list[SignpostOut]


class ProfileOut(Model):
    sex_for_equations: Sex
    birth_year: int | None
    height_cm: str | None
    activity_level: ActivityLevel | None
    goal: Goal
    target_rate_pct_per_week: str | None
    numbers_free: bool
    ed_history: bool
    unit_system: UnitSystem
    updated_at: datetime
    safety: SafetyOut


def _safety(state: safety_cases.SafetyState, gate: Gate | None = None) -> SafetyOut:
    gate = gate or state.weight_loss_gate
    return SafetyOut(
        gates=[GateOut(name="weight_loss", allowed=gate.allowed, reason=gate.reason.value)],
        suspended=state.suspended,
        signposts=[
            SignpostOut(name=s.name, contact=s.contact, note=s.note) for s in state.signposts
        ],
    )


def _profile(p: HealthProfile, safety: SafetyOut) -> ProfileOut:
    return ProfileOut(
        sex_for_equations=p.sex_for_equations,
        birth_year=p.birth_year,
        height_cm=None if p.height_cm is None else str(p.height_cm),
        activity_level=p.activity_level,
        goal=p.goal,
        target_rate_pct_per_week=(
            None if p.target_rate_pct_per_week is None else str(p.target_rate_pct_per_week)
        ),
        numbers_free=p.numbers_free,
        ed_history=p.ed_history,
        unit_system=p.unit_system,
        updated_at=p.updated_at,
        safety=safety,
    )


@router.get("/profile")
async def get_profile(auth: Auth, web: Runtime) -> ProfileOut | None:
    found = await health_cases.profile(web.uow(), auth.user.id, now=web.clock())
    if found is None:
        return None
    state = await safety_cases.assess(web.uow(), auth.user.id, now=web.clock())
    return _profile(found, _safety(state))


@router.put("/profile")
async def save_profile(body: ProfileIn, auth: Auth, web: Runtime) -> ProfileOut:
    """Replace the profile. Only input errors are refused here. A loss goal the safety gates
    block is stored as "maintain", and ``safety.gates`` says why."""
    saved = await health_cases.save_profile_checked(
        web.uow(),
        auth.user.id,
        sex_for_equations=body.sex_for_equations,
        birth_year=body.birth_year,
        height_cm=_weight(body.height_cm),
        activity_level=body.activity_level,
        goal=body.goal,
        target_rate_pct_per_week=_weight(body.target_rate_pct_per_week),
        numbers_free=body.numbers_free,
        ed_history=body.ed_history,
        unit_system=body.unit_system,
        confirm_ed_override=body.confirm_ed_override,
        now=web.clock(),
    )
    state = await safety_cases.assess(web.uow(), auth.user.id, now=web.clock())
    return _profile(saved.profile, _safety(state, saved.gate))


# --- the Gym coach's inputs -----------------------------------------------------------------


class TrainingIn(Model):
    days_per_week: int = Field(ge=MIN_DAYS, le=MAX_DAYS)
    session_minutes: int = Field(ge=MIN_SESSION_MINUTES, le=MAX_SESSION_MINUTES)
    equipment: list[Equipment] = Field(max_length=len(Equipment))  # body weight needs no entry
    experience: Experience
    focus: Focus


@router.get("/profile/training")
async def get_training(auth: Auth, web: Runtime) -> TrainingIn | None:
    """What the Gym coach plans around, or null until it is set."""
    found = await coach_cases.training_profile(web.uow(), auth.user.id)
    return None if found is None else TrainingIn(**found.as_dict())


@router.put("/profile/training")
async def save_training(body: TrainingIn, auth: Auth, web: Runtime) -> TrainingIn:
    """Replace the coach inputs (needs the Health consent, like every health write)."""
    saved = await coach_cases.save_training_profile(
        web.uow(),
        auth.user.id,
        TrainingProfile(
            body.days_per_week,
            body.session_minutes,
            tuple(body.equipment),
            body.experience,
            body.focus,
        ),
        now=web.clock(),
    )
    return TrainingIn(**saved.as_dict())


# --- consents -------------------------------------------------------------------------------


class ScopeOut(Model):
    scope: ConsentScope
    active: bool
    granted_at: datetime | None
    withdrawn_at: datetime | None


class ProviderOut(Model):
    name: str
    country: str


class ConsentsOut(Model):
    health_consented_at: datetime | None  # the master consent (``/consent``)
    scopes: list[ScopeOut]
    ai_provider: ProviderOut  # who receives health data when ``ai_processing`` is on
    wellness_statement: str


def _scope(s: consent_cases.ScopeState) -> ScopeOut:
    return ScopeOut(
        scope=s.scope, active=s.active, granted_at=s.granted_at, withdrawn_at=s.withdrawn_at
    )


@router.get("/consents")
async def get_consents(auth: Auth, web: Runtime) -> ConsentsOut:
    return _consents_out(await consent_cases.overview(web.uow(), auth.user.id), web)


def _consents_out(state: consent_cases.ConsentOverview, web: Runtime) -> ConsentsOut:
    settings = web.settings
    name, country = provider_disclosure(
        settings.llm_provider.value, settings.ai_provider_name, settings.ai_provider_country
    )
    return ConsentsOut(
        health_consented_at=state.health_at,
        scopes=[_scope(s) for s in state.scopes],
        ai_provider=ProviderOut(name=name, country=country),
        wellness_statement=WELLNESS_STATEMENT,
    )


@router.post("/consent/all", status_code=201)
async def turn_on_health(auth: Auth, web: Runtime) -> ConsentsOut:
    """One tap: the master consent and ``ai_processing``. Doing it again changes nothing."""
    state = await consent_cases.turn_on(web.uow(), auth.user.id, now=web.clock())
    return _consents_out(state, web)


def _consent_scope(value: str) -> ConsentScope:
    try:
        return ConsentScope(value)
    except ValueError as exc:
        raise NotFound("no such consent") from exc


@router.put("/consents/{scope}")
async def grant_consent(scope: str, auth: Auth, web: Runtime) -> ScopeOut:
    """Agree to one scope. Needs the master consent first; doing it again changes nothing."""
    return _scope(
        await consent_cases.grant(web.uow(), auth.user.id, _consent_scope(scope), now=web.clock())
    )


@router.delete("/consents/{scope}")
async def withdraw_consent(scope: str, auth: Auth, web: Runtime) -> ScopeOut:
    """Take one scope back. What is stored stays until you delete it."""
    return _scope(
        await consent_cases.withdraw(
            web.uow(), auth.user.id, _consent_scope(scope), now=web.clock()
        )
    )
