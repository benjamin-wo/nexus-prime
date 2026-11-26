"""The view catalog (ADR 0005): the hand-built views Prime can bring into a conversation.

A view is a screen the app already draws (the month outlook, a trip's money, today's food),
opened with params. Each has a spec here: its name, a description written for the model, a
Pydantic model for its params, a stable key, the web path of its page, a caption, a summary
built by code from what the tool found, and the tools whose answers open it. This module is
the one place that says which view is which page (``view_links`` reads it) and which tool
opens which view; every other tool is listed as opening none. A test fails for a registered
tool that is in neither list, so a new tool cannot be added without deciding.

Figures in a summary come from the use case's result, never from the model, and params are
the query the page takes (never a user id: the signed-in user is the tenant). Health views
are wellness only: a summary says what the numbers are and which way a trend went, never
what they mean.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nexus.application.budgets import BudgetStatus
from nexus.application.energy import WeightOverview
from nexus.application.gym import Records, Today
from nexus.application.investments import Valuation
from nexus.application.month_outlook import MonthOutlook
from nexus.application.nutrition import DaySummary
from nexus.application.transactions import HomeSummary
from nexus.application.trips import TripView
from nexus.domain.coach import WorkoutSuggestion
from nexus.domain.money import Money, minor_units

# The shape of a view's params. Bump a view's version only when a param is renamed or
# removed; adding one is not a change.
VERSION = 1

# How many budgets, categories or records a summary names. The view shows the rest.
SUMMARY_ROWS = 5

# At most this many views a turn, and at most one of them the focus (ADR 0005).
MAX_PER_TURN = 3

# Headline figures, JSON-ready: money as {"amount", "currency"} as the web API sends it.
type Summary = dict[str, Any]


class ViewKind(StrEnum):
    MONTH_OUTLOOK = "finance.month_outlook"
    BUDGETS = "finance.budgets"
    SPENDING = "finance.spending"
    TRANSACTIONS = "finance.transactions"
    AFFORDABILITY = "finance.affordability"
    TRIP_BUDGET = "travel.trip_budget"
    TRIPS = "travel.trips"
    PORTFOLIO = "invest.portfolio"
    TODAY = "health.today"
    WEIGHT_TREND = "health.weight_trend"
    WORKOUT = "health.workout"
    RECORDS = "health.records"


class ViewStatus(StrEnum):
    PLANNED = "planned"  # catalogued, no card yet: never opened, so never scored as opened
    LIVE = "live"
    HELD = "held"  # built but kept back (a regulatory question, say)


# --- params -----------------------------------------------------------------------------


class ViewParams(BaseModel):
    """What a view is opened with. Unknown fields are refused, so a user id (or anything
    else a caller made up) can't ride along to the client."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NoParams(ViewParams):
    pass


Month = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")]


class MonthParams(ViewParams):
    month: Month


class SpendingParams(ViewParams):
    month: Month
    category_id: str | None = None


class TripBudgetParams(ViewParams):
    trip_id: str = Field(description="an id from an earlier tool result")


class DayParams(ViewParams):
    day: date | None = Field(None, description="YYYY-MM-DD; today when left out")


class WorkoutParams(ViewParams):
    state: Literal["suggested", "open"] = "open"


class RecordsParams(ViewParams):
    exercise: str | None = Field(None, description="an exercise id; every lift when left out")


# --- summaries --------------------------------------------------------------------------


def _money(value: Money | None) -> dict[str, str] | None:
    """Money as the web API sends it, to the currency's minor units."""
    if value is None:
        return None
    shown = value.amount.quantize(Decimal(1).scaleb(-minor_units(value.currency)))
    return {"amount": str(shown), "currency": value.currency}


