from typing import Union, Dict, Any
from langchain_core.messages import AIMessage
from langgraph.types import Command
from langgraph.graph import END
from orchestrator.state import AssistantState

async def supervisor(state: AssistantState) -> Command[str]:
    """
    Top-level Supervisor agent node:
    - Analyzes user prompt and routes tasks to domain subagents using Command(goto=...)
    - Delegates to email_subagent, expense_subagent, route_subagent, or recipe_subagent
    - Manages subgraph handoffs and callback resumption
    """
    messages = state.get("messages", [])
    active_domain = state.get("active_domain")

    if not messages:
        return Command(goto=END)

    last_message = messages[-1]

    # If the last message was produced by an AI subagent, we return to END (conversation turn completed)
    if isinstance(last_message, AIMessage):
        return Command(goto=END)

    user_text = str(getattr(last_message, "content", "")).lower()

    # 1. In-Scope Domain Routing
    if any(k in user_text for k in ["email", "gmail", "inbox", "mail"]):
        return Command(
            goto="email_subagent",
            update={"active_domain": "email", "intent_type": "in_scope"},
        )
    elif any(k in user_text for k in ["expense", "spent", "paid", "receipt", "starbucks", "dollar", "$"]):
        return Command(
            goto="expense_subagent",
            update={"active_domain": "expenses", "intent_type": "in_scope"},
        )
    elif any(k in user_text for k in ["route", "direction", "drive", "transit", "eta", "traffic"]):
        return Command(
            goto="route_subagent",
            update={"active_domain": "routes", "intent_type": "in_scope"},
        )
    elif any(k in user_text for k in ["recipe", "grocery", "ingredient", "cook", "food"]):
        return Command(
            goto="recipe_subagent",
            update={"active_domain": "recipes", "intent_type": "in_scope"},
        )

    # 2. Unsupported Transactional Guardrail
    unsupported_map = {
        ("transfer", "send money", "wire", "bank transfer", "pay "): "bank_transfer",
        ("calendar", "schedule", "meeting", "appointment", "invite"): "calendar",
        ("flight", "hotel", "book a flight", "flight_booking"): "flight_booking",
        ("smart home", "lights", "turn on", "turn off", "thermostat"): "smart_home",
    }
    missing_tags = []
    for keywords, tag in unsupported_map.items():
        if any(k in user_text for k in keywords):
            missing_tags.append(tag)

    if missing_tags or any(w in user_text for w in ["transfer $", "transfer money", "book ", "schedule "]):
        if not missing_tags:
            missing_tags = ["general_transaction"]

        # Automatically log demand telemetry (resilient DB + GitHub sync)
        from core.audit import log_capability_request
        await log_capability_request(
            user_id=state.get("user_id", 0),
            requested_task=str(last_message.content),
            intent_type="unsupported_transaction",
            tags=missing_tags,
        )

        reply = AIMessage(
            content="I don't currently have a capability plugin for that task. Here are the domains I can help you with: 📧 Email, 💰 Expenses, 🗺️ Routes, 🍳 Recipes."
        )
        return Command(
            goto=END,
            update={
                "messages": [reply],
                "intent_type": "unsupported_transaction",
                "missing_capability_tags": missing_tags,
                "fallback_reason": "Unsupported transactional action requested.",
            },
        )

    # 3. Informational Fallback Routing (Generalist Subagent)
    return Command(
        goto="general_subagent",
        update={
            "active_domain": "general",
            "intent_type": "informational_fallback",
        },
    )

