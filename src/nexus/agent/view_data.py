"""Putting views on screen (ADR 0005): the figures behind a view, and the two ways one gets
into a turn.

``build`` runs the use case a view is built from and gives a ``ViewRef``: the caption and
headline figures come from the catalog's builders, so from code, never from the model. The
web endpoint ``GET /api/views/{kind}`` calls ``build`` too, so a card and the page it opens
read the same figures as the tool that answered.

A view gets into a turn by ``present`` (Prime chose it) or by ``surface`` (the safety net: a
tool that answered opens its default view, see ``views.surfaced``). Both add to the turn's
``TurnViews``, which dedupes and caps them.
"""

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from nexus.agent.progress import TurnViews
from nexus.agent.tools.core import ToolContext, ToolResult
from nexus.agent.tools.fx import rates
from nexus.agent.tools.helpers import parse_day
from nexus.agent.views import (
    CATALOG,
    DayFacts,
    DayParams,
    MonthParams,
    RecordsParams,
    SpendingParams,
    TripBudgetParams,
    ViewKind,
    ViewParams,
    ViewRef,
    ViewSpec,
    ViewStatus,
    WorkoutParams,
    surfaced,
)
from nexus.application import budgets as budget_cases
from nexus.application import coach as coach_cases
from nexus.application import energy as energy_cases
from nexus.application import gym as gym_cases
from nexus.application import health_targets as targets_cases
from nexus.application import investments as investment_cases
from nexus.application import month_outlook as outlook_cases
from nexus.application import nutrition as nutrition_cases
from nexus.application import transactions as tx_cases
from nexus.application import trip_access as access_cases
from nexus.application import trips as trip_cases
from nexus.application.wallet_figures import month_range
from nexus.domain.errors import ConsentRequired, InvalidInput, NexusError

log = logging.getLogger(__name__)

HEALTH_VIEWS = frozenset(
    {ViewKind.TODAY, ViewKind.WEIGHT_TREND, ViewKind.WORKOUT, ViewKind.RECORDS}
)
HEALTH_OFF = "Health is off, so there is no view of it. The user can turn Health on in the app."


def month_of(day: date) -> str:
    return f"{day:%Y-%m}"


def _first(month: str) -> date:
    return date.fromisoformat(month + "-01")


def _uuid(text: str, what: str) -> UUID:
    try:
        return UUID(text)
    except ValueError as exc:
        raise InvalidInput(f"{what} is not an id from a tool result") from exc


async def _spending(ctx: ToolContext, p: SpendingParams) -> Any:
    tz = ctx.tz
    start, end = month_range(ctx.user, datetime.combine(_first(p.month), time(12), tzinfo=tz))
    summary = await tx_cases.summarize_in_home(ctx.uow(), rates(ctx), ctx.user, start, end)
    if p.category_id is None:
        return summary
    wanted = _uuid(p.category_id, "category_id")
    return replace(
        summary,
        spending_by_category=[c for c in summary.spending_by_category if c.category_id == wanted],
    )


async def _trip(ctx: ToolContext, p: TripBudgetParams) -> Any:
    # The owner's own trip only: for a trip someone shared, this is NotFound, so a member
    # never gets the owner's money in a card (as for the page).
    return await trip_cases.trip_view(
        ctx.uow, rates(ctx), ctx.user, _uuid(p.trip_id, "trip_id"), now=ctx.now
    )


async def _day(ctx: ToolContext, p: DayParams) -> DayFacts:
    today = p.day is None or p.day == ctx.today()
    targets = None
    if today:
        found = await targets_cases.safe_targets(ctx.uow, ctx.user.id, now=ctx.now, record=False)
        targets = found.overview.targets
    food = await nutrition_cases.day_summary(
        ctx.uow(), ctx.user.id, p.day, targets=targets, now=ctx.now
    )
    workout = await gym_cases.todays_workout(ctx.uow(), ctx.user.id, now=ctx.now) if today else None
    return DayFacts(food, workout)


