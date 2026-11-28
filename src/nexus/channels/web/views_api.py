"""Web API: the figures behind a view (ADR 0005).

``GET /api/views/{kind}?<params>`` answers with what the card in the chat shows and what the
page behind it can read: the caption and the headline figures of ``agent.view_data.build``,
the same function the chat uses when a tool answered or Prime presented the view, so the
card, the page and Prime's own words are one set of figures. Params are the view's, as query
parameters (a user id is never one: the signed-in user is the tenant). A Health view needs the
user's Health consent (403 without it) and shows no numbers in numbers-free mode. Off unless
views are switched on (404).
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, ValidationError

from nexus.agent import view_data
from nexus.agent.tools.core import ToolContext
from nexus.agent.views import CATALOG, ViewKind, ViewStatus
from nexus.channels.web.security import Auth, Runtime
from nexus.channels.web.shapes import Model, MoneyOut

router = APIRouter(prefix="/api")


class Figures(Model):
    pass


class OutlookFigures(Figures):
    status: str
    received: MoneyOut | None
    spent: MoneyOut | None
    overall: MoneyOut | None
    headroom: MoneyOut | None
    shortfall: MoneyOut | None


class BudgetRow(Model):
    name: str
    spent: MoneyOut | None
    limit: MoneyOut | None
    percent: int


class BudgetsFigures(Figures):
    count: int
    over: int
    budgets: list[BudgetRow]


class CategoryRow(Model):
    name: str
    total: MoneyOut | None


class SpendingFigures(Figures):
    spent: MoneyOut | None
    count: int
    categories: list[CategoryRow]


class TripFigures(Figures):
    budget: MoneyOut | None
    spent: MoneyOut | None
    left: MoneyOut | None
    percent: int | None
    to_spend: MoneyOut | None


class PortfolioFigures(Figures):
    holdings: int
    value: MoneyOut | None
    cost: MoneyOut | None
    gain: MoneyOut | None
    day_change: MoneyOut | None
    as_of: str | None


class WorkoutFigures(Figures):
    state: Literal["suggested", "open", "planned", "rest"]
    focus: str | None = None
    routine: str | None = None
    exercises: int | None = None
    minutes: int | None = None
    started_at: str | None = None


class TodayFigures(Figures):
    day: str
    meals: int
    # Left out in numbers-free mode, together with the target.
    kcal: str | None = None
    protein_g: str | None = None
    kcal_target: str | None = None
    workout: WorkoutFigures | None = None


class WeightFigures(Figures):
    hidden: bool
    trend_words: str
    # Left out in numbers-free mode: only the direction in words is left.
    trend_kg: str | None = None
    kg_a_week: str | None = None
    weigh_ins: int | None = None


class RecordRow(Model):
    exercise: str
    heaviest_kg: str | None
    e1rm_kg: str | None
    sessions: int


class RecordsFigures(Figures):
    records: list[RecordRow]


class NoFigures(Figures):
    pass


# The figures model of each view; a view with no figures of its own (the trips list) has none.
FIGURES: dict[ViewKind, type[Figures]] = {
    ViewKind.MONTH_OUTLOOK: OutlookFigures,
    ViewKind.BUDGETS: BudgetsFigures,
    ViewKind.SPENDING: SpendingFigures,
    ViewKind.TRIP_BUDGET: TripFigures,
    ViewKind.PORTFOLIO: PortfolioFigures,
    ViewKind.TODAY: TodayFigures,
    ViewKind.WEIGHT_TREND: WeightFigures,
    ViewKind.WORKOUT: WorkoutFigures,
    ViewKind.RECORDS: RecordsFigures,
    ViewKind.TRIPS: NoFigures,
}


class ViewBase(Model):
    view_id: str
    params: dict[str, Any]
    caption: str


class OutlookView(ViewBase):
    kind: Literal["finance.month_outlook"]
    summary: OutlookFigures


class BudgetsView(ViewBase):
    kind: Literal["finance.budgets"]
    summary: BudgetsFigures


class SpendingView(ViewBase):
    kind: Literal["finance.spending"]
    summary: SpendingFigures


class TripBudgetView(ViewBase):
    kind: Literal["travel.trip_budget"]
    summary: TripFigures


class TripsView(ViewBase):
    kind: Literal["travel.trips"]
    summary: NoFigures


class PortfolioView(ViewBase):
    kind: Literal["invest.portfolio"]
    summary: PortfolioFigures


class TodayView(ViewBase):
    kind: Literal["health.today"]
    summary: TodayFigures


class WeightTrendView(ViewBase):
    kind: Literal["health.weight_trend"]
    summary: WeightFigures


class WorkoutView(ViewBase):
    kind: Literal["health.workout"]
    summary: WorkoutFigures


class RecordsView(ViewBase):
    kind: Literal["health.records"]
    summary: RecordsFigures


ViewOut = Annotated[
    OutlookView
    | BudgetsView
    | SpendingView
    | TripBudgetView
    | TripsView
    | PortfolioView
    | TodayView
    | WeightTrendView
    | WorkoutView
    | RecordsView,
    Field(discriminator="kind"),
]

_VIEWS: dict[ViewKind, type[ViewBase]] = {
    ViewKind.MONTH_OUTLOOK: OutlookView,
    ViewKind.BUDGETS: BudgetsView,
    ViewKind.SPENDING: SpendingView,
    ViewKind.TRIP_BUDGET: TripBudgetView,
    ViewKind.TRIPS: TripsView,
    ViewKind.PORTFOLIO: PortfolioView,
    ViewKind.TODAY: TodayView,
    ViewKind.WEIGHT_TREND: WeightTrendView,
    ViewKind.WORKOUT: WorkoutView,
    ViewKind.RECORDS: RecordsView,
}


@router.get("/views/{kind}", response_model=ViewOut)
async def get_view(kind: str, request: Request, auth: Auth, web: Runtime) -> ViewBase:
    """A view's caption and figures for these params, read now."""
    if not web.settings.views_enabled:
        raise HTTPException(status_code=404)
    try:
        found = ViewKind(kind)
    except ValueError:
        raise HTTPException(status_code=404) from None
    spec = CATALOG[found]
    if spec.status is not ViewStatus.LIVE:
        raise HTTPException(status_code=404)
    try:
        params = spec.validate(dict(request.query_params))
    except ValidationError as exc:
        problems = exc.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status_code=422, detail=problems) from exc
    ctx = ToolContext(auth.user, web.uow, web.clock(), rates=web.rates)
    ref = await view_data.build(ctx, found, params, focus=False)
    return _VIEWS[found].model_validate(
        {
            "view_id": ref.view_id,
            "kind": ref.kind.value,
            "params": ref.params,
            "caption": ref.caption,
            "summary": ref.summary or {},
        }
    )
