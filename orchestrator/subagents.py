from typing import Dict, Any
from langchain_core.messages import AIMessage
from langgraph.types import Command
from orchestrator.state import AssistantState
from capabilities.email.tools import (
    search_email_messages,
    search_gmail_messages,
    apply_gmail_processed_label,
    discover_and_track_bank_domain,
)
from capabilities.expenses.tools import process_extracted_expense
from capabilities.routes.tools import plan_route
from capabilities.recipes.tools import parse_recipe_and_extract_ingredients, sync_to_grocery_list, get_user_grocery_list

async def email_subagent(state: AssistantState) -> Command[str]:
    """Email domain subagent: searches financial messages across active providers and discovers bank domains."""
    user_id = state["user_id"]
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""

    # Execute search using unified provider query
    results = await search_email_messages.ainvoke({"user_id": user_id})
    if results:
        for msg in results:
            sender = msg.get("sender", "")
            if sender:
                await discover_and_track_bank_domain(user_id, sender)

    reply = AIMessage(content=f"📧 [Email Subagent] Checked email providers. Found {len(results)} relevant messages.")
    return Command(
        goto="supervisor",
        update={
            "messages": [reply],
            "active_domain": "email",
        },
    )

async def expense_subagent(state: AssistantState) -> Command[str]:
    """Expense domain subagent: extracts, checks duplicates, and triggers HITL on ambiguity."""
    user_id = state["user_id"]
    messages = state["messages"]
    last_msg = str(messages[-1].content) if messages else ""

    # Default extraction parameters; in live mode extracted via LLM structured parser
    res = await process_extracted_expense.ainvoke({
        "user_id": user_id,
        "amount": 15.00,
        "currency": "USD",
        "merchant": "Starbucks",
        "category": "Food & Drink",
        "date_iso": "2026-08-01T10:00:00Z",
        "confidence": 0.75,  # Trigger HITL confirmation
        "needs_clarification": True,
        "source_message_id": "msg_1001",
    })

    status = res.get("status", "unknown")
    reply = AIMessage(content=f"💰 [Expense Subagent] Processed expense: status={status}.")
    return Command(
        goto="supervisor",
        update={
            "messages": [reply],
            "active_domain": "expenses",
        },
    )

async def route_subagent(state: AssistantState) -> Command[str]:
    """Route domain subagent: calculates transit and driving directions."""
    res = await plan_route.ainvoke({
        "origin": "Home",
        "destination": "Office",
        "mode": "transit",
    })
    summary = res.get("summary", "Route planned.")
    reply = AIMessage(content=f"🗺️ [Route Subagent] {summary}")
    return Command(
        goto="supervisor",
        update={
            "messages": [reply],
            "active_domain": "routes",
        },
    )

async def recipe_subagent(state: AssistantState) -> Command[str]:
    """Recipe domain subagent: scrapes recipe and syncs ingredients to GroceryItem table."""
    user_id = state["user_id"]
    res = await parse_recipe_and_extract_ingredients.ainvoke({"recipe_text_or_url": "sample_recipe"})
    ingredients = res.get("ingredients", [])
    synced_ids = await sync_to_grocery_list.ainvoke({"user_id": user_id, "items": ingredients})

    reply = AIMessage(content=f"🍳 [Recipe Subagent] Extracted recipe '{res.get('title')}' and synced {len(synced_ids)} grocery items.")
    return Command(
        goto="supervisor",
        update={
            "messages": [reply],
            "active_domain": "recipes",
        },
    )

async def general_subagent(state: AssistantState) -> Command[str]:
    """
    Generalist fallback subagent: answers factual, temporal, and general reasoning questions.
    Strictly prohibited from performing transactional actions.
    """
    from capabilities.general.tools import search_web, get_current_time_in_user_tz

    user_id = state["user_id"]
    messages = state.get("messages", [])
    last_msg = str(messages[-1].content) if messages else ""

    if "time" in last_msg.lower() or "date" in last_msg.lower():
        answer = await get_current_time_in_user_tz.ainvoke({"user_id": user_id})
    else:
        answer = await search_web.ainvoke({"query": last_msg})

    reply = AIMessage(content=f"💡 [General Assistant] {answer}")
    return Command(
        goto="supervisor",
        update={
            "messages": [reply],
            "active_domain": "general",
        },
    )

