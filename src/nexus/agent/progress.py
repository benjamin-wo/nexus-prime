"""What a chat turn is doing, for a screen that shows it, and a way to stop it early.

A turn reports each tool as it starts and finishes, as a short plain label ("Logging the
expense"). The label comes from the tool's name alone: never from its arguments or results,
so it can't carry an id, an amount or someone's name. The channel that wants the steps
passes a sink to ``AgentService.handle_text``; the graph reports to whichever sink the
running turn has (a context variable, so the graph's own state and replies are untouched).
With no sink, reporting does nothing: Telegram and every other caller never notice.

Views (ADR 0005) are kept on a note of their own for the turn (``TurnViews``): a view
opened by a tool that answered, or chosen with ``present``, is added to it; the same view
twice is one, and a turn holds at most ``MAX_PER_TURN``. When the turn ends the service
sends the final list to the view sink (``ViewSink``, beside the step sink) and keeps it with
the reply. With views off there is no note and nothing is added.

A stop request is read the same way: the graph asks ``stop_requested()`` between steps.
"""

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Literal

from nexus.agent.views import MAX_PER_TURN, ViewRef

log = logging.getLogger(__name__)

type StepState = Literal["running", "done"]


@dataclass(frozen=True)
class Step:
    """One thing the turn is doing: ``label`` is fit to show the user as it is."""

    label: str
    state: StepState


type StepSink = Callable[[Step], Awaitable[None]]

type ViewSink = Callable[[ViewRef], Awaitable[None]]

GENERIC = "Working on it"

# Plain words for what each tool does, in the present tense. A tool missing here is
# labelled GENERIC, never by its internal name.
LABELS: dict[str, str] = {
    # The ledger
    "log_expense": "Logging the expense",
    "log_receipt_expense": "Logging the receipt",
    "log_move": "Recording the transfer",
    "record_income": "Recording the income",
    "find_transactions": "Looking through your transactions",
    "edit_transaction": "Updating the transaction",
    "delete_transaction": "Deleting the transaction",
    "restore_transaction": "Restoring the transaction",
    "undo_last_change": "Undoing the last change",
    "find_duplicates": "Looking for duplicates",
    "combine_duplicate_transactions": "Combining the duplicates",
    "mark_as_move": "Marking it as a transfer",
    "find_likely_moves": "Looking for transfers between your accounts",
    "spending_summary": "Adding up your spending",
    "query_ledger": "Checking your ledger",
    "cash_flow": "Working out your cash flow",
    "money_history": "Working out your savings by month",
    "transaction_updates": "Checking what changed",
    "what_moved_today": "Checking what moved today",
    # Categories and wallets
    "list_categories": "Checking your categories",
    "add_category": "Adding the category",
    "rename_category": "Renaming the category",
    "delete_category": "Deleting the category",
    "merge_category": "Merging the categories",
    "list_category_rules": "Checking your category rules",
    "set_category_rule": "Saving the category rule",
    "remove_category_rule": "Removing the category rule",
    "explain_category": "Working out why it was filed there",
    "list_wallets": "Checking your accounts",
    "add_wallet": "Adding the account",
    "update_wallet": "Updating the account",
    "set_usual_card": "Saving your usual card",
    "delete_wallet": "Removing the account",
    # Splitting and owing
    "split_bill": "Splitting the bill",
    "list_ious": "Checking who owes what",
    "they_paid": "Recording the payment",
    "settle_up": "Settling up",
    "set_split_habit": "Saving how you usually split",
    "list_split_habits": "Checking how you usually split",
    "remove_split_habit": "Forgetting a split habit",
    "split_trip_costs": "Splitting the trip costs",
    # Budgets, bills and pay
    "set_budget": "Setting the budget",
    "list_budgets": "Checking your budgets",
    "remove_budget": "Removing the budget",
    "add_bill": "Adding the bill",
    "list_bills": "Checking your bills",
    "mark_bill_paid": "Marking the bill as paid",
    "snooze_bill": "Snoozing the bill",
    "remove_bill": "Removing the bill",
    "list_subscriptions": "Checking your subscriptions",
    "set_pay_schedule": "Saving your pay schedule",
    "show_pay_schedule": "Checking your pay schedule",
    "remove_pay_schedule": "Removing your pay schedule",
    "set_usual_salary": "Saving your usual salary",
    # Trips
    "create_trip": "Creating the trip",
    "update_trip": "Updating the trip",
    "delete_trip": "Deleting the trip",
    "list_trips": "Checking your trips",
    "trip_status": "Checking the trip",
    "add_to_trip": "Adding to the trip",
    "remove_from_trip": "Removing from the trip",
    "add_to_itinerary": "Adding to the itinerary",
    "add_trip_todo": "Adding to the trip to-do list",
    "add_trip_cover": "Setting the trip photo",
    "change_itinerary_entry": "Changing the itinerary",
    "label_trip_day": "Labelling the day",
    "remove_from_itinerary": "Removing from the itinerary",
    "research_trip": "Researching the trip",
    "research_to_trip": "Adding what I found to the trip",
    # Looking things up
    "web_search": "Looking that up on the web",
    "find_places": "Finding places",
    "find_ideas": "Looking for ideas",
    "place_info": "Checking the place",
    "flight_prices": "Checking flight prices",
    "flight_status": "Checking the flight",
    "product_prices": "Comparing prices",
    # Investments
    "show_portfolio": "Checking your portfolio",
    "record_trade": "Recording the trade",
    "trade_history": "Looking through your trades",
    "show_dividends": "Checking your dividends",
    "stock_levels": "Checking the price levels",
    "set_market_alerts": "Setting the market alerts",
    "research_plan": "Researching your plan",
    "show_plan": "Checking your plan",
    "keep_plan_fresh": "Updating your plan",
    "plan_record": "Saving to your plan",
    "show_watchlist": "Checking your watchlist",
    "watch_stock": "Adding to your watchlist",
    "unwatch_stock": "Removing from your watchlist",
    # Email, settings, and the rest
    "answer_email": "Reading the email",
    "connect_email": "Setting up email",
    "forward_email": "Setting up email forwarding",
    "test_email_setup": "Testing your email setup",
    "email_status": "Checking your email setup",
    "set_timezone": "Saving your time zone",
    "set_voice": "Changing how I talk",
    "show_voice": "Checking how I talk",
    "load_skill": "Getting ready",
    "present": "Putting it on screen",
}


