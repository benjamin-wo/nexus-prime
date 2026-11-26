"""The view catalog (ADR 0005): which tool opens which view, what its params say, and the
headline figures its summary carries. Every name and figure here is made up."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.agent.tools.body import ShowArgs
from nexus.agent.view_links import VIEWS
from nexus.agent.views import (
    CATALOG,
    NON_SURFACING,
    SURFACING,
    VERSION,
    ViewKind,
    ViewStatus,
    is_classified,
    live,
    surfaced,
)
from nexus.domain.money import Money


def sgd(amount: str) -> Money:
    return Money(Decimal(amount), "SGD")


def json(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "SGD"}


def summary(kind: ViewKind, result: Any) -> dict[str, Any] | None:
    return CATALOG[kind].summary(result)


# --- the catalog ----------------------------------------------------------------------------


def test_every_registered_tool_is_surfacing_or_not() -> None:
    tools = set(build_tools(SkillLibrary.load().body))
    unclassified = tools - set(SURFACING) - NON_SURFACING
    assert not unclassified, f"decide whether these open a view: {sorted(unclassified)}"
    assert not set(SURFACING) & NON_SURFACING, "a tool is both surfacing and not"


def test_the_catalog_names_no_tool_that_does_not_exist() -> None:
    tools = set(build_tools(SkillLibrary.load().body))
    assert not (set(SURFACING) | NON_SURFACING) - tools


def test_the_first_views_and_their_tools() -> None:
    assert SURFACING == {
        "month_outlook": ViewKind.MONTH_OUTLOOK,
        "list_budgets": ViewKind.BUDGETS,
        "query_ledger": ViewKind.SPENDING,
        "trip_status": ViewKind.TRIP_BUDGET,
        "show_portfolio": ViewKind.PORTFOLIO,
        "food_today": ViewKind.TODAY,
        "log_food": ViewKind.TODAY,
        "log_photo_meal": ViewKind.TODAY,
        "log_weight": ViewKind.WEIGHT_TREND,
        "todays_workout": ViewKind.WORKOUT,
        "suggest_workout": ViewKind.WORKOUT,
        "log_sets": ViewKind.WORKOUT,
        "finish_workout": ViewKind.WORKOUT,
        "personal_records": ViewKind.RECORDS,
    }
    assert VERSION == 1


def test_every_view_has_a_spec_and_only_the_unbuilt_are_planned() -> None:
    assert set(CATALOG) == set(ViewKind)
    for kind, spec in CATALOG.items():
        assert spec.name is kind
        assert spec.description.strip()
        assert spec.path.startswith("/")
        assert spec.version == VERSION
    planned = {k for k, s in CATALOG.items() if s.status is ViewStatus.PLANNED}
    assert planned == {ViewKind.TRANSACTIONS, ViewKind.AFFORDABILITY}
    assert not any(live(SURFACING[t]) is False for t in SURFACING)


def test_writes_and_lookups_open_nothing() -> None:
    for tool in ("log_expense", "set_budget", "create_trip", "calculate", "web_search"):
        assert tool in NON_SURFACING
        assert is_classified(tool)
    assert not is_classified("some_new_tool")


def test_show_opens_the_view_it_names() -> None:
    assert surfaced("show", {"view": "health.weight_trend"}) is ViewKind.WEIGHT_TREND
    assert surfaced("show", {"view": "nope"}) is None
    assert surfaced("show", {}) is None
    assert surfaced("month_outlook") is ViewKind.MONTH_OUTLOOK
    assert surfaced("log_expense") is None
    assert surfaced("query_ledger", {"group_by": "category"}) is ViewKind.SPENDING
    assert surfaced("query_ledger", {"group_by": "merchant"}) is None
    assert surfaced("query_ledger", {}) is None
    assert surfaced("spending_summary") is None


# --- view_links reads the catalog -----------------------------------------------------------


def test_view_links_are_the_catalog_s_pages() -> None:
    assert {k: v.path for k, v in VIEWS.items()} == {
        "health.today": "/health",
        "health.weight_trend": "/health",
        "health.workout": "/health/gym",
        "health.records": "/health/gym/history",
        "finance.month_outlook": "/accounting",
        "finance.budgets": "/accounting/budgets",
        "travel.trips": "/travel",
        "invest.portfolio": "/investment",
    }
    for name, shown in VIEWS.items():
        assert shown.path == CATALOG[ViewKind(name)].path
        assert shown.line.endswith(".") and shown.button.startswith("Open ")


def test_the_show_tool_offers_exactly_the_views_view_links_has() -> None:
    offered = set(get_args(ShowArgs.model_fields["view"].annotation))
    assert offered == set(VIEWS)


# --- params ---------------------------------------------------------------------------------


def test_params_are_checked_against_the_spec() -> None:
    month = CATALOG[ViewKind.MONTH_OUTLOOK]
    assert month.validate({"month": "2026-11"}).model_dump() == {"month": "2026-11"}
    for bad in ({"month": "2026-13"}, {"month": "November"}, {}):
        with pytest.raises(ValidationError):
            month.validate(bad)
    assert CATALOG[ViewKind.WORKOUT].validate({}).model_dump() == {
        "state": "open",
        "suggestion_id": None,
    }
    with pytest.raises(ValidationError):
        CATALOG[ViewKind.WORKOUT].validate({"state": "done"})


def test_params_never_carry_a_user_id_or_anything_else_unnamed() -> None:
    for kind, spec in CATALOG.items():
        assert "user_id" not in spec.params.model_fields, kind
        with pytest.raises(ValidationError):
            spec.validate({"user_id": "1d2c3b4a"})


def test_the_view_id_is_the_name_unless_the_view_has_an_entity() -> None:
    month = CATALOG[ViewKind.BUDGETS]
    assert month.view_id(month.validate({"month": "2026-10"})) == "finance.budgets"
    trip = CATALOG[ViewKind.TRIP_BUDGET]
    params = trip.validate({"trip_id": "6f1f4a52"})
    assert trip.view_id(params) == "travel.trip_budget:6f1f4a52"


def test_captions_are_worded_from_the_params() -> None:
    assert (
        CATALOG[ViewKind.MONTH_OUTLOOK].caption(
            CATALOG[ViewKind.MONTH_OUTLOOK].validate({"month": "2026-11"})
        )
        == "Your outlook for November 2026"
    )
    day = CATALOG[ViewKind.TODAY]
    assert day.caption(day.validate({})) == "Your day"
    assert day.caption(day.validate({"day": "2026-11-02"})) == "Your day, 2 Nov"
    work = CATALOG[ViewKind.WORKOUT]
    assert work.caption(work.validate({"state": "suggested"})) == "Your suggested workout"


# --- summaries: figures from code -----------------------------------------------------------


def test_the_outlook_summary_is_its_headline_figures() -> None:
    outlook = SimpleNamespace(
        status="current",
        received=sgd("5000.00"),
        spent=sgd("2100.50"),
        overall=sgd("1400.00"),
        headroom=sgd("1400.00"),
        shortfall=sgd("0.00"),
    )
    assert summary(ViewKind.MONTH_OUTLOOK, outlook) == {
        "status": "current",
        "received": json("5000.00"),
        "spent": json("2100.50"),
        "overall": json("1400.00"),
        "headroom": json("1400.00"),
        "shortfall": json("0.00"),
    }


def _status(name: str, spent: str, limit: str) -> Any:
    return SimpleNamespace(
        name=name,
        spent=sgd(spent),
        budget=SimpleNamespace(limit=sgd(limit)),
        percent=int(Decimal(spent) * 100 // Decimal(limit)),
    )


def test_the_budgets_summary_names_the_most_used_first() -> None:
    statuses = [
        _status("Groceries", "200.00", "600.00"),
        _status("Dining Out", "450.00", "400.00"),
        *(_status(f"b{n}", "1.00", "100.00") for n in range(5)),
    ]
    out = summary(ViewKind.BUDGETS, statuses)
    assert out is not None
    assert (out["count"], out["over"]) == (7, 1)
    assert len(out["budgets"]) == 5
    assert out["budgets"][0] == {
        "name": "Dining Out",
        "spent": json("450.00"),
        "limit": json("400.00"),
        "percent": 112,
    }
    assert summary(ViewKind.BUDGETS, []) == {"count": 0, "over": 0, "budgets": []}


def test_the_spending_summary_is_the_total_and_top_categories() -> None:
    result = SimpleNamespace(
        out=SimpleNamespace(total=sgd("812.40"), count=31),
        spending_by_category=[
            SimpleNamespace(category_name="Dining Out", total=sgd("300.00")),
            SimpleNamespace(category_name=None, total=sgd("20.00")),
        ],
    )
    assert summary(ViewKind.SPENDING, result) == {
        "spent": json("812.40"),
        "count": 31,
        "categories": [
            {"name": "Dining Out", "total": json("300.00")},
            {"name": "Uncategorised", "total": json("20.00")},
        ],
    }


def test_the_trip_summary_is_its_money() -> None:
    trip = SimpleNamespace(
        trip=SimpleNamespace(budget=sgd("3000.00")),
        spending=SimpleNamespace(spent=sgd("1200.00"), left=sgd("1800.00"), percent=40),
        to_spend=sgd("1500.00"),
    )
    assert summary(ViewKind.TRIP_BUDGET, trip) == {
        "budget": json("3000.00"),
        "spent": json("1200.00"),
        "left": json("1800.00"),
        "percent": 40,
        "to_spend": json("1500.00"),
    }
    bare = SimpleNamespace(
        trip=SimpleNamespace(budget=None),
        spending=SimpleNamespace(spent=sgd("80.00"), left=None, percent=None),
        to_spend=None,
    )
    out = summary(ViewKind.TRIP_BUDGET, bare)
    assert out is not None and out["budget"] is None and out["spent"] == json("80.00")


def test_the_portfolio_summary_is_its_totals() -> None:
    valued = SimpleNamespace(
        rows=[object(), object()],
        value=sgd("12000.00"),
        cost=sgd("10000.00"),
        gain=sgd("2000.00"),
        day_change=None,
        as_of=date(2026, 9, 25),
    )
    assert summary(ViewKind.PORTFOLIO, valued) == {
        "holdings": 2,
        "value": json("12000.00"),
        "cost": json("10000.00"),
        "gain": json("2000.00"),
        "day_change": None,
        "as_of": "2026-09-25",
    }


# Health summaries state numbers and which way a trend went, never what they mean.


def _food(hidden: bool) -> Any:
    point = SimpleNamespace(kcal=Decimal("1432.6"), protein_g=Decimal("71.2"))
    return SimpleNamespace(
        day=date(2026, 9, 28),
        entries=[object(), object()],
        hidden=hidden,
        totals=SimpleNamespace(point=point),
        targets=SimpleNamespace(kcal=Decimal("2100")),
    )


def test_the_day_summary_has_the_logged_figures_and_no_verdict() -> None:
    out = summary(ViewKind.TODAY, SimpleNamespace(food=_food(False), workout=None))
    assert out == {
        "day": "2026-09-28",
        "meals": 2,
        "kcal": "1433",
        "protein_g": "71",
        "kcal_target": "2100",
    }
    workout = SimpleNamespace(in_progress=None, routine=None)
    both = summary(ViewKind.TODAY, SimpleNamespace(food=_food(False), workout=workout))
    assert both is not None and both["workout"] == {"state": "rest"}


def test_numbers_free_mode_leaves_out_every_number() -> None:
    out = summary(ViewKind.TODAY, SimpleNamespace(food=_food(True), workout=None))
    assert out == {"day": "2026-09-28", "meals": 2}
    weight = SimpleNamespace(
        hidden=True,
        trend_words="Your weight is trending down.",
        trend_kg=None,
        rate=None,
        points=[],
    )
    assert summary(ViewKind.WEIGHT_TREND, weight) == {
        "hidden": True,
        "trend_words": "Your weight is trending down.",
    }


def test_the_weight_summary_is_the_trend_not_a_reading_of_it() -> None:
    weight = SimpleNamespace(
        hidden=False,
        trend_words="Your trend is down about 0.4 kg a week.",
        trend_kg=Decimal("81.34"),
        rate=(Decimal("-0.42"), Decimal("-0.5")),
        points=[object()] * 9,
    )
    out = summary(ViewKind.WEIGHT_TREND, weight)
    assert out == {
        "hidden": False,
        "trend_words": "Your trend is down about 0.4 kg a week.",
        "trend_kg": "81.3",
        "kg_a_week": "-0.4",
        "weigh_ins": 9,
    }


def test_the_workout_summary_for_each_state() -> None:
    routine = SimpleNamespace(name="Push", slots=[1, 2, 3])
    started = datetime(2026, 9, 28, 18, 0, tzinfo=UTC)
    planned = SimpleNamespace(in_progress=None, routine=routine)
    assert summary(ViewKind.WORKOUT, planned) == {
        "state": "planned",
        "routine": "Push",
        "exercises": 3,
    }
    opened = SimpleNamespace(in_progress=SimpleNamespace(started_at=started), routine=routine)
    assert summary(ViewKind.WORKOUT, opened) == {
        "state": "open",
        "started_at": "2026-09-28T18:00:00+00:00",
    }


def test_the_records_summary_names_the_lifts() -> None:
    bench = SimpleNamespace(
        exercise=SimpleNamespace(name="Bench Press"),
        heaviest=SimpleNamespace(weight_kg=Decimal("80")),
        e1rm_kg=Decimal("93.33"),
        sessions=4,
    )
    assert summary(ViewKind.RECORDS, [bench]) == {
        "records": [
            {"exercise": "Bench Press", "heaviest_kg": "80.0", "e1rm_kg": "93.3", "sessions": 4}
        ]
    }
    assert summary(ViewKind.RECORDS, []) == {"records": []}


# --- the turn's views and the Telegram button (ADR 0005) -----------------------------------


def _ref(kind: ViewKind, focus: bool = False, **params: Any) -> Any:
    from nexus.agent.views import ViewRef

    spec = CATALOG[kind]
    return ViewRef(kind, spec.view_id(spec.validate(params)), params, focus, "Caption", None)


def test_a_turn_dedupes_by_view_id_caps_at_three_and_keeps_one_focus() -> None:
    from nexus.agent.progress import TurnViews

    turn = TurnViews()
    assert turn.add(_ref(ViewKind.MONTH_OUTLOOK, month="2026-09"))
    assert turn.add(_ref(ViewKind.MONTH_OUTLOOK, month="2026-08"))  # same id: updated in place
    assert turn.add(_ref(ViewKind.BUDGETS, month="2026-08"))
    assert turn.add(_ref(ViewKind.PORTFOLIO))
    assert not turn.add(_ref(ViewKind.TODAY))  # a fourth is refused
    assert turn.add(_ref(ViewKind.PORTFOLIO))  # one already in is never refused
    final = turn.final()
    assert [(v.kind, v.focus) for v in final] == [
        (ViewKind.MONTH_OUTLOOK, True),
        (ViewKind.BUDGETS, False),
        (ViewKind.PORTFOLIO, False),
    ]
    assert final[0].params == {"month": "2026-08"}
    turn.add(_ref(ViewKind.BUDGETS, focus=True, month="2026-08"), presented=True)
    assert [v.focus for v in turn.final()] == [False, True, False]


def test_present_names_its_view_for_the_metrics_like_show_does() -> None:
    assert surfaced("present", {"view": "finance.budgets"}) is ViewKind.BUDGETS
    assert surfaced("present", {"view": "nothing"}) is None


def test_a_reply_with_views_gets_one_open_in_nexus_button_for_the_focus_view() -> None:
    from nexus.agent.view_links import open_in_nexus

    views = [_ref(ViewKind.MONTH_OUTLOOK, month="2026-09"), _ref(ViewKind.PORTFOLIO, True)]
    assert open_in_nexus(views, "https://nexus.test/") == (
        "Open in Nexus",
        "url:https://nexus.test/investment",
    )
    assert open_in_nexus(views, None) is None
    assert open_in_nexus([], "https://nexus.test") is None
