from dataclasses import dataclass, field
import asyncio
import json
import os
import re
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
    extract_expense_from_photo,
    expense_source_id,
    log_expenses_from_emails,
)
from capabilities.routes.tools import plan_route, extract_route_request
from capabilities.routes.journey import format_journey, plan_transit_journey
from capabilities.recipes.tools import (
    parse_recipe_and_extract_ingredients,
    sync_to_grocery_list,
)
from capabilities.reminders.tools import parse_reminder_request
from capabilities.general.tools import search_web
from orchestrator.checkpointer import prune_and_summarize_messages
from core.audit import log_capability_request, should_sample_audit, perform_audit_evaluation
from core.scheduler import (
    delete_scheduled_job,
    list_active_jobs,
    schedule_proactive_task,
    scheduler,
)
from core.config import settings
from core.llm import extract_llm_text, get_agent_llm, get_multimodal_llm, ThinkingLevel


SYSTEM_PROMPT = (
    "You are Nexus Prime, a personal AI assistant running as a Telegram bot for a close friend. "
    "You are warm, sharp, proactive, and resourceful — like a capable friend who actually helps build plans and solutions. "
    "Write like a human texting on Telegram: concise, natural, lowercase-friendly when it fits, "
    "light emoji where it adds warmth, and no corporate filler. "
    "When asked to plan a trip, itinerary, event, or recommendation, BE PROACTIVE: immediately give a concrete draft plan or schedule based on what the user shared, recommend real, exciting spots/activities, and suggest clear options. NEVER stall by asking a barrage of questionnaire questions — give them an actionable plan right away! "
    "Format for Telegram chat: short paragraphs, **bold** for key phrases, bullet lists starting "
    "with '-', no tables, no code fences, no headings with '#'. "
    "Never introduce yourself as a subagent or model; just be you. "
    "If you don't know something, say so honestly instead of making it up. "
    "Current Singapore time: {now}. "
    "You can help with email, expenses, routes, recipes, reminders, whiteboard planning, and general questions."
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
        last_content = messages[-1].content if messages else ""

        # Receipt photo path: Gemini vision extracts the expense, image hash dedups.
        if isinstance(last_content, list):
            media_blocks = [
                block
                for block in last_content
                if isinstance(block, dict) and block.get("type") == "media"
            ]
            text_parts = [
                block.get("text", "")
                for block in last_content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            caption = " ".join(text_parts).strip()
            image_block = next(
                (
                    block
                    for block in media_blocks
                    if (block.get("mime_type") or "").startswith("image/")
                ),
                None,
            )
            if image_block:
                import hashlib

                extracted = await extract_expense_from_photo.ainvoke(
                    {
                        "image_b64": image_block.get("data", ""),
                        "mime_type": image_block.get("mime_type", "image/jpeg"),
                        "caption": caption or None,
                    }
                )
                if not extracted or not extracted.get("amount"):
                    return PluginOutput(
                        message=AIMessage(
                            content=(
                                "📸 I don't see a clear receipt in that photo — try a closer, "
                                "well-lit shot of the total, or just tell me the amount in text."
                            )
                        ),
                        state_update={"active_domain": self.name},
                    )
                image_digest = hashlib.md5(
                    (image_block.get("data") or "").encode("utf-8")
                ).hexdigest()[:12]
                return await self._finalize_expense(
                    user_id,
                    extracted,
                    f"exp-photo-{user_id}-{image_digest}",
                )

        last_text = (
            str(last_content) if not isinstance(last_content, list) else ""
        )

        # Listing intent: "list/show/how much/spending/summary" queries → query DB, not extract.
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
                "how much did i spend",
                "how much on",
                "how much did i spend on",
                "spent on",
                "spending on",
                "expenses so far",
                "expense total",
                "total expenses",
                "food expenses",
                "food spending",
                "/expenses",
            )
        )
        if list_intent:
            from capabilities.expenses.tools import get_user_expenses
            from datetime import timezone as _tz, timedelta

            now_sg = datetime.now(_tz.utc).astimezone(ZoneInfo("Asia/Singapore"))
            now_iso = now_sg.isoformat()

            # ── LLM-powered structured intent extraction ─────────────────────────
            # Ask the LLM to parse the user's natural-language query into structured
            # filters instead of relying on a brittle hardcoded keyword list.
            VALID_CATEGORIES = ["Dining", "Groceries", "Transport", "Shopping", "Bills", "General", "Leisure"]
            intent_filters: Dict[str, Any] = {
                "categories": None,
                "since_date": None,
                "until_date": None,
                "summary_only": False,
                "label": "recent expenses",
            }

            if settings.deepseek_api_key and settings.deepseek_api_key != "test_deepseek_key":
                try:
                    llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.0)
                    extraction_prompt = (
                        f"Today is {now_iso} (Asia/Singapore). "
                        "The user is asking about their expense history. "
                        "Extract structured query filters from their message. "
                        "Reply ONLY with a JSON object (no markdown fences):\n"
                        "{\n"
                        f'  "categories": null | array of strings from {VALID_CATEGORIES},\n'
                        '  "since_date": null | ISO 8601 datetime string (inclusive start),\n'
                        '  "until_date": null | ISO 8601 datetime string (exclusive end),\n'
                        '  "summary_only": boolean (true if user wants total/sum, not itemised list),\n'
                        '  "label": short human-readable description of what was queried (e.g. "food this week")\n'
                        "}\n\n"
                        "Rules:\n"
                        "- 'food', 'eating', 'hawker', 'restaurant', 'meals', 'takeout' → Dining and/or Groceries\n"
                        "- 'this week' = Monday 00:00 SGT to now\n"
                        "- 'this month' = 1st of current month 00:00 SGT to now\n"
                        "- 'today' = today 00:00 SGT to now\n"
                        "- 'yesterday' = yesterday 00:00 to 23:59 SGT\n"
                        "- 'last fortnight' = 14 days ago to now\n"
                        "- 'last N days' = N days ago 00:00 to now\n"
                        "- If no category filter mentioned, set categories to null\n"
                        "- If no time filter mentioned, set both date fields to null"
                    )
                    ai_msg = await llm.ainvoke([
                        SystemMessage(content=extraction_prompt),
                        HumanMessage(content=last_text),
                    ])
                    raw = str(getattr(ai_msg, "content", "") or "").strip()
                    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
                    parsed = json.loads(raw)
                    intent_filters["categories"] = parsed.get("categories") or None
                    intent_filters["since_date"] = parsed.get("since_date") or None
                    intent_filters["until_date"] = parsed.get("until_date") or None
                    intent_filters["summary_only"] = bool(parsed.get("summary_only", False))
                    intent_filters["label"] = str(parsed.get("label", "recent expenses"))
                except Exception as parse_err:
                    print(f"[EXPENSES] LLM intent parse failed, querying unfiltered: {parse_err}")

            rows = await get_user_expenses.ainvoke({
                "user_id": user_id,
                "limit": 50,
                "categories": intent_filters["categories"],
                "since_date": intent_filters["since_date"],
                "until_date": intent_filters["until_date"],
            })

            label = intent_filters["label"]
            if not rows:
                reply = (
                    f"💰 No expenses found for *{label}*. "
                    "Try *\"spent $12.50 at Starbucks\"* or ask me to scan your email for receipts."
                )
            else:
                total = sum(row["amount"] for row in rows)
                currency = rows[0]["currency"]
                count = len(rows)
                if intent_filters["summary_only"]:
                    reply = (
                        f"💰 *{label.title()}* — you spent **{currency} {total:.2f}** "
                        f"across {count} transaction{'s' if count != 1 else ''}."
                    )
                else:
                    lines = [
                        f"💰 *{label.title()}* — **{currency} {total:.2f}** "
                        f"across {count} transaction{'s' if count != 1 else ''}:"
                    ]
                    for row in rows[:15]:
                        lines.append(
                            f"• {row['date'][:10]} {row['currency']} {row['amount']:.2f} — "
                            f"{row['merchant']} ({row['category']})"
                        )
                    if count > 15:
                        lines.append(f"…and {count - 15} more.")
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

        return await self._finalize_expense(
            user_id,
            extracted,
            expense_source_id(user_id, last_text),
        )

    @staticmethod
    async def _finalize_expense(
        user_id: int,
        extracted: Dict[str, Any],
        source_id: str,
    ) -> PluginOutput:
        """Save an extracted expense (text or photo) with dedup and HITL handling."""
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
                "source_message_id": source_id,
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

        # Bus-arrival queries (times at a stop) use LTA; directions with a
        # destination ("bus from X to Y") go through the Maps journey instead.
        lowered = last_text.lower()
        from capabilities.routes.tools import handle_bus_query, is_bare_place_fragment, is_bus_arrival_query

        if is_bus_arrival_query(last_text):

            bus_result = await handle_bus_query(
                last_text, pending_stops=state.get("pending_bus_stops")
            )
            return PluginOutput(
                message=AIMessage(content=bus_result["message"]),
                state_update={
                    "active_domain": self.name,
                    "pending_bus_stops": bus_result.get("pending_stops"),
                },
            )

        req = await extract_route_request.ainvoke({"user_text": last_text})
        origin = (req.get("origin") or "").strip()
        destination = (req.get("destination") or "").strip()
        mode = req.get("mode") or "transit"
        last_route = state.get("last_route") or {}
        if not origin and last_route.get("origin"):
            origin = str(last_route["origin"])
        if not destination and last_route.get("destination"):
            destination = str(last_route["destination"])
        if is_bare_place_fragment(last_text):
            if origin and not destination:
                destination = last_text.strip()
            elif not origin and destination:
                origin = last_text.strip()
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

        if mode == "transit":
            journey = await plan_transit_journey(origin, destination)
            if not journey.get("error"):
                return PluginOutput(
                    message=AIMessage(content=format_journey(journey)),
                    state_update={
                        "active_domain": self.name,
                        "last_route": {
                            "origin": origin,
                            "destination": destination,
                            "mode": mode,
                        },
                    },
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
        return PluginOutput(
            message=reply,
            state_update={
                "active_domain": self.name,
                "last_route": {"origin": origin, "destination": destination, "mode": mode},
            },
        )


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
        if len(messages) > 12:
            pruned, _ = prune_and_summarize_messages(messages, threshold=12)
        else:
            pruned = messages
        history = [SystemMessage(content=SYSTEM_PROMPT.format(now=now_sg))]
        for message in pruned[-8:]:
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

        # Real web search context for informational questions.
        last_text = str(last_content) if not isinstance(last_content, list) else ""
        if any(
            phrase in last_text.lower()
            for phrase in (
                "who is",
                "what is",
                "latest",
                "news",
                "search",
                "current",
                "weather",
                "capital",
                "when is",
                "how do i",
                "why is",
            )
        ):
            try:
                search_result = await search_web.ainvoke({"query": last_text})
                if search_result and not search_result.startswith("[search]"):
                    history.append(
                        SystemMessage(
                            content=(
                                "Web search results (use them as the factual basis for your "
                                f"reply, and cite the source when useful):\n{search_result}"
                            )
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[GENERAL] web search failed: {exc}")

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


class ReminderPlugin:
    """Reminder capability plugin: creates, lists, and deletes cron reminders."""

    name = "reminders"
    keywords = ["remind", "reminder", "cron", "every", "daily", "weekly"]
    description = "Sets cron-based reminders and scheduled tasks on Telegram."

    async def execute(self, state: AssistantState) -> PluginOutput:
        user_id = state["user_id"]
        messages = state.get("messages", [])
        last_text = str(messages[-1].content) if messages else ""

        parsed = await parse_reminder_request.ainvoke({"user_text": last_text})
        action = parsed.get("action")

        if action == "list":
            jobs = await list_active_jobs(user_id=user_id)
            if not jobs:
                reply = "📋 No active reminders. Try *\"remind me to drink water every 2 hours\"*."
            else:
                lines = ["📋 Active reminders:"]
                for job in jobs:
                    next_run = job.get("next_run_time") or "not scheduled"
                    lines.append(
                        f"- #{job['job_id']} *{job['job_name']}* "
                        f"(`{job['cron_expression']}` @ {job['timezone']}, next: {next_run})"
                    )
                reply = "\n".join(lines)
            return PluginOutput(
                message=AIMessage(content=reply),
                state_update={"active_domain": self.name},
            )

        if action == "delete":
            job_id = parsed.get("job_id")
            if not job_id:
                reply = "Which reminder? Say *\"delete reminder <id>\"* — use /jobs to find the ID."
            else:
                deleted = await delete_scheduled_job(int(job_id), user_id)
                reply = (
                    f"🗑️ Reminder #{job_id} deleted."
                    if deleted
                    else f"⚠️ No reminder #{job_id} found."
                )
            return PluginOutput(
                message=AIMessage(content=reply),
                state_update={"active_domain": self.name},
            )

        message_text = (parsed.get("message") or "").strip()
        cron = (parsed.get("cron") or "").strip()
        timezone = parsed.get("timezone") or "Asia/Singapore"
        if not message_text or not cron:
            reply = (
                "I can set reminders — try *\"remind me to drink water every 2 hours\"* "
                "or *\"remind me to call mom daily at 9pm\"*."
            )
            return PluginOutput(
                message=AIMessage(content=reply),
                state_update={"active_domain": self.name},
            )

        try:
            job = await schedule_proactive_task(
                user_id=user_id,
                job_name=message_text[:50],
                cron_expression=cron,
                instruction_prompt=message_text,
                timezone_str=timezone,
            )
            aps_job = scheduler.get_job(str(job.id))
            next_run = (
                aps_job.next_run_time.isoformat()
                if aps_job and aps_job.next_run_time
                else "soon"
            )
            reply = (
                f"✅ Reminder set (#{job.id}): *\"{message_text}\"*\n"
                f"Cron `{cron}` ({timezone})\nNext run: {next_run}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[REMINDERS] schedule failed: {exc}")
            reply = (
                f"⚠️ Couldn't parse *\"{cron}\"* as a schedule — try something like "
                "*\"every 2 hours\"* or *\"daily at 9pm\"*."
            )
        return PluginOutput(
            message=AIMessage(content=reply),
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


def _schedule_audit(
    user_id: int,
    turn_context: Dict[str, Any],
    force: bool = False,
) -> None:
    """Fire-and-forget LLM-as-a-judge evaluation without blocking the webhook."""
    try:
        if not should_sample_audit(hitl_triggered=force):
            return
        asyncio.create_task(
            perform_audit_evaluation(
                user_id=user_id,
                thread_id=str(user_id),
                turn_context=turn_context,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[AUDIT] scheduling failed: {exc}")


# Global registry of active domain capability plugins
CAPABILITY_REGISTRY: Dict[str, CapabilityPlugin] = {
    "email": EmailPlugin(),
    "expenses": ExpensePlugin(),
    "routes": RoutePlugin(),
    "recipes": RecipePlugin(),
    "reminders": ReminderPlugin(),
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

        last_content = getattr(last_message, "content", "")
        if isinstance(last_content, list):
            text_parts = [
                block.get("text", "")
                for block in last_content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            user_text = " ".join(text_parts).strip()
            media_blocks = [
                block
                for block in last_content
                if isinstance(block, dict) and block.get("type") == "media"
            ]
            image_block = next(
                (
                    block
                    for block in media_blocks
                    if (block.get("mime_type") or "").startswith("image/")
                ),
                None,
            )
        else:
            user_text = str(last_content).strip()
            image_block = None

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
            _schedule_audit(
                user_id=user_id,
                turn_context={
                    "user_text": user_text,
                    "reply_text": str(reply.content),
                    "intent_type": "unsupported_transaction",
                },
                force=True,
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
        if image_block is not None:
            # Receipt-like photos (no caption, or expense words) go to expense extraction;
            # other photos go to the general multimodal assistant.
            lowered = user_text.lower()
            expense_hint = any(
                phrase in lowered
                for phrase in ("receipt", "expense", "spent", "paid", "bill", "cost", "$")
            )
            target_domain = "expenses" if (not lowered or expense_hint) else "general"
        else:
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
        _schedule_audit(
            user_id=user_id,
            turn_context={
                "user_text": user_text,
                "reply_text": str(output.message.content),
                "intent_type": intent_type,
            },
            force=False,
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
    from orchestrator.plan_router import plan_dispatch

    return await plan_dispatch(state)