async def _workout(ctx: ToolContext, p: WorkoutParams) -> Any:
    if p.state == "suggested":
        if p.suggestion_id is None:
            raise InvalidInput("a suggested workout needs suggestion_id, from suggest_workout")
        return await coach_cases.suggestion(
            ctx.uow(), ctx.user.id, _uuid(p.suggestion_id, "suggestion_id"), now=ctx.now
        )
    return await gym_cases.todays_workout(ctx.uow(), ctx.user.id, now=ctx.now)


async def _records(ctx: ToolContext, p: RecordsParams) -> Any:
    if p.exercise:
        return await gym_cases.records(ctx.uow(), ctx.user.id, p.exercise)
    return await gym_cases.all_records(ctx.uow(), ctx.user.id)


async def fetch(ctx: ToolContext, kind: ViewKind, p: Any) -> Any:
    """What the view's use case gives for these params: the same call the tool makes."""
    match kind:
        case ViewKind.MONTH_OUTLOOK:
            return await outlook_cases.month_outlook(
                ctx.uow, rates(ctx), ctx.user, now=ctx.now, month=p.month
            )
        case ViewKind.BUDGETS:
            return await budget_cases.budget_statuses(
                ctx.uow, rates(ctx), ctx.user, now=ctx.now, month=_first(p.month)
            )
        case ViewKind.SPENDING:
            return await _spending(ctx, p)
        case ViewKind.TRIP_BUDGET:
            return await _trip(ctx, p)
        case ViewKind.PORTFOLIO:
            return await investment_cases.valuation(ctx.uow(), rates(ctx), ctx.user, now=ctx.now)
        case ViewKind.TODAY:
            return await _day(ctx, p)
        case ViewKind.WEIGHT_TREND:
            return await energy_cases.weight_overview(ctx.uow(), ctx.user.id, now=ctx.now)
        case ViewKind.WORKOUT:
            return await _workout(ctx, p)
        case ViewKind.RECORDS:
            return await _records(ctx, p)
        case _:
            return None  # TRIPS has no figures: a link to the list


def _spec(kind: ViewKind) -> ViewSpec:
    spec = CATALOG[kind]
    if spec.status is not ViewStatus.LIVE:
        raise InvalidInput(f"{kind.value} is not available yet")
    return spec


async def build(ctx: ToolContext, kind: ViewKind, params: ViewParams, *, focus: bool) -> ViewRef:
    """The view with its caption and figures, read now. Raises ``ConsentRequired`` for a
    Health view without consent, ``NotFound`` for what isn't the user's."""
    spec = _spec(kind)
    if kind in HEALTH_VIEWS and await gym_cases.consent(ctx.uow(), ctx.user.id) is None:
        raise ConsentRequired(HEALTH_OFF)
    result = await fetch(ctx, kind, params)
    return ViewRef(
        kind=kind,
        view_id=spec.view_id(params),
        params=params.model_dump(mode="json", exclude_none=True),
        focus=focus,
        caption=spec.caption(params),
        summary=spec.summary(result),
    )


def check(view: str, raw: Mapping[str, object]) -> tuple[ViewKind, ViewParams]:
    """The view and its params, checked against the catalog. Raises ``InvalidInput`` saying
    what to fix: an unknown or planned view, or params that don't fit."""
    try:
        kind = ViewKind(view)
    except ValueError:
        live = ", ".join(k.value for k, s in CATALOG.items() if s.status is ViewStatus.LIVE)
        raise InvalidInput(f"no view called {view!r}; use one of: {live}") from None
    spec = _spec(kind)
    try:
        return kind, spec.validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'params'}: {e['msg']}" for e in exc.errors()
        )
        raise InvalidInput(f"bad params for {view}: {problems}") from exc


