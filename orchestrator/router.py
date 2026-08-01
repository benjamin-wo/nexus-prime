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
from capabilities.expenses.tools import (
    process_extracted_expense,
    extract_expense_from_text,
    expense_source_id,
    log_expenses_from_emails,
)
from capabilities.routes.tools import plan_route, extract_route_request
from capabilities.recipes.tools import (
    parse_recipe_and_extract_ingredients,
    sync_to_grocery_list,
)
from core.config import settings
from core.llm import extract_llm_text, get_agent_llm, get_multimodal_llm, ThinkingLevel
from core.audit import log_capability_request


SYSTEM_PROMPT = (
    "You are Nexus Prime, a personal AI assistant running as a Telegram bot for a close friend. "
    "You are warm, sharp, and lightly witty — like a capable friend who actually enjoys helping. "
    "Write like a human texting on Telegram: concise, natural, lowercase-friendly when it fits, "
    "light emoji where it adds warmth, and no corporate filler. "
    "Format for Telegram chat: short paragraphs, **bold** for key phrases, bullet lists starting "
    "with '-', no tables, no code fences, no headings with '#'. "
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
                        f"Open this link and allow Gmail access (read-only) — "
                        f"I'll ping you here when it's connected:\n{link}"
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

        # Auto-log expenses found in the fetched emails (deduped by email ID).
        expense_result = await log_expenses_from_emails.ainvoke(
            {"user_id": user_id, "emails": results}
        )
        logged = expense_result.get("logged") or []
        skipped = expense_result.get("skipped") or []
        if logged:
            lines = [
                f"📧 Checked your inbox — auto-logged {len(logged)} expense"
                f"{'s' if len(logged) != 1 else ''}:"
            ]
            for item in logged[:8]:
                lines.append(
                    f"• {item['currency']} {item['amount']:.2f} — "
                    f"{item['merchant']} ({item['category']})"
                )
            if skipped:
                lines.append(f"\n…{len(skipped)} ambiguous skipped — ask me to review them.")
            lines.append("\n/expenses to see everything.")
            return PluginOutput(
                message=AIMessage(content="\n".join(lines)),
                state_update={"active_domain": self.name},
            )

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
        messages = state.get("messages", [])
        last_text = str(messages[-1].content) if messages else ""

        # Listing intent: "list/show/summary my expenses" should query, not extract.
        lowered = last_text.lower()
        list_intent = any(
            phrase in lowered
            for phrase in (
                "list my expense",
                "show my expense",
                "show me my expense",
                "my expenses",
                "expense summary",
                "expense overview",
                "what have i spent",
                "how much have i spent",
                "expenses so far",
                "expense total",
                "total expenses",
            )
        )
        if list_intent:
            from capabilities.expenses.tools import get_user_expenses

            rows = await get_user_expenses.ainvoke({"user_id": user_id, "limit": 10})
            if not rows:
                reply = (
                    "💰 No expenses logged yet. Say something like "
                    "*\"spent $12.50 at Starbucks\"*, or ask me to check your email "
                    "and I'll log receipts automatically."
                )
            else:
                lines = ["💰 Your recent expenses:"]
                for row in rows:
                    lines.append(
                        f"• {row['date'][:10]} {row['currency']} {row['amount']:.2f} — "
                        f"{row['merchant']} ({row['category']})"
                    )
                total = sum(row["amount"] for row in rows)
                lines.append(f"\nTotal (last {len(rows)}): {rows[0]['currency']} {total:.2f}")
                reply = "\n".join(lines)
            return PluginOutput(
                message=AIMessage(content=reply),
                state_update={"active_domain": self.name},
            )

        extracted = await extract_expense_from_text.ainvoke({"user_text": last_text})
        if not extracted or not extracted.get("amount"):
            return PluginOutput(
                message=AIMessage(
                    content=(
                        "💰 I couldn't spot an expense in that — try something like "
                        "*\"spent $12.50 at Starbucks\"* or *\"paid $4.20 for kopi\"*."
                    )
                ),
                state_update={"active_domain": self.name},
            )

        res = await process_extracted_expense.ainvoke(
            {
                "user_id": user_id,
                "amount": extracted["amount"],
                "currency": extracted.get("currency", "USD"),
                "merchant": extracted["merchant"],
                "category": extracted.get("category", "General"),
                "date_iso": extracted.get("date_iso") or "",
                "confidence": extracted.get("confidence", 0.9),
                "needs_clarification": extracted.get("needs_clarification", False),
                "source_message_id": expense_source_id(user_id, last_text),
            }
        )
        status = res.get("status", "unknown")
        if status == "saved_silently":
            reply = (
                f"💰 Logged *{extracted.get('currency', 'SGD')} {extracted['amount']:.2f}* "
                f"at *{extracted['merchant']}* ({extracted.get('category', 'General')})."
            )
        elif status == "duplicate":
            reply = "🙅 That expense is already logged."
        elif status == "confirmed_by_user":
            reply = (
                f"✅ Saved {extracted.get('currency', 'SGD')} {extracted['amount']:.2f} "
                f"at {extracted['merchant']}."
            )
        else:
            reply = f"💰 Found {extracted['amount']:.2f} at {extracted['merchant']} — confirm below."
        return PluginOutput(message=reply, state_update={"active_domain": self.name})


class RoutePlugin:
    """Route capability plugin: plans travel routes and checks real-time Singapore LTA transit alerts."""

    name = "routes"
    keywords = ["route", "direction", "drive", "transit", "eta", "traffic"]
    description = "Computes travel routes and live Singapore LTA transit alerts."

    async def execute(self, state: AssistantState) -> PluginOutput:
        messages = state.get("messages", [])
        last_text = str(messages[-1].content) if messages else ""

        req = await extract_route_request.ainvoke({"user_text": last_text})
        origin = (req.get("origin") or "").strip()
        destination = (req.get("destination") or "").strip()
        mode = req.get("mode") or "transit"
        if not origin or not destination:
            return PluginOutput(
                message=AIMessage(
                    content=(
                        "I need two places to route between — try *\"route from Raffles Place "
                        "to Changi Airport\"* or *\"drive to Marina Bay Sands\"*. 🌏"
                    )
                ),
                state_update={"active_domain": self.name},
            )

        res = await plan_route.ainvoke(
            {"origin": origin, "destination": destination, "mode": mode}
        )
        if res.get("error"):
            return PluginOutput(
                message=AIMessage(
                    content=(
                        f"⚠️ Couldn't plan that route ({res['error']}). "
                        "Try different place names or a nearby landmark?"
                    )
                ),
                state_update={"active_domain": self.name},
            )

        icon = "🚇" if mode == "transit" else "🚗"
        lines = [
            f"{icon} *{res['origin']}* → *{res['destination']}*: "
            f"~{res['eta_minutes']} min ({res['distance_km']} km)"
        ]
        for index, step in enumerate(res.get("steps", [])[:5], 1):
            lines.append(f"{index}. {step}")
        reply = AIMessage(content="\n".join(lines))
        return PluginOutput(message=reply, state_update={"active_domain": self.name})


class RecipePlugin:
    """Recipe capability plugin: extracts ingredients from recipes and syncs to grocery lists."""

    name = "recipes"
    keywords = ["recipe", "grocery", "ingredient", "cook", "food"]
    description = "Parses recipes and syncs ingredients to user grocery lists."

    async def execute(self, state: AssistantState) -> PluginOutput:
        user_id = state["user_id"]
        messages = state.get("messages", [])
        last_text = str(messages[-1].content) if messages else ""

        res = await parse_recipe_and_extract_ingredients.ainvoke(
            {"recipe_text_or_url": last_text}
        )
        ingredients = res.get("ingredients") or []
        if not ingredients:
            return PluginOutput(
                message=AIMessage(
                    content=(
                        "🍳 I couldn't find a recipe in that — paste a recipe and I'll add "
                        "the ingredients to your grocery list."
                    )
                ),
                state_update={"active_domain": self.name},
            )

        added = await sync_to_grocery_list.ainvoke(
            {"user_id": user_id, "items": ingredients}
        )
        lines = [
            f"📖 *{res.get('title', 'Recipe')}* — added {len(added)} items to your grocery list:"
        ]
        for item in ingredients[:10]:
            lines.append(f"• {item['name']} ({item.get('quantity', '1')})")
        if len(ingredients) > 10:
            lines.append(f"…and {len(ingredients) - 10} more")
        lines.append("\nType /groceries to see the full list.")
        reply = AIMessage(content="\n".join(lines))
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
                history.append(
                    HumanMessage(
                        content=message.content
                        if isinstance(message.content, list)
                        else str(message.content)
                    )
                )
            elif isinstance(message, AIMessage):
                history.append(AIMessage(content=str(message.content)))

        last_content = messages[-1].content if messages else ""
        has_media = isinstance(last_content, list) and any(
            isinstance(block, dict) and block.get("type") == "media"
            for block in last_content
        )

        if has_media:
            return await self._execute_multimodal(history)

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

    @staticmethod
    async def _execute_multimodal(history: List[Any]) -> PluginOutput:
        """Answer image/audio messages with Gemini's multimodal model."""
        fallback = (
            "I got your photo/voice, but my vision model isn't configured "
            "on this deployment yet (GEMINI_API_KEY missing)."
        )
        if (
            not settings.active_gemini_api_key
            or settings.active_gemini_api_key == "test_google_key"
        ):
            return PluginOutput(
                message=AIMessage(content=fallback),
                state_update={"active_domain": "general"},
            )

        try:
            llm = get_multimodal_llm(temperature=0.4)
            ai_message = await llm.ainvoke(history)
            content = extract_llm_text(getattr(ai_message, "content", "")).strip()
            if not content:
                content = "I saw your attachment but drew a blank — mind describing it?"
        except Exception as exc:  # noqa: BLE001
            print(f"[GENERAL] multimodal LLM failed: {exc}")
            content = "😵‍💫 I couldn't process that media just now — try again?"
        return PluginOutput(
            message=AIMessage(content=content),
            state_update={"active_domain": "general"},
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
