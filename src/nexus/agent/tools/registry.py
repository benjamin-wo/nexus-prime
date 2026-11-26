"""The tool catalogue: every domain module's specs, in the order the model is offered them."""

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from nexus.agent.tools import (
    bills,
    budgets,
    categories,
    coach,
    email,
    food,
    gym,
    investments,
    ledger,
    outlook,
    pay,
    query,
    settings,
    splits,
    subscriptions,
    wallets,
)
from nexus.agent.tools.core import Args, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.trips import itinerary as trips_itinerary
from nexus.agent.tools.trips import places as trips_places
from nexus.agent.tools.trips import prep as trips_prep
from nexus.agent.tools.trips import research as trips_research
from nexus.agent.tools.trips import search as trips_search
from nexus.agent.tools.trips import trip as trips_trip
from nexus.agent.tools.trips import trip_money as trips_trip_money
from nexus.application import mistakes
from nexus.domain.errors import NexusError
from nexus.domain.ledger import (
    MenuSection,
)


class SkillArgs(Args):
    name: str


def _skill_tool(load: Callable[[str], str]) -> ToolSpec:
    async def run(_: ToolContext, a: SkillArgs) -> ToolResult:
        return ToolResult(load(a.name))

    return ToolSpec("load_skill", "Read the full instructions for a skill by name.", SkillArgs, run)


# Tools that only read. With these and the tools that confirm first, the agent can
# answer about an image without anything in the image changing the user's data;
# every other tool waits until the user asks (see AgentGraph.offered). A new tool is
# withheld from image turns until it's listed here or confirms first.
READ_ONLY = frozenset(
    {
        "load_skill",
        *bills.READ_ONLY,
        *budgets.READ_ONLY,
        *categories.READ_ONLY,
        *email.READ_ONLY,
        *coach.READ_ONLY,
        *food.READ_ONLY,
        *gym.READ_ONLY,
        *investments.READ_ONLY,
        *ledger.READ_ONLY,
        *outlook.READ_ONLY,
        *pay.READ_ONLY,
        *query.READ_ONLY,
        *settings.READ_ONLY,
        *splits.READ_ONLY,
        *subscriptions.READ_ONLY,
        *trips_places.READ_ONLY,
        *trips_trip.READ_ONLY,
        *wallets.READ_ONLY,
    }
)


# The tools that belong to a menu section. The first one to succeed for a user who has not
# decided (null) shows that section in the web menu (see AgentGraph.tools_node). The tools
# themselves work the same for everyone: the menu only decides what the web app shows.
MENU_OF: dict[str, MenuSection] = {
    **investments.MENU,
    **coach.MENU,
    **food.MENU,
    **gym.MENU,
    **trips_itinerary.MENU,
    **trips_prep.MENU,
    **trips_research.MENU,
    **trips_trip.MENU,
    **trips_trip_money.MENU,
}


def safe_for_images(spec: ToolSpec) -> bool:
    """Whether the agent may use this tool on a turn about an image the user hasn't
    asked it to act on: it only reads, or it asks the user to confirm first."""
    return spec.confirm is not None or spec.name in READ_ONLY


# The order the model is offered the tools in (the modules each own their specs).
ORDER = (
    "log_expense",
    "log_move",
    "record_income",
    "find_transactions",
    "edit_transaction",
    "delete_transaction",
    "answer_email",
    "find_duplicates",
    "combine_duplicate_transactions",
    "show_portfolio",
    "what_moved_today",
    "set_market_alerts",
    "record_trade",
    "trade_history",
    "show_dividends",
    "stock_levels",
    "research_plan",
    "show_plan",
    "keep_plan_fresh",
    "plan_record",
    "show_watchlist",
    "watch_stock",
    "unwatch_stock",
    "find_exercise",
    "todays_workout",
    "last_time",
    "personal_records",
    "workout_history",
    "weekly_volume",
    "log_sets",
    "finish_workout",
    "undo_last_set",
    "log_food",
    "log_photo_meal",
    "food_today",
    "energy_estimate",
    "draft_training_plan",
    "suggest_adjustments",
    "apply_adjustments",
    "restore_transaction",
    "undo_last_change",
    "spending_summary",
    "query_ledger",
    "list_categories",
    "add_category",
    "rename_category",
    "delete_category",
    "merge_category",
    "mark_as_move",
    "list_wallets",
    "find_likely_moves",
    "add_wallet",
    "update_wallet",
    "set_usual_card",
    "delete_wallet",
    "list_category_rules",
    "set_category_rule",
    "remove_category_rule",
    "explain_category",
    "connect_email",
    "forward_email",
    "test_email_setup",
    "email_status",
    "cash_flow",
    "month_outlook",
    "money_history",
    "calculate",
    "list_subscriptions",
    "transaction_updates",
    "split_bill",
    "list_ious",
    "set_split_habit",
    "list_split_habits",
    "remove_split_habit",
    "set_budget",
    "list_budgets",
    "add_bill",
    "list_bills",
    "mark_bill_paid",
    "snooze_bill",
    "remove_bill",
    "set_pay_schedule",
    "create_trip",
    "update_trip",
    "delete_trip",
    "list_trips",
    "trip_status",
    "add_to_trip",
    "remove_from_trip",
    "split_trip_costs",
    "they_paid",
    "settle_up",
    "add_to_itinerary",
    "add_trip_todo",
    "add_trip_cover",
    "change_itinerary_entry",
    "find_places",
    "find_ideas",
    "web_search",
    "flight_prices",
    "product_prices",
    "flight_status",
    "place_info",
    "label_trip_day",
    "remove_from_itinerary",
    "research_trip",
    "research_to_trip",
    "show_pay_schedule",
    "set_usual_salary",
    "remove_pay_schedule",
    "remove_budget",
    "set_timezone",
    "set_voice",
    "show_voice",
    "load_skill",
    "log_receipt_expense",
)


def build_tools(load_skill: Callable[[str], str]) -> dict[str, ToolSpec]:
    specs = {
        spec.name: spec
        for spec in [
            *bills.SPECS,
            *budgets.SPECS,
            *categories.SPECS,
            *email.SPECS,
            *coach.SPECS,
            *food.SPECS,
            *gym.SPECS,
            *investments.SPECS,
            *ledger.SPECS,
            *outlook.SPECS,
            *pay.SPECS,
            *query.SPECS,
            *settings.SPECS,
            *splits.SPECS,
            *subscriptions.SPECS,
            *trips_itinerary.SPECS,
            *trips_places.SPECS,
            *trips_prep.SPECS,
            *trips_research.SPECS,
            *trips_search.SPECS,
            *trips_trip.SPECS,
            *trips_trip_money.SPECS,
            *wallets.SPECS,
            _skill_tool(load_skill),
        ]
    }
    return {name: specs[name] for name in ORDER}


async def run_tool(spec: ToolSpec, ctx: ToolContext, raw_args: dict[str, Any]) -> ToolResult:
    """Validate and run one call. Expected failures come back as text for the model, and
    so do arguments the tool has no field for (they are dropped, not refused)."""
    try:
        result = await spec.run(ctx, spec.parse(raw_args))
    except NexusError as exc:
        result = ToolResult(f"Error: {exc}", error=mistakes.error_kind(exc))
    ignored = spec.ignored(raw_args)
    if not ignored:
        return result
    return replace(result, text=f"{result.text} (Ignored unknown fields: {', '.join(ignored)}.)")


def args_json(raw: dict[str, Any]) -> str:
    return json.dumps(raw, sort_keys=True, default=str)
