from dataclasses import dataclass, field
import json
import os
from typing import Protocol, List, Dict, Any, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Command
from langgraph.graph import END
from orchestrator.state import AssistantState
from capabilities.email.tools import (
    search_email_messages,
    discover_and_track_bank_domain,
    get_user_gmail_token,
)
from capabilities.expenses.tools import process_extracted_expense
from capabilities.routes.tools import plan_route
from capabilities.recipes.tools import parse_recipe_and_extract_ingredients
from core.config import settings
from core.llm import get_agent_llm, ThinkingLevel
from core.audit import log_capability_request


SYSTEM_PROMPT = (
    "You are Nexus Prime, a personal AI assistant running as a Telegram bot for a close friend. "
    "You are warm, sharp, and lightly witty — like a capable friend who actually enjoys helping. "
    "Write like a human texting on Telegram: concise, natural, lowercase-friendly when it fits, "
    "light emoji where it adds warmth, and no corporate filler. "
    "Never introduce yourself as a subagent or model; just be you. "
    "If you don't know something, say so honestly instead of making it up. "
    "Current Singapore time: {now}. "
    "You can help with email, expenses, routes, recipes, reminders, and general questions — "
    "but if the user asks for something genuinely out of scope, say so warmly and suggest what you CAN do."
)


@dataclass
class PluginOutput:
    """Pure Python execution output from a CapabilityPlugin."""

    message: AIMessage
    state_update: Dict[str, Any] = field(default_factory=dict)


class CapabilityPlugin(Protocol):
    """Declarative interface for domain capability plugins."""

    name: str
    keywords: List[str]
    description: str

    async def execute(self, state: AssistantState) -> PluginOutput:
        ...


class EmailPlugin:
    """Email capability plugin: searches financial messages and tracks bank domains."""

    name = "email"
    keywords = ["email", "gmail", "inbox", "mail"]
    description = "Searches email providers and discovers bank domains automatically."

    async def execute(self, state: AssistantState) -> PluginOutput:
        user_id = state["user_id"]

        # One-time Gmail authorization: the bot can't read email until the user consents.
        if settings.google_client_id and not await get_user_gmail_token(user_id):
            public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
            base = (
                f"https://{public_domain}".rstrip("/")
                if public_domain
                else (settings.webapp_url or "").rstrip("/")
            )
            link = f"{base}/auth/gmail?user_id={user_id}"
            return PluginOutput(
                message=AIMessage(
                    content=(
                        "🔐 I can check your Gmail — I just need one-time access from you. "
                        f"Open this link and allow Gmail access (read-only), then message me again:\n{link}"
                    )
                ),
                state_update={"active_domain": self.name},
            )

        results = await search_email_messages.ainvoke({"user_id": user_id})
        if results:
            for msg in results:
                sender = msg.get("sender", "")
                if sender:
                    await discover_and_track_bank_domain(user_id, sender)
        reply = AIMessage(content=await self._summarize_email_results(results))
        return PluginOutput(message=reply, state_update={"active_domain": self.name})

    @staticmethod
    async def _summarize_email_results(results: List[Dict[str, Any]]) -> str:
        """Summarize fetched emails with DeepSeek, or fall back to a plain list."""
        if not results:
            return (
                "📬 I checked your inbox — nothing expense-related in the last week. "
                "Want me to look at a specific sender or date range?"
            )

        fallback_lines = [
            f"• {msg.get('sender', '?')}: {msg.get('subject', '(no subject)')}"
            for msg in results[:5]
        ]
        fallback = "📬 Here's what I found in your inbox:\n" + "\n".join(fallback_lines)

        if not settings.deepseek_api_key or settings.deepseek_api_key == "test_deepseek_key":
            return fallback

        try:
            llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.4)
            emails_text = json.dumps(results[:8], indent=1, default=str)
            ai_message = await llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are Nexus Prime, the user's personal assistant on Telegram. "
                            "You just fetched real emails from their inbox. Summarize them "
                            "conversationally in 2-5 short lines: name the senders, what each "
                            "message is about, and flag anything that looks like a bill, receipt, "
                            "or expense. Do not mention that you are a subagent."
                        )
                    ),
                    HumanMessage(content=f"Emails:\n{emails_text}"),
                ]
            )
            summary = str(getattr(ai_message, "content", "") or "").strip()
            return summary or fallback
        except Exception as exc:  # noqa: BLE001
            print(f"[EMAIL] summary LLM failed, using fallback: {exc}")
            return fallback


