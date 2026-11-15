"""Domain panels (ADR 0001): which tools open a panel beside the web chat, and what it holds.

A panel is a hand-built view the web app already has (the month outlook, the budgets, the
ledger, a trip's money). Prime never asks for one: it opens when a domain tool the agent
called comes back with an answer. This module is the one place that says which tool opens
which kind, and every other tool is listed as opening none. A test fails for a tool that is
in neither list, so a new tool cannot be added without deciding.

A tool reports what it *resolved* ("Japan" became a trip id, "this month" became 2026-11),
so the panel shows what the answer was built from. Params are the query the web endpoint
takes, named as that endpoint names them, and never a user id: the signed-in user is the
tenant. The ``topic`` is worded here from the same values, never by the model.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

# The shape of every panel's params and event. Bump a kind's version only when a param is
# renamed or removed; adding one is not a change.
VERSION = 1

# What the web endpoint accepts for a search (``GET /api/transactions``, ``search``).
MAX_SEARCH = 100

EN_DASH = "\u2013"  # a range of days: 1-31 Oct
DASH = f" {EN_DASH} "  # between two dates: 28 Sep - 3 Oct
type Params = dict[str, str | bool]


class PanelKind(StrEnum):
    MONTH_OUTLOOK = "finance.month_outlook"
    BUDGETS = "finance.budgets"
    TRANSACTIONS = "finance.transactions"
    TRIP_BUDGET = "travel.trip_budget"


# The tools that open a panel, and the kind each opens.
SURFACING: dict[str, PanelKind] = {
    "month_outlook": PanelKind.MONTH_OUTLOOK,
    "list_budgets": PanelKind.BUDGETS,
    "find_transactions": PanelKind.TRANSACTIONS,
    "query_ledger": PanelKind.TRANSACTIONS,
    "trip_status": PanelKind.TRIP_BUDGET,
}

# Every other tool. Writes open nothing in v1; neither do lookups, the calculator, a
# currency check or the tools that read something no panel shows yet.
NON_SURFACING = frozenset(
    {
        "add_bill", "add_category", "add_to_itinerary", "add_to_trip", "add_trip_cover",
        "add_trip_todo", "add_wallet", "answer_email", "calculate", "cash_flow",
        "change_itinerary_entry", "combine_duplicate_transactions", "connect_email",
        "create_trip", "delete_category", "delete_transaction", "delete_trip", "delete_wallet",
        "edit_transaction", "email_status", "explain_category", "find_duplicates", "find_ideas",
        "find_likely_moves", "find_places", "flight_prices", "flight_status", "forward_email",
        "keep_plan_fresh", "label_trip_day", "list_bills", "list_categories",
        "list_category_rules", "list_ious", "list_split_habits", "list_subscriptions",
        "list_trips", "list_wallets", "load_skill", "log_expense", "log_move",
        "log_receipt_expense", "mark_as_move", "mark_bill_paid", "merge_category",
        "place_info", "plan_record", "product_prices", "record_income", "record_trade",
        "remove_bill", "remove_budget", "remove_category_rule", "remove_from_itinerary",
        "remove_from_trip", "remove_pay_schedule", "remove_split_habit", "rename_category",
        "research_plan", "research_to_trip", "research_trip", "restore_transaction",
        "set_budget", "set_category_rule", "set_market_alerts", "set_pay_schedule",
        "set_split_habit", "set_timezone", "set_usual_card", "set_usual_salary", "set_voice",
        "settle_up", "show_dividends", "show_pay_schedule", "show_plan", "show_portfolio",
        "show_voice", "show_watchlist", "snooze_bill", "spending_summary", "split_bill",
        "split_trip_costs", "stock_levels", "test_email_setup", "they_paid", "trade_history",
        "transaction_updates", "undo_last_change", "unwatch_stock", "update_trip",
        "update_wallet", "watch_stock", "web_search", "what_moved_today",
    }
)  # fmt: skip


def is_classified(tool: str) -> bool:
    """Whether the registry has decided about this tool (opens a panel, or none)."""
    return tool in SURFACING or tool in NON_SURFACING


@dataclass(frozen=True, slots=True)
class PanelRef:
    """One panel a tool's answer opens: its kind, the query it shows and why it opened."""

    kind: PanelKind
    params: Params
    topic: str  # for the caption: "Opened because you asked about <topic>"
    entity: str | None = None  # what tells two panels of one kind apart (a trip id)

    @property
    def panel_id(self) -> str:
        """Stable across a turn and the next: the same id updates the panel in place."""
        return f"{self.kind.value}:{self.entity}" if self.entity else self.kind.value

    def event(self, message_id: str, as_of: datetime) -> dict[str, Any]:
        """The ``panel.upsert`` event body. ``as_of`` is when the tool read the data."""
        return {
            "panel_id": self.panel_id,
            "kind": self.kind.value,
            "version": VERSION,
            "params": dict(self.params),
            "topic": self.topic,
            "as_of": as_of.isoformat(),
            "message_id": message_id,
        }