def _whole(value: Decimal) -> str:
    return str(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _one(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _outlook_summary(result: MonthOutlook) -> Summary:
    return {
        "status": result.status,
        "received": _money(result.received),
        "spent": _money(result.spent),
        "overall": _money(result.overall),
        "headroom": _money(result.headroom),
        "shortfall": _money(result.shortfall),
    }


def _budgets_summary(result: Sequence[BudgetStatus]) -> Summary:
    used = sorted(result, key=lambda s: s.percent, reverse=True)
    return {
        "count": len(result),
        "over": sum(1 for s in result if s.percent >= 100),
        "budgets": [
            {
                "name": s.name,
                "spent": _money(s.spent),
                "limit": _money(s.budget.limit),
                "percent": s.percent,
            }
            for s in used[:SUMMARY_ROWS]
        ],
    }


def _spending_summary(result: HomeSummary) -> Summary:
    return {
        "spent": _money(result.out.total),
        "count": result.out.count,
        "categories": [
            {"name": c.category_name or "Uncategorised", "total": _money(c.total)}
            for c in result.spending_by_category[:SUMMARY_ROWS]
        ],
    }


def _trip_summary(result: TripView) -> Summary:
    spending = result.spending
    return {
        "budget": _money(result.trip.budget),
        "spent": _money(spending.spent),
        "left": _money(spending.left),
        "percent": spending.percent,
        "to_spend": _money(result.to_spend),
    }


def _portfolio_summary(result: Valuation) -> Summary:
    return {
        "holdings": len(result.rows),
        "value": _money(result.value),
        "cost": _money(result.cost),
        "gain": _money(result.gain),
        "day_change": _money(result.day_change),
        "as_of": result.as_of.isoformat() if result.as_of else None,
    }


@dataclass(frozen=True, slots=True)
class DayFacts:
    """What ``health.today`` is built from: the day's food and, if there is one, its workout."""

    food: DaySummary
    workout: Today | None = None


def _today_summary(result: DayFacts) -> Summary:
    food = result.food
    out: Summary = {"day": food.day.isoformat(), "meals": len(food.entries)}
    if not food.hidden:  # numbers-free mode: foods and meal names only
        out["kcal"] = _whole(food.totals.point.kcal)
        out["protein_g"] = _whole(food.totals.point.protein_g)
        if food.targets is not None:
            out["kcal_target"] = _whole(food.targets.kcal)
    if result.workout is not None:
        out["workout"] = _workout_summary(result.workout)
    return out


def _weight_summary(result: WeightOverview) -> Summary:
    out: Summary = {"hidden": result.hidden, "trend_words": result.trend_words}
    if result.hidden:  # numbers-free mode: no weights, only the direction in words
        return out
    out["trend_kg"] = None if result.trend_kg is None else _one(result.trend_kg)
    out["kg_a_week"] = None if result.rate is None else _one(result.rate[0])
    out["weigh_ins"] = len(result.points)
    return out


def _workout_summary(result: Today | WorkoutSuggestion) -> Summary:
    if isinstance(result, WorkoutSuggestion):
        return {
            "state": "suggested",
            "focus": result.focus,
            "exercises": len(result.slots),
            "minutes": result.minutes,
        }
    if result.in_progress is not None:
        return {"state": "open", "started_at": result.in_progress.started_at.isoformat()}
    if result.routine is not None:
        return {
            "state": "planned",
            "routine": result.routine.name,
            "exercises": len(result.routine.slots),
        }
    return {"state": "rest"}


def _heaviest(record: Records) -> str | None:
    best = record.heaviest
    return None if best is None else _one(best.weight_kg or Decimal(0))


def _records_summary(result: Records | Sequence[Records]) -> Summary:
    rows = [result] if isinstance(result, Records) else list(result)
    return {
        "records": [
            {
                "exercise": r.exercise.name,
                "heaviest_kg": None
                if r.heaviest is None
                else _one(r.heaviest.weight_kg or Decimal(0)),
                "e1rm_kg": None if r.e1rm_kg is None else _one(r.e1rm_kg),
                "sessions": r.sessions,
            }
            for r in rows[:SUMMARY_ROWS]
        ]
    }


# --- captions ---------------------------------------------------------------------------


def month_label(month: str) -> str:
    return f"{date.fromisoformat(month + '-01'):%B %Y}"


def _day_label(day: date | None) -> str:
    return "" if day is None else f", {day.day} {day:%b}"


# --- the catalog ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShowText:
    """How the ``show`` tool brings a view up: the one line Prime says, the label of the
    button that opens it, and where it is in the app when there is no link to give."""

    line: str
    button: str
    where: str


@dataclass(frozen=True, slots=True)
class ViewSpec:
    """One view. ``description`` is for the model. ``key`` gives the stable view id from the
    params (the same id again updates the card in place). ``summary`` gives the headline
    figures from the use case's result. ``tools`` are the tools whose answers open it."""

    name: ViewKind
    description: str
    params: type[ViewParams]
    path: str  # a route of the web app
    caption: Callable[[Any], str]
    summary: Callable[[Any], Summary | None]
    status: ViewStatus
    tools: tuple[str, ...] = ()
    show: ShowText | None = None
    key: Callable[[Any], str] = field(default=lambda _: "")
    version: int = VERSION

    def view_id(self, params: ViewParams) -> str:
        return self.key(params) or self.name.value

    def validate(self, raw: Mapping[str, object]) -> ViewParams:
        """The params, checked; raises ``pydantic.ValidationError`` when they don't fit."""
        return self.params.model_validate(dict(raw))


def _nothing(_: object) -> None:
    return None


_SPECS: tuple[ViewSpec, ...] = (
    ViewSpec(
        ViewKind.MONTH_OUTLOOK,
        "The month at a glance: money in and out so far, the bills and pay still to come, "
        "and what should be left at the end. Use it for how a month is going.",
        MonthParams,
        "/accounting",
        lambda p: f"Your outlook for {month_label(p.month)}",
        _outlook_summary,
        ViewStatus.LIVE,
        ("month_outlook",),
        ShowText("Here's your month.", "Open month outlook", "Finance, under Overview"),
    ),
    ViewSpec(
        ViewKind.BUDGETS,
        "Each budget for a month with what is spent against it. Use it for how the user's "
        "budgets stand.",
        MonthParams,
        "/accounting/budgets",
        lambda p: f"Your budgets for {month_label(p.month)}",
        _budgets_summary,
        ViewStatus.LIVE,
        ("list_budgets",),
        ShowText("Here are your budgets.", "Open budgets", "Finance, under Budgets"),
    ),
    ViewSpec(
        ViewKind.SPENDING,
        "Where the money went in a month, by category. Use it for questions about spending "
        "patterns and what was spent on something.",
        SpendingParams,
        "/accounting",
        lambda p: f"Where your money went in {month_label(p.month)}",
        _spending_summary,
        ViewStatus.LIVE,
        ("query_ledger",),
    ),
    ViewSpec(
        ViewKind.TRANSACTIONS,
        "The ledger filtered by dates, direction, category or text. Planned: the spending "
        "view answers these for now.",
        NoParams,
        "/accounting/transactions",
        lambda _: "Your transactions",
        _nothing,
        ViewStatus.PLANNED,
    ),
    ViewSpec(
        ViewKind.AFFORDABILITY,
        "Whether a purchase or a trip fits a month. Planned: the month outlook answers "
        "'can I afford ...' for now.",
        MonthParams,
        "/accounting",
        lambda p: f"Can you afford it in {month_label(p.month)}",
        _nothing,
        ViewStatus.PLANNED,
    ),
    ViewSpec(
        ViewKind.TRIP_BUDGET,
        "One trip's money: its budget, what is spent and booked, and what is left. Use it "
        "for how a trip's spending is going.",
        TripBudgetParams,
        "/travel",
        lambda _: "Your trip's budget",
        _trip_summary,
        ViewStatus.LIVE,
        ("trip_status",),
        key=lambda p: f"{ViewKind.TRIP_BUDGET.value}:{p.trip_id}",
    ),
    ViewSpec(
        ViewKind.TRIPS,
        "The list of the user's trips.",
        NoParams,
        "/travel",
        lambda _: "Your trips",
        _nothing,
        ViewStatus.LIVE,
        (),
        ShowText("Here are your trips.", "Open trips", "Travel"),
    ),
    ViewSpec(
        ViewKind.PORTFOLIO,
        "The user's stock holdings with value and gain or loss. Use it for how the "
        "portfolio is doing.",
        NoParams,
        "/investment",
        lambda _: "Your portfolio",
        _portfolio_summary,
        ViewStatus.LIVE,
        ("show_portfolio",),
        ShowText("Here's your portfolio.", "Open portfolio", "Investments"),
    ),
    ViewSpec(
        ViewKind.TODAY,
        "The user's day in Health: what they ate and the workout of the day. Use it after a "
        "meal is logged and for what they ate today.",
        DayParams,
        "/health",
        lambda p: f"Your day{_day_label(p.day)}",
        _today_summary,
        ViewStatus.LIVE,
        ("food_today", "log_food", "log_photo_meal"),
        ShowText("Here's your day.", "Open Today", "Health, under Today"),
    ),
    ViewSpec(
        ViewKind.WEIGHT_TREND,
        "The user's weight trend over time. Use it for 'how is my weight going' and after a "
        "weigh-in. Wellness only: it shows the trend, never what it means.",
        NoParams,
        "/health",
        lambda _: "Your weight trend",
        _weight_summary,
        ViewStatus.LIVE,
        ("log_weight",),
        ShowText("Here's your weight trend.", "Open weight trend", "Health, under Today"),
    ),
    ViewSpec(
        ViewKind.WORKOUT,
        "A workout: the one Prime suggested for today, or the one open now. Use it for "
        "'what should I train', today's routine and while sets are being logged.",
        WorkoutParams,
        "/health/gym",
        lambda p: "Your suggested workout" if p.state == "suggested" else "Your workout",
        _workout_summary,
        ViewStatus.LIVE,
        ("todays_workout", "suggest_workout", "log_sets", "finish_workout"),
        ShowText("Here's your workout.", "Open workout", "Health, under Gym"),
    ),
    ViewSpec(
        ViewKind.RECORDS,
        "The user's best lifts: heaviest weight, estimated one-rep max, sessions. Use it for "
        "'what's my bench PR'.",
        RecordsParams,
        "/health/gym/history",
        lambda _: "Your records",
        _records_summary,
        ViewStatus.LIVE,
        ("personal_records",),
        ShowText("Here are your records.", "Open records", "Health, under Gym"),
    ),
)

CATALOG: dict[ViewKind, ViewSpec] = {spec.name: spec for spec in _SPECS}


# The tools that open a view, and the view each opens (derived from the specs above).
SURFACING: dict[str, ViewKind] = {t: spec.name for spec in _SPECS for t in spec.tools}

# Every other tool. Writes open nothing unless a spec says so; neither do lookups, the
# calculator, a currency check, the tools that read something no view shows yet, and
# ``show`` (it names its view itself: see ``surfaced``). ``spending_summary`` is a supporting
# lookup the model adds to other answers, so it opens nothing.
NON_SURFACING = frozenset(
    {
        "add_bill", "add_category", "add_to_itinerary", "add_to_trip", "add_trip_cover",
        "add_trip_todo", "add_wallet", "answer_email", "apply_adjustments", "calculate",
        "cash_flow", "change_itinerary_entry", "combine_duplicate_transactions",
        "connect_email", "create_trip", "delete_category", "delete_transaction", "delete_trip",
        "delete_wallet", "draft_training_plan", "edit_transaction", "email_status",
        "energy_estimate", "explain_category", "find_duplicates", "find_exercise", "find_ideas",
        "find_likely_moves", "find_places", "find_transactions", "flight_prices", "flight_status",
        "forward_email",
        "keep_plan_fresh", "label_trip_day", "last_time", "list_bills", "list_categories",
        "list_category_rules", "list_ious", "list_split_habits", "list_subscriptions",
        "list_trips", "list_wallets", "load_skill", "log_expense", "log_move",
        "log_receipt_expense", "mark_as_move", "mark_bill_paid", "merge_category",
        "money_history", "place_info", "plan_record", "product_prices",
        "record_income", "record_trade", "remove_bill", "remove_budget", "remove_category_rule",
        "remove_from_itinerary", "remove_from_trip", "remove_pay_schedule",
        "remove_split_habit", "rename_category", "research_plan", "research_to_trip",
        "research_trip", "restore_transaction", "set_budget", "set_category_rule",
        "set_market_alerts", "set_pay_schedule", "set_split_habit", "set_timezone",
        "set_usual_card", "set_usual_salary", "set_voice", "settle_up", "show",
        "show_dividends", "show_pay_schedule", "show_plan", "show_voice", "show_watchlist",
        "snooze_bill", "spending_summary", "split_bill", "split_trip_costs", "stock_levels",
        "suggest_adjustments",
        "test_email_setup", "they_paid", "trade_history", "transaction_updates",
        "undo_last_change", "undo_last_meal", "undo_last_set", "unwatch_stock",
        "update_health_profile", "update_trip", "update_wallet", "watch_stock", "web_search",
        "weekly_volume", "what_moved_today", "workout_history",
    }
)  # fmt: skip


def is_classified(tool: str) -> bool:
    """Whether the catalog has decided about this tool (opens a view, or none)."""
    return tool in SURFACING or tool in NON_SURFACING


def surfaced(tool: str, args: Mapping[str, object] | None = None) -> ViewKind | None:
    """The view a call to ``tool`` opens: its mapping (``query_ledger`` only when grouped by
    category: any other ledger question has no view yet), or for ``show`` the view it names.
    None when it opens nothing (or the view it names isn't in the catalog)."""
    if tool == "query_ledger":  # only an answer grouped by category is "where the money went"
        return SURFACING[tool] if (args or {}).get("group_by") == "category" else None
    if tool == "show":
        try:
            return ViewKind(str((args or {}).get("view")))
        except ValueError:
            return None
    return SURFACING.get(tool)


def live(view: ViewKind) -> bool:
    return CATALOG[view].status is ViewStatus.LIVE