class ExpensePlugin:
    """Expense capability plugin: extracts expenses, checks duplicates, and triggers HITL on ambiguity."""

    name = "expenses"
    keywords = ["expense", "spent", "paid", "receipt", "starbucks", "dollar", "$"]
    description = "Processes receipts and financial expenses with HITL confirmation."

    async def execute(self, state: AssistantState) -> PluginOutput:
        user_id = state["user_id"]
        res = await process_extracted_expense.ainvoke(
            {
                "user_id": user_id,
                "amount": 15.00,
                "currency": "USD",
                "merchant": "Starbucks",
                "category": "Food & Drink",
                "date_iso": "2026-08-01T10:00:00Z",
                "confidence": 0.75,
                "needs_clarification": True,
                "source_message_id": "msg_1001",
            }
        )
        status = res.get("status", "unknown")
        reply = AIMessage(
            content=f"💰 [Expense Subagent] Processed expense: status={status}."
        )
        return PluginOutput(message=reply, state_update={"active_domain": self.name})


class RoutePlugin:
    """Route capability plugin: plans travel routes and checks real-time Singapore LTA transit alerts."""

    name = "routes"
    keywords = ["route", "direction", "drive", "transit", "eta", "traffic"]
    description = "Computes travel routes and live Singapore LTA transit alerts."

    async def execute(self, state: AssistantState) -> PluginOutput:
        res = await plan_route.ainvoke(
            {
                "origin": "Changi Airport",
                "destination": "Marina Bay Sands",
                "mode": "transit",
            }
        )
        reply = AIMessage(
            content=f"🗺️ [Route Subagent] Route planned: {res['origin']} -> {res['destination']} (~{res['eta_minutes']} mins). Mode: {res['mode']}."
        )
        return PluginOutput(message=reply, state_update={"active_domain": self.name})


class RecipePlugin:
    """Recipe capability plugin: extracts ingredients from recipes and syncs to grocery lists."""

    name = "recipes"
    keywords = ["recipe", "grocery", "ingredient", "cook", "food"]
    description = "Parses recipes and syncs ingredients to user grocery lists."

    async def execute(self, state: AssistantState) -> PluginOutput:
        res = await parse_recipe_and_extract_ingredients.ainvoke(
            {
                "recipe_text": "Spaghetti Carbonara: 200g pasta, 100g pancetta, 2 eggs, 50g pecorino cheese"
            }
        )
        reply = AIMessage(
            content=f"🍳 [Recipe Subagent] Parsed recipe: {res['title']} with {len(res['ingredients'])} ingredients."
        )
        return PluginOutput(message=reply, state_update={"active_domain": self.name})


class GeneralPlugin:
    """General capability plugin: handles factual queries and casual conversation with DeepSeek v4 Flash + Tavily."""

    name = "general"
    keywords = []
    description = "Fallback capability using DeepSeek v4 Flash and Tavily web search."

    async def execute(self, state: AssistantState) -> PluginOutput:
        messages = state.get("messages", [])
        now_sg = datetime.now(ZoneInfo("Asia/Singapore")).strftime("%A, %d %b %Y %H:%M")
        history = [SystemMessage(content=SYSTEM_PROMPT.format(now=now_sg))]
        for message in messages[-8:]:
            if isinstance(message, HumanMessage):
                history.append(HumanMessage(content=str(message.content)))
            elif isinstance(message, AIMessage):
                history.append(AIMessage(content=str(message.content)))

        # Tests and local runs use the placeholder key; skip the network call there.
        if not settings.deepseek_api_key or settings.deepseek_api_key == "test_deepseek_key":
            return PluginOutput(
                message=AIMessage(content="Hey! I'm here — what do you need? 🙂"),
                state_update={"active_domain": self.name},
            )

        try:
            llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.7)
            ai_message = await llm.ainvoke(history)
            content = str(getattr(ai_message, "content", "") or "").strip()
            if not content:
                content = "My mind went blank for a second — mind rephrasing that?"
        except Exception as exc:  # noqa: BLE001 - never let LLM errors kill the webhook
            print(f"[GENERAL] LLM call failed, using fallback: {exc}")
            content = "Sorry — my brain just glitched for a second. Try me again?"

        return PluginOutput(
            message=AIMessage(content=content),
            state_update={"active_domain": self.name},
        )