def opened_by(tool: str, ref: PanelRef) -> bool:
    """Whether the registry lets ``tool`` open this panel. The graph checks it, so a tool
    can't open a kind the registry doesn't give it."""
    return SURFACING.get(tool) is ref.kind


def month_label(month: date) -> str:
    return f"{month:%B %Y}"


def _day(d: date, today: date, *, year: bool | None = None) -> str:
    show = d.year != today.year if year is None else year
    return f"{d.day} {d:%b}" + (f" {d.year}" if show else "")


def period_label(start: date | None, end: date | None, today: date) -> str | None:
    """A date range in few words: "1-31 Oct" (with an en dash), "28 Sep - 3 Oct", "from 1 Oct".
    The year only
    when it isn't this year (or the range crosses one). None when there are no dates."""
    if start is None:
        return f"to {_day(end, today)}" if end else None
    if end is None:
        return f"from {_day(start, today)}"
    if start == end:
        return _day(start, today)
    if start.year != end.year:
        return f"{_day(start, today, year=True)}{DASH}{_day(end, today, year=True)}"
    tail = f" {end.year}" if end.year != today.year else ""
    if start.month == end.month:
        return f"{start.day}{EN_DASH}{end.day} {end:%b}{tail}"
    return f"{start.day} {start:%b}{DASH}{end.day} {end:%b}{tail}"


def month_outlook_panel(month: date) -> PanelRef:
    """The outlook for ``month``: any day of it, as the tool resolved it."""
    return PanelRef(
        PanelKind.MONTH_OUTLOOK,
        {"month": f"{month:%Y-%m}"},
        f"your outlook for {month_label(month)}",
    )


def budgets_panel(month: date) -> PanelRef:
    return PanelRef(
        PanelKind.BUDGETS, {"month": f"{month:%Y-%m}"}, f"your budgets for {month_label(month)}"
    )


def trip_budget_panel(trip_id: UUID, destination: str) -> PanelRef:
    """A trip's money, by the trip's id (never the name the user typed)."""
    return PanelRef(
        PanelKind.TRIP_BUDGET,
        {"trip_id": str(trip_id)},
        f"the {destination} trip's money",
        entity=str(trip_id),
    )


_DIRECTION_WORDS = {"out": "Spending", "in": "Money in", "move": "Transfers"}


def transactions_panel(
    *,
    today: date,
    start: date | None = None,
    end: date | None = None,
    direction: str | None = None,
    category_id: UUID | None = None,
    category_name: str | None = None,
    uncategorized: bool = False,
    search: str | None = None,
    source: str | None = None,
    include_deleted: bool = False,
) -> PanelRef | None:
    """The ledger filtered as the tool filtered it. Params carry only the filters that
    apply, named as ``GET /api/transactions`` names them. None when the filters can't be
    said to that endpoint (a search longer than it takes), so no panel rather than a wrong
    one."""
    search = (search or "").strip() or None
    if search is not None and len(search) > MAX_SEARCH:
        return None
    params: Params = {}
    if direction:
        params["direction"] = direction
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    if category_id:
        params["category_id"] = str(category_id)
    if uncategorized:
        params["uncategorized"] = True
    if search:
        params["search"] = search
    if source:
        params["source"] = source
    if include_deleted:
        params["include_deleted"] = True
    subject = [
        *([category_name] if category_name else []),
        *(["Uncategorised"] if uncategorized else []),
        *([f"“{search}”"] if search else []),
    ]
    if not subject or direction in ("in", "move"):
        subject.insert(0, _DIRECTION_WORDS.get(direction or "", "Transactions"))
    parts = [*subject, *filter(None, [period_label(start, end, today)])]
    return PanelRef(PanelKind.TRANSACTIONS, params, ", ".join(parts))