def label_for(tool: str) -> str:
    """The label to show for a tool: from the table, else a generic one. Never the name."""
    return LABELS.get(tool, GENERIC)


@dataclass
class TurnViews:
    """The views one turn has put on screen so far, by view id and in the order first seen.
    The focus is the latest ``present`` with focus true, else the first view."""

    refs: dict[str, ViewRef] = field(default_factory=dict)
    chosen: str | None = None  # the view id of the latest present with focus true

    def add(self, ref: ViewRef, *, presented: bool = False) -> bool:
        """Note a view; False when the turn is full (a view already in is updated, never
        refused). A view seen again keeps its place and takes the newer params and figures."""
        if ref.view_id not in self.refs and len(self.refs) >= MAX_PER_TURN:
            return False
        self.refs[ref.view_id] = ref
        if presented and ref.focus:
            self.chosen = ref.view_id
        return True

    def final(self) -> list[ViewRef]:
        """The turn's views with exactly one in focus."""
        if not self.refs:
            return []
        focus = self.chosen if self.chosen in self.refs else next(iter(self.refs))
        return [replace(r, focus=r.view_id == focus) for r in self.refs.values()]


_sink: ContextVar[StepSink | None] = ContextVar("turn_step_sink", default=None)
_view_sink: ContextVar[ViewSink | None] = ContextVar("turn_view_sink", default=None)
_turn_views: ContextVar[TurnViews | None] = ContextVar("turn_views", default=None)
_stop: ContextVar[Callable[[], bool] | None] = ContextVar("turn_stop", default=None)


@contextmanager
def watching(
    sink: StepSink | None,
    stop: Callable[[], bool] | None = None,
    *,
    views: bool = False,
    on_view: ViewSink | None = None,
) -> Iterator[None]:
    """For the turn run inside: report its steps to ``sink`` and ask ``stop`` whether the
    user wants it ended. With ``views`` the turn keeps a note of its views (see
    ``turn_views``); ``on_view`` is told of each once the turn ends (see ``finish_views``)."""
    steps = _sink.set(sink)
    stopper = _stop.set(stop)
    # One mutable note, not a value per node: LangGraph runs each node in a copy of this
    # context, and the copies must all add to the same turn's views.
    noted = _turn_views.set(TurnViews() if views else None)
    shown = _view_sink.set(on_view)
    try:
        yield
    finally:
        _view_sink.reset(shown)
        _turn_views.reset(noted)
        _stop.reset(stopper)
        _sink.reset(steps)


def turn_views() -> TurnViews | None:
    """The running turn's views so far; None when the turn keeps none (views are off)."""
    return _turn_views.get()


async def finish_views() -> list[ViewRef]:
    """The turn's final views, each told to the view sink in order. Call it inside
    ``watching``, once the graph has run. Never raises on a sink that fails."""
    noted = _turn_views.get()
    final = noted.final() if noted is not None else []
    sink = _view_sink.get()
    if sink is not None:
        for view in final:
            try:
                await sink(view)
            except Exception:
                log.exception("could not report a view")
    return final


async def report(tool: str, state: StepState) -> None:
    """Tell the turn's sink a tool started or finished. Never raises: a screen that can't
    be told must not stop the work."""
    sink = _sink.get()
    if sink is None:
        return
    try:
        await sink(Step(label_for(tool), state))
    except Exception:
        log.exception("could not report a step")


def stop_requested() -> bool:
    """Whether the user asked to stop the running turn."""
    stop = _stop.get()
    return stop is not None and stop()