async def present(
    ctx: ToolContext, turn: TurnViews | None, view: str, raw: Mapping[str, object], focus: bool
) -> ToolResult:
    """The ``present`` tool. A bad call is an "Error: ..." for the model to fix; with no turn
    note (views off, or a caller that keeps none) it says there is no screen."""
    kind, params = check(view, raw)
    if turn is None:
        return ToolResult("There is no screen to show a view on here: just answer.")
    ref = await build(ctx, kind, params, focus=focus)
    if not turn.add(ref, presented=True):
        raise InvalidInput(
            "this turn already shows the most views it can (3). Answer with what is on screen."
        )
    return ToolResult(
        f'On screen: "{ref.caption}". It carries its own figures: say only figures a tool gave you.'
    )


# --- the safety net ---------------------------------------------------------------------


def _this_month(ctx: ToolContext) -> str:
    return month_of(ctx.today())


def _month_from(ctx: ToolContext, text: object) -> str:
    """The month a ``YYYY-MM`` or ``YYYY-MM-DD`` argument names; this month when absent."""
    if isinstance(text, str) and len(text) >= 7:
        try:
            return month_of(date.fromisoformat(text[:7] + "-01"))
        except ValueError:
            pass
    return _this_month(ctx)


async def _trip_params(ctx: ToolContext, args: Mapping[str, Any]) -> ViewParams | None:
    found = await access_cases.find_trip(ctx.uow, ctx.user, args.get("trip"), now=ctx.now)
    return None if found.shared else TripBudgetParams(trip_id=str(found.trip.id))


async def _records_params(ctx: ToolContext, args: Mapping[str, Any]) -> ViewParams:
    said = args.get("exercise")
    if not said:
        return RecordsParams()
    from nexus.agent.tools.gym import resolve_exercise  # gym imports the tools package

    try:
        return RecordsParams(exercise=(await resolve_exercise(ctx, str(said))).id)
    except NexusError:
        return RecordsParams()


def _suggestion_id(result: ToolResult) -> str | None:
    for row in result.buttons or []:
        for _, data in row:
            if data.startswith("workout:start:"):
                return data.removeprefix("workout:start:")
    return None


async def _params_for(
    ctx: ToolContext, kind: ViewKind, tool: str, args: Mapping[str, Any], result: ToolResult
) -> ViewParams | None:
    """The params the tool's answer opens its view with, read from what the user asked."""
    match kind:
        case ViewKind.MONTH_OUTLOOK:
            return MonthParams(month=_month_from(ctx, args.get("month")))
        case ViewKind.BUDGETS:
            return MonthParams(month=_this_month(ctx))
        case ViewKind.SPENDING:
            return SpendingParams(month=_month_from(ctx, args.get("start_date")))
        case ViewKind.TRIP_BUDGET:
            return await _trip_params(ctx, args)
        case ViewKind.TODAY:
            if tool == "food_today" and args.get("day"):
                return DayParams(day=parse_day(ctx, str(args["day"])).astimezone(ctx.tz).date())
            return DayParams()
        case ViewKind.WORKOUT:
            if tool == "suggest_workout":
                found = _suggestion_id(result)
                return (
                    None if found is None else WorkoutParams(state="suggested", suggestion_id=found)
                )
            return WorkoutParams()
        case ViewKind.RECORDS:
            return await _records_params(ctx, args)
        case _:
            return CATALOG[kind].params()


async def surface(
    turn: TurnViews, ctx: ToolContext, tool: str, args: Mapping[str, Any], result: ToolResult
) -> None:
    """After a tool that answered: add the view the catalog says it opens, if any. Never
    raises: a card that can't be built is no card, the answer stands without it."""
    if tool == "present":  # it built its own view, with the params Prime chose
        return
    kind = surfaced(tool, args)
    if kind is None or CATALOG[kind].status is not ViewStatus.LIVE:
        return
    try:
        params = await _params_for(ctx, kind, tool, args, result)
        if params is None:
            return
        # The first view the net adds is the turn's focus unless Prime presents another.
        turn.add(await build(ctx, kind, params, focus=False))
    except Exception as exc:
        log.info("no view for %s: %s", tool, type(exc).__name__)