class GuardrailPolicy:
    """Declarative guardrail policy registry for detecting out-of-scope transactional requests."""

    def __init__(self):
        self.unsupported_map = {
            (
                "transfer",
                "send money",
                "wire",
                "bank transfer",
                "pay ",
            ): "bank_transfer",
            ("calendar", "schedule", "meeting", "appointment", "invite"): "calendar",
            ("flight", "hotel", "book a flight", "flight_booking"): "flight_booking",
            ("smart home", "lights", "turn on", "turn off", "thermostat"): "smart_home",
        }

    def evaluate(self, user_text: str) -> Optional[List[str]]:
        """Return a list of wishlist capability tags if the intent is an unsupported transaction, else None."""
        lowered = user_text.lower()
        missing_tags = []
        for keywords, tag in self.unsupported_map.items():
            if any(k in lowered for k in keywords):
                missing_tags.append(tag)

        if (
            missing_tags
            or any(
                w in lowered
                for w in ["transfer $", "transfer money", "book ", "schedule "]
            )
        ):
            if not missing_tags:
                missing_tags = ["general_transaction"]
            return missing_tags
        return None


# Global registry of active domain capability plugins
CAPABILITY_REGISTRY: Dict[str, CapabilityPlugin] = {
    "email": EmailPlugin(),
    "expenses": ExpensePlugin(),
    "routes": RoutePlugin(),
    "recipes": RecipePlugin(),
    "general": GeneralPlugin(),
}


class CapabilityRouter:
    """Deep routing module: dispatches intents to registered CapabilityPlugins or GuardrailPolicy."""

    def __init__(
        self,
        registry: Optional[Dict[str, CapabilityPlugin]] = None,
        guardrail: Optional[GuardrailPolicy] = None,
    ):
        self.registry = registry or CAPABILITY_REGISTRY
        self.guardrail = guardrail or GuardrailPolicy()

    def route_intent(self, user_text: str) -> str:
        """Match prompt against declarative plugin keywords."""
        lowered = user_text.lower()
        for name, plugin in self.registry.items():
            if name == "general":
                continue
            if any(k in lowered for k in plugin.keywords):
                return name
        return "general"

    async def dispatch(self, state: AssistantState) -> Command[str]:
        """
        Evaluate guardrails, dispatch state to matched CapabilityPlugin,
        record audit telemetry, and return LangGraph Command(goto=END).
        """
        messages = state.get("messages", [])
        user_id = state.get("user_id", 0)

        if not messages:
            return Command(goto=END)

        last_message = messages[-1]
        if isinstance(last_message, AIMessage):
            return Command(goto=END)

        user_text = str(getattr(last_message, "content", "")).strip()

        # 1. Evaluate Unsupported Transactional Guardrails
        missing_tags = self.guardrail.evaluate(user_text)
        if missing_tags:
            primary_tag = missing_tags[0]
            await log_capability_request(
                user_id=user_id,
                requested_task=user_text,
                intent_type="unsupported_transaction",
                tags=missing_tags,
            )
            reply = AIMessage(
                content=f"⚠️ [Supervisor Guardrail] This transactional capability (`#{primary_tag}`) is not yet supported. Would you like to log it as a feature request?"
            )
            return Command(
                goto=END,
                update={
                    "messages": [reply],
                    "active_domain": "general",
                    "intent_type": "unsupported_transaction",
                    "missing_capability_tags": missing_tags,
                },
            )

        # 2. Dispatch to declarative capability plugin
        target_domain = self.route_intent(user_text)
        plugin = self.registry.get(target_domain) or self.registry["general"]
        output = await plugin.execute(state)

        intent_type = "informational_fallback" if plugin.name == "general" else "in_scope"
        await log_capability_request(
            user_id=user_id,
            requested_task=user_text,
            intent_type=intent_type,
            tags=[plugin.name],
        )

        return Command(
            goto=END,
            update={
                "messages": [output.message],
                "active_domain": plugin.name,
                "intent_type": intent_type,
                **output.state_update,
            },
        )


# Default global router instance
_default_router = CapabilityRouter()


async def capability_router_node(state: AssistantState) -> Command[str]:
    """Single deep LangGraph entry node that routes and executes capabilities."""
    return await _default_router.dispatch(state)
