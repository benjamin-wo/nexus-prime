"""Weight trend, energy estimate and targets over HTTP. Everything is computed from weigh-ins
and the profile. With ``numbers_free`` on, only the qualitative wording is returned."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from nexus.application import energy as energy_cases
from nexus.application import health_targets as targets_cases
from nexus.channels.web.security import Auth, Runtime
from nexus.domain.health_texts import TEXT_CHECK_IN, Signpost

router = APIRouter(prefix="/api/health")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrendPointOut(Model):
    date: date
    scale_kg: str | None
    trend_kg: str


class LastWeighInOut(Model):
    at: datetime
    kg: str


class WeightOut(Model):
    hidden: bool
    trend_words: str  # steady, slowly down, slowly up
    points: list[TrendPointOut] | None  # None when hidden
    trend_kg: str | None
    rate_kg_per_week: str | None
    rate_pct_per_week: str | None
    rate_text: str | None  # "about 0.4 kg a week down over the last 2 weeks"
    last_weigh_in: LastWeighInOut | None


class TargetsOut(Model):
    kcal: str
    kcal_low: str
    kcal_high: str
    protein_g: str
    fibre_g: str
    rate_pct_per_week: str
    notes: list[str]


class SignpostOut(Model):
    name: str
    contact: str
    note: str


class SafetyNoteOut(Model):
    """Shared by the energy and day reads. ``suspended``: calorie targets are off, so there are
    none, and ``signposts`` say where to get help. ``new_signals`` lists signals first recorded
    by this read (a soft check-in is due, with ``check_in`` as its text)."""

    suspended: bool
    signposts: list[SignpostOut]
    new_signals: list[str]
    check_in: str | None


def safety_note(found: targets_cases.SafeOverview) -> SafetyNoteOut:
    return SafetyNoteOut(
        suspended=found.suspended,
        signposts=[signpost(s) for s in found.signposts],
        new_signals=[s.value for s in found.new_signals],
        check_in=TEXT_CHECK_IN if found.check_in else None,
    )


def signpost(s: Signpost) -> SignpostOut:
    return SignpostOut(name=s.name, contact=s.contact, note=s.note)


class EnergyOut(Model):
    hidden: bool
    trend_words: str
    available: bool  # False until the profile and a weigh-in allow an estimate
    label: str | None  # "estimated from your profile" or "worked out from your logged ..."
    paused_reason: str | None
    kcal: str | None
    kcal_low: str | None
    kcal_high: str | None
    confidence: str | None
    days_used: int | None
    targets: TargetsOut | None
    safety: SafetyNoteOut


@router.get("/weight")
async def weight(
    auth: Auth, web: Runtime, days: Annotated[int, Query(ge=1, le=energy_cases.MAX_DAYS)] = 90
) -> WeightOut:
    o = await energy_cases.weight_overview(web.uow(), auth.user.id, now=web.clock(), days=days)
    last = o.last_weigh_in
    if o.hidden:
        return WeightOut(
            hidden=True, trend_words=o.trend_words, points=None, trend_kg=None,
            rate_kg_per_week=None, rate_pct_per_week=None, rate_text=None, last_weigh_in=None,
        )  # fmt: skip
    return WeightOut(
        hidden=False,
        trend_words=o.trend_words,
        points=[
            TrendPointOut(
                date=p.date,
                scale_kg=None if p.scale_kg is None else str(p.scale_kg),
                trend_kg=str(p.trend_kg),
            )
            for p in o.points
        ],
        trend_kg=None if o.trend_kg is None else str(o.trend_kg),
        rate_kg_per_week=None if o.rate is None else str(o.rate[0]),
        rate_pct_per_week=None if o.rate is None else str(o.rate[1]),
        rate_text=energy_cases.rate_sentence(o.rate, o.rate_days),
        last_weigh_in=None if last is None else LastWeighInOut(at=last[0], kg=str(last[1])),
    )


@router.get("/energy")
async def energy(auth: Auth, web: Runtime) -> EnergyOut:
    found = await targets_cases.safe_targets(web.uow, auth.user.id, now=web.clock())
    t, note = found.overview, safety_note(found)
    e = t.energy
    est = e.estimate
    if t.hidden or est is None:
        return EnergyOut(
            hidden=t.hidden, trend_words=e.trend_words, available=est is not None and not t.hidden,
            label=None if t.hidden else e.label, paused_reason=None, kcal=None, kcal_low=None,
            kcal_high=None, confidence=None, days_used=None, targets=None, safety=note,
        )  # fmt: skip
    goal = t.targets
    return EnergyOut(
        hidden=False,
        trend_words=e.trend_words,
        available=True,
        label=e.label,
        paused_reason=est.paused_reason,
        kcal=str(est.kcal),
        kcal_low=str(est.kcal_range[0]),
        kcal_high=str(est.kcal_range[1]),
        confidence=str(est.confidence.quantize(energy_cases.CONFIDENCE_STEP)),
        days_used=est.days_used,
        safety=note,
        targets=None
        if goal is None
        else TargetsOut(
            kcal=str(goal.kcal),
            kcal_low=str(goal.kcal_range[0]),
            kcal_high=str(goal.kcal_range[1]),
            protein_g=str(goal.protein_g),
            fibre_g=str(goal.fibre_g),
            rate_pct_per_week=str(goal.rate_pct_per_week),
            notes=list(goal.notes),
        ),
    )
