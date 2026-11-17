"""The panel registry (ADR 0001): which tool opens which panel, and what its params say."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from nexus.agent import panels, progress
from nexus.agent.panels import (
    NON_SURFACING,
    SURFACING,
    VERSION,
    PanelKind,
    PanelRef,
    budgets_panel,
    month_outlook_panel,
    opened_by,
    period_label,
    transactions_panel,
    trip_budget_panel,
)
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools

EN = "\N{EN DASH}"  # a range: 1-31 Oct
TODAY = date(2026, 11, 15)
TRIP = UUID("6f1f4a52-5c0e-4a53-9a43-1d3f2b7c9e10")
CATEGORY = UUID("0b8e5c3d-7a41-4f6b-8d52-9c1e3a7f4b20")


# --- the registry ---------------------------------------------------------------------------


def test_every_tool_is_classified_exactly_once() -> None:
    tools = set(build_tools(SkillLibrary.load().body))
    unclassified = tools - set(SURFACING) - NON_SURFACING
    assert not unclassified, f"decide whether these open a panel: {sorted(unclassified)}"
    assert not set(SURFACING) & NON_SURFACING, "a tool is both surfacing and not"


def test_the_registry_names_no_tool_that_does_not_exist() -> None:
    tools = set(build_tools(SkillLibrary.load().body))
    assert not (set(SURFACING) | NON_SURFACING) - tools


def test_the_four_kinds_and_their_tools() -> None:
    assert SURFACING == {
        "month_outlook": PanelKind.MONTH_OUTLOOK,
        "list_budgets": PanelKind.BUDGETS,
        "find_transactions": PanelKind.TRANSACTIONS,
        "query_ledger": PanelKind.TRANSACTIONS,
        "trip_status": PanelKind.TRIP_BUDGET,
    }
    assert {k.value for k in PanelKind} == {
        "finance.month_outlook",
        "finance.budgets",
        "finance.transactions",
        "travel.trip_budget",
    }
    assert VERSION == 1


def test_writes_and_lookups_open_nothing() -> None:
    for tool in ("log_expense", "set_budget", "create_trip", "calculate", "web_search"):
        assert tool in NON_SURFACING
        assert panels.is_classified(tool)
    assert not panels.is_classified("some_new_tool")


def test_a_tool_may_only_open_the_kind_the_registry_gives_it() -> None:
    outlook = month_outlook_panel(date(2026, 11, 1))
    assert opened_by("month_outlook", outlook)
    assert not opened_by("list_budgets", outlook)
    assert not opened_by("log_expense", outlook)
    ledger = transactions_panel(today=TODAY)
    assert ledger is not None
    assert opened_by("find_transactions", ledger) and opened_by("query_ledger", ledger)


# --- params and topics ----------------------------------------------------------------------


def test_month_outlook_params_and_topic() -> None:
    panel = month_outlook_panel(date(2026, 11, 1))
    assert panel.kind is PanelKind.MONTH_OUTLOOK
    assert panel.params == {"month": "2026-11"}
    assert panel.panel_id == "finance.month_outlook"
    assert panel.topic == "your outlook for November 2026"


def test_budgets_params_and_topic() -> None:
    panel = budgets_panel(date(2026, 11, 15))  # any day of the month
    assert panel.params == {"month": "2026-11"}
    assert panel.panel_id == "finance.budgets"
    assert panel.topic == "your budgets for November 2026"


def test_a_trip_panel_is_keyed_by_the_resolved_trip_id() -> None:
    panel = trip_budget_panel(TRIP, "Japan")
    assert panel.params == {"trip_id": str(TRIP)}
    assert panel.panel_id == f"travel.trip_budget:{TRIP}"
    assert panel.topic == "the Japan trip's money"


def test_transactions_params_are_named_as_the_web_endpoint_names_them() -> None:
    panel = transactions_panel(
        today=TODAY,
        start=date(2026, 10, 1),
        end=date(2026, 10, 31),
        direction="out",
        category_id=CATEGORY,
        category_name="Dining Out",
        search="grab",
        source="photo",
        include_deleted=True,
    )
    assert panel is not None
    assert panel.params == {
        "direction": "out",
        "start": "2026-10-01",
        "end": "2026-10-31",
        "category_id": str(CATEGORY),
        "search": "grab",
        "source": "photo",
        "include_deleted": True,
    }
    assert panel.panel_id == "finance.transactions"
    assert panel.topic == f"Dining Out, “grab”, 1{EN}31 Oct"


def test_transactions_params_include_only_what_applies() -> None:
    panel = transactions_panel(today=TODAY)
    assert panel is not None
    assert panel.params == {}
    assert panel.topic == "Transactions"
    only_dates = transactions_panel(today=TODAY, start=date(2026, 11, 1), end=date(2026, 11, 15))
    assert only_dates is not None
    assert only_dates.params == {"start": "2026-11-01", "end": "2026-11-15"}
    assert "user_id" not in only_dates.params


def test_the_transactions_topic_reads_like_the_example() -> None:
    panel = transactions_panel(
        today=TODAY,
        start=date(2026, 10, 1),
        end=date(2026, 10, 31),
        direction="out",
        category_id=CATEGORY,
        category_name="Dining Out",
    )
    assert panel is not None
    assert panel.topic == f"Dining Out, 1{EN}31 Oct"


def test_the_transactions_topic_names_the_direction_when_nothing_else_does() -> None:
    spent = transactions_panel(today=TODAY, direction="out", start=date(2026, 11, 1))
    assert spent is not None and spent.topic == "Spending, from 1 Nov"
    got = transactions_panel(today=TODAY, direction="in", category_name="Salary")
    assert got is not None and got.topic == "Money in, Salary"
    moved = transactions_panel(today=TODAY, direction="move")
    assert moved is not None and moved.topic == "Transfers"
    none = transactions_panel(today=TODAY, uncategorized=True, direction="out")
    assert none is not None and none.params == {"direction": "out", "uncategorized": True}
    assert none.topic == "Uncategorised"


def test_a_search_the_endpoint_would_refuse_opens_no_panel() -> None:
    assert transactions_panel(today=TODAY, search="x" * 101) is None
    assert transactions_panel(today=TODAY, search="x" * 100) is not None
    blank = transactions_panel(today=TODAY, search="   ")
    assert blank is not None and "search" not in blank.params


@pytest.mark.parametrize(
    ("start", "end", "label"),
    [
        (None, None, None),
        (date(2026, 10, 1), date(2026, 10, 31), f"1{EN}31 Oct"),
        (date(2026, 10, 3), date(2026, 10, 3), "3 Oct"),
        (date(2026, 9, 28), date(2026, 10, 3), f"28 Sep {EN} 3 Oct"),
        (date(2026, 11, 1), None, "from 1 Nov"),
        (None, date(2026, 10, 31), "to 31 Oct"),
        (date(2025, 10, 1), date(2025, 10, 31), f"1{EN}31 Oct 2025"),
        (date(2025, 12, 28), date(2026, 1, 3), f"28 Dec 2025 {EN} 3 Jan 2026"),
    ],
)
def test_a_period_in_few_words(start: date | None, end: date | None, label: str | None) -> None:
    assert period_label(start, end, TODAY) == label


# --- the event ------------------------------------------------------------------------------


def test_the_event_body() -> None:
    as_of = datetime(2026, 11, 15, 6, 2, tzinfo=UTC)
    body = trip_budget_panel(TRIP, "Japan").event("web:abc:1", as_of)
    assert body == {
        "panel_id": f"travel.trip_budget:{TRIP}",
        "kind": "travel.trip_budget",
        "version": 1,
        "params": {"trip_id": str(TRIP)},
        "topic": "the Japan trip's money",
        "as_of": "2026-11-15T06:02:00+00:00",
        "message_id": "web:abc:1",
    }


def test_the_event_copies_its_params() -> None:
    panel = budgets_panel(date(2026, 11, 1))
    body = panel.event("ref", datetime(2026, 11, 15, tzinfo=UTC))
    body["params"]["month"] = "2000-01"
    assert panel.params == {"month": "2026-11"}


# --- the panel sink -------------------------------------------------------------------------


async def test_a_panel_sink_hears_the_panels_of_the_turn_it_watches() -> None:
    heard: list[PanelRef] = []

    async def sink(panel: PanelRef) -> None:
        heard.append(panel)

    panel = budgets_panel(date(2026, 11, 1))
    await progress.report_panel(panel)  # no sink: nothing happens
    with progress.watching(None, panels=sink):
        await progress.report_panel(panel)
    await progress.report_panel(panel)  # the turn is over
    assert heard == [panel]


async def test_a_panel_sink_that_breaks_does_not_stop_the_turn() -> None:
    async def broken(panel: PanelRef) -> None:
        raise RuntimeError("the screen is gone")

    with progress.watching(None, panels=broken):
        await progress.report_panel(budgets_panel(date(2026, 11, 1)))
