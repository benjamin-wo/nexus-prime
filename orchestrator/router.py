from dataclasses import dataclass, field
import asyncio
import json
import os
import re
from typing import Protocol, List, Dict, Any, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command
from langgraph.graph import END
from orchestrator.state import AssistantState
from capabilities.email.tools import (
    search_email_messages,
    discover_and_track_bank_domain,
    get_user_gmail_token,
    get_user_outlook_token,
    disconnect_email_account,
)
from capabilities.expenses.tools import (
    process_extracted_expense,
    extract_expense_from_text,
    extract_expense_from_photo,
    expense_source_id,
    log_expenses_from_emails,
    parse_incoming_transaction_text,
    save_income_transaction,
    income_source_id,
    is_duplicate_income,
    SPLIT_ALERT_THRESHOLD,
)
from capabilities.routes.tools import plan_route, extract_route_request
from capabilities.routes.journey import format_journey, plan_transit_journey
from capabilities.recipes.tools import (
    parse_recipe_and_extract_ingredients,
    sync_to_grocery_list,
)
from capabilities.reminders.tools import parse_reminder_request
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


def get_system_prompt(is_admin: bool, now: str) -> str:
    capabilities_desc = (
        "You can help with email, expenses, routes, recipes, reminders, whiteboard planning, and general questions."
        if is_admin
        else "You can help with email, expenses, routes, recipes, reminders/tasks, and general questions & trip planning."
    )
    return (
        "You are Nexus Prime, a personal AI assistant running as a Telegram bot for a close friend. "
        "You are warm, sharp, proactive, and resourceful — like a capable friend who actually helps build plans and solutions. "
        "Write like a human texting on Telegram: concise, natural, lowercase-friendly when it fits, "
        "light emoji where it adds warmth, and no corporate filler. "
        "When asked to plan a trip, itinerary, event, or recommendation, BE PROACTIVE: immediately give a concrete draft plan or schedule based on what the user shared, recommend real, exciting spots/activities, and suggest clear options. NEVER stall by asking a barrage of questionnaire questions — give them an actionable plan right away! "
        "Format for Telegram chat: short paragraphs, **bold** for key phrases, bullet lists starting "
        "with '-', no tables, no code fences, no headings with '#'. "
        "Never introduce yourself as a subagent or model; just be you. "
        "If you don't know something, say so honestly instead of making it up. "
        "NEVER state specific expenses, email contents/senders, transactions, or transit "
        "directions unless a tool call in this turn actually returned that data — if the "
        "relevant tool hasn't been invoked (or isn't connected), say so plainly and offer to "
        "check, instead of inventing plausible-sounding details. "
        f"Current Singapore time: {now}. "
        f"{capabilities_desc}"
    )


SYSTEM_PROMPT = get_system_prompt(is_admin=True, now="{now}")


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
    keywords = ["email", "gmail", "outlook", "hotmail", "inbox", "mail"]
    description = "Searches email providers and discovers bank domains automatically."

    async def execute(self, state: AssistantState) -> PluginOutput:
        user_id = state["user_id"]
        messages = state.get("messages", [])
        last_text = str(messages[-1].content) if messages else ""
        lowered_text = last_text.lower()
        from orchestrator.planner import (
            is_email_disconnect_request,
            is_latest_email_request,
            is_financial_email_request,
        )

        if is_email_disconnect_request(last_text):
            requested_provider = "all"
            if any(word in lowered_text for word in ("outlook", "hotmail", "microsoft mail", "office 365")):
                requested_provider = "outlook"
            elif any(word in lowered_text for word in ("gmail", "google mail")):
                requested_provider = "gmail"
            disconnected = await disconnect_email_account(
                user_id=user_id,
                provider=requested_provider,
            )
            if disconnected.get("count"):
                names = ", ".join(disconnected["disconnected"]).title()
                reply = (
                    f"🔌 Disconnected {names}. I will no longer read that mailbox or use it for "
                    "automatic expense tracking."
                )
            else:
                target = "your mailbox" if requested_provider == "all" else f"your {requested_provider} account"
                reply = f"ℹ️ No connected credential found for {target}."
            return PluginOutput(
                message=AIMessage(content=reply),
                state_update={"active_domain": self.name},
            )

        connection_intent = any(
            word in lowered_text
            for word in ("connect", "link", "integrat", "authoriz", "grant access", "set up", "setup")
        )
        requested_outlook = any(word in lowered_text for word in ("outlook", "hotmail", "microsoft mail", "office 365"))
        requested_gmail = any(word in lowered_text for word in ("gmail", "google mail"))

        # When the user names exactly one provider ("check outlook for...",
        # "see my gmail"), scope the search to that mailbox instead of merging
        # every connected provider. Without this, a user with both Gmail and
        # Outlook connected who explicitly asks about Outlook silently gets
        # Gmail's (irrelevant) results back with no indication Outlook was
        # ever queried — the exact "outlook fails terribly" report: the
        # assistant summarizes generic Gmail promos and finds no transactions,
        # with nothing in the reply signaling it never actually looked at
        # Outlook.
        requested_provider_scope: Optional[str] = None
        if requested_outlook and not requested_gmail:
            requested_provider_scope = "outlook"
        elif requested_gmail and not requested_outlook:
            requested_provider_scope = "gmail"

        # One-time mailbox authorization: the bot can't read email until the user consents.
        # Offer whichever providers are still missing (Gmail and/or Outlook).
        gmail_token = await get_user_gmail_token(user_id)
        outlook_token = await get_user_outlook_token(user_id)
        needs_gmail = bool(settings.google_client_id and settings.google_client_secret) and not gmail_token
        needs_outlook = bool(settings.microsoft_client_id and settings.microsoft_client_secret) and not outlook_token

        # Show missing provider links even when another provider is already
        # connected. This is especially important for "connect Outlook" after
        # Gmail has already been authorized.
        missing_requested_provider = (
            (requested_outlook and needs_outlook)
            or (requested_gmail and needs_gmail)
        )
        no_mailbox_connected = not gmail_token and not outlook_token
        if missing_requested_provider or (no_mailbox_connected and (needs_gmail or needs_outlook)):
            public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
            base = (
                f"https://{public_domain}".rstrip("/")
                if public_domain
                else (settings.webapp_url or "").rstrip("/")
            )
            lines = [
                "🔐 I can check your email — I just need one-time access from you.",
                "Open a link and allow read-only access; I'll ping you here when it's connected:",
            ]
            if needs_gmail and (not connection_intent or requested_gmail or not requested_outlook):
                lines.append(f"🟢 Gmail: {base}/auth/gmail?user_id={user_id}")
            if needs_outlook and (not connection_intent or requested_outlook or not requested_gmail):
                lines.append(f"🔵 Outlook: {base}/auth/outlook?user_id={user_id}")
            return PluginOutput(
                message=AIMessage(content="\n".join(lines)),
                state_update={"active_domain": self.name},
            )

        # Informational "check the latest email" requests fetch the true newest
        # messages (no financial keyword, no expense auto-logging). A generic
        # sweep here is why "check my latest email" used to return stale receipts.
        # Real phrasings ("did you see the DBS email today?") rarely match the
        # literal "latest email" list, so latest is the DEFAULT for any email
        # request without an explicit financial intent; the keyword sweep runs
        # only for receipt/bill/expense/bank asks.
        if is_latest_email_request(last_text) or not is_financial_email_request(last_text):
            latest_results = await search_email_messages.ainvoke(
                {"user_id": user_id, "latest": True, "provider": requested_provider_scope}
            )
            reply = AIMessage(content=await self._summarize_email_results(latest_results, latest=True))
            return PluginOutput(
                message=reply,
                state_update={"active_domain": self.name},
            )

        results = await search_email_messages.ainvoke(
            {"user_id": user_id, "provider": requested_provider_scope}
        )
        if results:
            for msg in results:
                sender = msg.get("sender", "")
                if sender:
                    await discover_and_track_bank_domain(user_id, sender)

        # Auto-log expenses found in the fetched emails (deduped by email ID).
        # notify=False: this is a user-initiated chat request, so no separate Telegram push —
        # the reply below already announces everything (and the sweep path stays the snitch).
        expense_result = await log_expenses_from_emails.ainvoke(
            {"user_id": user_id, "emails": results, "notify": False}
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
            if any(item["amount"] >= SPLIT_ALERT_THRESHOLD for item in logged):
                lines.append("\n💡 Big bill? Reply /split to split it with friends.")
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
    async def _summarize_email_results(results: List[Dict[str, Any]], latest: bool = False) -> str:
        """Summarize fetched emails with the agent LLM, or fall back to a plain list."""
        if not results:
            if latest:
                return "📬 I couldn't find any emails in your mailbox right now."
            return (
                "📬 I checked your inbox — nothing expense-related in the last week. "
                "Want me to look at a specific sender or date range?"
            )

        fallback_lines = [
            f"• {msg.get('sender', '?')}: {msg.get('subject', '(no subject)')}"
            for msg in results[:5]
        ]
        fallback = "📬 Here's what I found in your inbox:\n" + "\n".join(fallback_lines)

        if not settings.has_llm_key:
            return fallback

        try:
            llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.4)
            emails_text = json.dumps(results[:8], indent=1, default=str)
            ai_message = await llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are Nexus Prime, the user's personal assistant on Telegram. "
                            "You just fetched emails from their inbox. Summarize them "
                            "conversationally in 2-5 short lines: name the senders and what "
                            "each message is about, and flag anything that looks like a bill, "
                            "receipt, or expense. "
                            "Only describe emails present in the provided JSON. Never invent, "
                            "guess, or reconstruct senders, subjects, amounts, or dates that are "
                            "not listed; if an email lacks a subject or body, say so instead of "
                            "making one up. Do not mention that you are a subagent."
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
    keywords = [
        "expense", "spent", "paid", "receipt", "starbucks", "dollar", "$",
        "received", "salary", "payroll", "repaid", "reimbursement", "claim", "credited",
    ]
    description = "Processes spending, incoming money, receipts, and financial expenses with HITL confirmation."

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

        incoming = parse_incoming_transaction_text(last_text)
        if incoming is not None:
            return await self._finalize_income(
                user_id,
                incoming,
                income_source_id(user_id, last_text),
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
                "my transactions",
                "transaction history",
                "transaction summary",
                "my income",
                "income summary",
                "how much did i receive",
                "how much have i received",
                "net cashflow",
                "cash flow",
            )
        )
        if list_intent:
            from capabilities.expenses.tools import query_unified_transactions
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

            if settings.has_llm_key:
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
                        "- 'salary', 'repayment', 'reimbursement', 'refund', 'income', 'money in' → leave categories null so money-in rows are not filtered out\n"
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

            ledger = await query_unified_transactions(
                user_id=user_id,
                direction="all",
                categories=intent_filters["categories"],
                since_date=intent_filters["since_date"],
                until_date=intent_filters["until_date"],
                limit=50,
            )

            label = intent_filters["label"]
            money_out = ledger["money_out"]
            money_in = ledger["money_in"]
            rows = ledger["items"]
            if not rows:
                reply = (
                    f"💰 No transactions found for *{label}*. "
                    "Try *\"spent $12.50 at Starbucks\"* or ask me to scan your email for receipts."
                )
            else:
                currencies = sorted(set(money_out) | set(money_in))
                currency = currencies[0] if len(currencies) == 1 else None
                spent = sum(b["total"] for b in money_out.values())
                earned = sum(b["total"] for b in money_in.values())
                count = ledger["total_matched"]
                header_amounts: List[str] = []
                if currency is None:
                    for cur, bucket in sorted(money_out.items()):
                        header_amounts.append(f"-{cur} {bucket['total']:.2f}")
                    for cur, bucket in sorted(money_in.items()):
                        header_amounts.append(f"+{cur} {bucket['total']:.2f}")
                    header = f"💰 *{label.title()}*: **{' / '.join(header_amounts)}**" if header_amounts else ""
                else:
                    header = (
                        f"💰 *{label.title()}* — out **-{currency} {spent:.2f}**, "
                        f"in **+{currency} {earned:.2f}**, net "
                        f"**{earned - spent:+.2f} {currency}**"
                    )
                if intent_filters["summary_only"]:
                    reply = header or (
                        f"💰 Nothing recorded for *{label}* yet."
                    )
                else:
                    count_word = f"{count} transaction{'s' if count != 1 else ''}"
                    lines = [f"{header} across {count_word}:"] if header else [f"💰 {label.title()}:"]
                    for row in rows[:15]:
                        mark = "-" if row["direction"] == "outgoing" else "+"
                        title = row["title"]
                        lines.append(
                            f"• {row['date'][:10]} {mark}{row['currency']} {row['amount']:.2f} — "
                            f"{title} ({row['category']})"
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
        split_hint = ""
        if (
            status in ("saved_silently", "confirmed_by_user")
            and float(extracted["amount"]) >= SPLIT_ALERT_THRESHOLD
        ):
            split_hint = (
                f"\n💡 Over {extracted.get('currency', 'SGD')} {SPLIT_ALERT_THRESHOLD:.0f}"
                f" — split with friends anytime: "
                f"*'/split {extracted['amount']:.2f} {extracted['merchant']} with [names]'*."
            )
        if status == "saved_silently":
            reply = (
                f"💰 Logged *{extracted.get('currency', 'SGD')} {extracted['amount']:.2f}* "
                f"at *{extracted['merchant']}* ({extracted.get('category', 'General')})."
            ) + split_hint
        elif status == "duplicate":
            reply = "🙅 That expense is already logged."
        elif status == "confirmed_by_user":
            reply = (
                f"✅ Saved {extracted.get('currency', 'SGD')} {extracted['amount']:.2f} "
                f"at {extracted['merchant']}."
            ) + split_hint
        else:
            reply = f"💰 Found {extracted['amount']:.2f} at {extracted['merchant']} — confirm below."
        return PluginOutput(message=reply, state_update={"active_domain": "expenses"})

    @staticmethod
    async def _finalize_income(
        user_id: int,
        parsed: Dict[str, Any],
        source_id: str,
    ) -> PluginOutput:
        """Save an explicit incoming-money message once and confirm the result."""
        if parsed.get("category") == "Friend Repayment":
            from capabilities.expenses.settlement import settle_matching_iou

            received_at = None
            try:
                received_at = datetime.fromisoformat(
                    str(parsed.get("date_iso") or "").replace("Z", "+00:00")
                )
            except ValueError:
                pass
            settlement = await settle_matching_iou(
                user_id=user_id,
                participant=str(parsed.get("source") or ""),
                amount=float(parsed.get("amount") or 0.0),
                received_at=received_at,
                notes=str(parsed.get("notes") or "").strip() or None,
            )
            if settlement is not None and settlement.get("status") in {
                "settled",
                "partially_settled",
                "already_settled",
            }:
                status = settlement["status"]
                if status == "already_settled":
                    reply = (
                        f"ℹ️ {settlement['participant']}'s repayment is already marked as paid "
                        f"({settlement['currency']} {settlement['amount_due']:.2f})."
                    )
                elif status == "partially_settled":
                    outstanding = settlement["amount_due"] - settlement["total_received"]
                    reply = (
                        f"💵 Logged {settlement['currency']} {settlement['amount_received']:.2f} from "
                        f"{settlement['participant']}. Their IOU still has "
                        f"{settlement['currency']} {outstanding:.2f} outstanding."
                    )
                else:
                    reply = (
                        f"✅ Logged {settlement['currency']} {settlement['amount_received']:.2f} from "
                        f"{settlement['participant']} and marked their IOU as paid."
                    )
                return PluginOutput(
                    message=AIMessage(content=reply),
                    state_update={"active_domain": "expenses"},
                )

        if await is_duplicate_income(source_id):
            return PluginOutput(
                message=AIMessage(content="↩️ That incoming transaction is already logged."),
                state_update={"active_domain": "expenses"},
            )

        item = await save_income_transaction(
            user_id=user_id,
            income=parsed,
            source_message_id=source_id,
        )
        reply = (
            f"💵 Logged *{item.currency} {item.amount:.2f}* from *{item.source}* "
            f"({item.category})."
        )
        return PluginOutput(
            message=AIMessage(content=reply),
            state_update={"active_domain": "expenses"},
        )


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

    @staticmethod
    def _generate_rule_based_response(text: str) -> str:
        """Graceful conversational fallback for greetings and standard queries if LLM quota is unavailable."""
        text_lower = text.strip().lower()
        
        # Greetings
        greetings = ["hello", "hi", "hey", "hola", "yo", "sup", "good morning", "good afternoon", "good evening", "howdy", "hiya", "start", "/start"]
        if any(text_lower == g or text_lower.startswith(f"{g} ") or text_lower.startswith(f"{g}!") or text_lower.startswith(f"{g},") for g in greetings):
            return (
                "Hey there! 👋 I'm **Nexus Prime**, your personal assistant.\n\n"
                "Here is what I can help you with:\n"
                "• 💰 **Track Expenses**: Send *Spent $14 on lunch* or upload receipt photos\n"
                "• 👥 **Split Bills**: Send */split $60 with Alice and Bob*\n"
                "• ⏰ **Reminders & Tasks**: Send *Remind me to call Mom at 6pm*\n"
                "• 📊 **Dashboard**: Tap /dashboard to view your live cockpit & ledger\n\n"
                "What would you like to do today?"
            )
            
        # Thanks / acknowledgement
        if any(w in text_lower for w in ["thank", "thanks", "thx", "appreciate", "cheers"]):
            return "You're very welcome! Let me know if there's anything else you need. 😊"
            
        # How are you / status
        if any(phrase in text_lower for phrase in ["how are you", "how's it going", "how r u", "whats up", "what's up"]):
            return "I'm doing great and ready to assist! What can I help you tackle today? 🚀"
            
        # Help / capabilities
        if any(phrase in text_lower for phrase in ["help", "what can you do", "who are you", "what are your features", "commands", "/help"]):
            return (
                "🤖 **Nexus Prime Capabilities**\n\n"
                "• 💰 **Expenses**: Track spending (*$15 Starbucks*), summarize budgets, and view charts.\n"
                "• 🧾 **Receipt Scanner**: Upload or forward receipt photos for automatic scanning.\n"
                "• 👥 **Bill Splitting**: Easily split dining or group costs and request PayNow/shares.\n"
                "• ⏰ **Tasks & Reminders**: Schedule smart timed reminders in plain English.\n"
                "• 📊 **Web Dashboard**: Access your real-time cockpit via /dashboard.\n\n"
                "Type /help anytime for interactive command shortcuts!"
            )
            
        # General friendly fallback
        return (
            "I'm here to help! You can ask me to track expenses (*Spent $15 on lunch*), split a bill (*"
            "/split $50 with Sam*), set reminders (*Remind me at 4pm*), or tap /dashboard to view your cockpit.\n\n"
            "How can I assist you right now?"
        )

    async def execute(self, state: AssistantState) -> PluginOutput:
        messages = state.get("messages", [])
        now_sg = datetime.now(ZoneInfo("Asia/Singapore")).strftime("%A, %d %b %Y %H:%M")
        if len(messages) > 12:
            pruned, _ = prune_and_summarize_messages(messages, threshold=12)
        else:
            pruned = messages
        user_id = state.get("user_id")
        is_admin = settings.is_admin(user_id)
        history = [SystemMessage(content=get_system_prompt(is_admin=is_admin, now=now_sg))]
        # Iterate the full `pruned` list (already bounded by prune_and_summarize_messages
        # to <=12 raw messages, or 1 summary note + the last 10) rather than re-slicing
        # it with [-8:] — that used to cut off the summary note at index 0 whenever
        # pruning actually triggered, silently dropping everything before the last ~8
        # turns with no compensating summary. Also handle SystemMessage explicitly:
        # the summary note is a SystemMessage and was previously falling through this
        # if/elif unrecognized, so it was never added to `history` even when it survived
        # the slice.
        for message in pruned:
            if isinstance(message, SystemMessage):
                history.append(SystemMessage(content=str(message.content)))
            elif isinstance(message, HumanMessage):
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

        last_text = str(last_content) if not isinstance(last_content, list) else ""

        # Bounded tool loop: the model itself decides when to search the web or read
        # the transaction ledger. Import lazily: tests monkeypatch
        # capabilities.general.tools.search_web, which requires late binding.
        from capabilities.general.tools import query_transactions, search_web

        available_tools = [search_web, query_transactions]

        # Tests and local runs use placeholder keys; skip network call if no provider is configured.
        has_key = bool(settings.active_gemini_api_key or (settings.deepseek_api_key and settings.deepseek_api_key != "test_deepseek_key"))
        if not has_key:
            content = self._generate_rule_based_response(last_text)
            return PluginOutput(
                message=AIMessage(content=content),
                state_update={"active_domain": self.name},
            )

        try:
            llm = get_agent_llm(complexity=ThinkingLevel.MEDIUM, temperature=0.7)
            llm_with_tools = llm.bind_tools(available_tools)
            ai_message = await llm_with_tools.ainvoke(history)

            MAX_TOOL_ROUNDS = 3
            for _round in range(MAX_TOOL_ROUNDS):
                tool_calls = getattr(ai_message, "tool_calls", None) or []
                if not tool_calls:
                    break
                history.append(ai_message)
                for call in tool_calls:
                    call_name = str(call.get("name") or "")
                    call_args = dict(call.get("args") or {})
                    if call_name == "query_transactions":
                        # Identity guard: never trust a model-supplied user_id.
                        call_args["user_id"] = int(user_id or 0)
                    tool_obj = next((t for t in available_tools if t.name == call_name), None)
                    if tool_obj is None:
                        observation: Any = f"[{call_name}] Unknown tool."
                    else:
                        try:
                            observation = await tool_obj.ainvoke(call_args)
                        except Exception as tool_exc:  # noqa: BLE001
                            print(f"[GENERAL] tool {call_name} failed: {tool_exc}")
                            observation = f"[{call_name}] failed: {tool_exc}"
                    history.append(
                        ToolMessage(
                            content=str(observation),
                            tool_call_id=str(call.get("id") or call_name),
                        )
                    )
                ai_message = await llm_with_tools.ainvoke(history)

            content = extract_llm_text(getattr(ai_message, "content", "")).strip()
            if not content:
                if getattr(ai_message, "tool_calls", None):
                    history.append(ai_message)
                    for call in ai_message.tool_calls:
                        history.append(
                            ToolMessage(
                                content="[tool] Round budget exhausted; answer from what you have.",
                                tool_call_id=str(call.get("id") or call.get("name") or ""),
                            )
                        )
                    final_message = await llm.ainvoke(history)
                    content = extract_llm_text(getattr(final_message, "content", "")).strip()
                if not content:
                    content = self._generate_rule_based_response(last_text)
        except Exception as exc:  # noqa: BLE001 - never let LLM errors kill the webhook
            print(f"[GENERAL] LLM/tool loop failed, using fallback: {exc}")
            content = self._generate_rule_based_response(last_text)

        return PluginOutput(
            message=AIMessage(content=content),
            state_update={"active_domain": self.name},
        )

    @staticmethod
    async def _execute_multimodal(history: List[Any]) -> PluginOutput:
        """Answer image/audio messages with Gemini's multimodal model."""
        if (
            not settings.active_gemini_api_key
            or settings.active_gemini_api_key == "test_google_key"
        ):
            return PluginOutput(
                message=AIMessage(
                    content=(
                        "I got your photo/voice, but my vision model isn't configured "
                        "on this deployment yet (GEMINI_API_KEY missing)."
                    )
                ),
                state_update={"active_domain": "general"},
            )

        try:
            llm = get_multimodal_llm(temperature=0.2)
            ai_message = await llm.ainvoke(history)
            content = extract_llm_text(getattr(ai_message, "content", "")).strip()
            if not content:
                content = "I processed your media message, but couldn't generate a description."
        except Exception as exc:  # noqa: BLE001
            print(f"[GENERAL] multimodal call failed: {exc}")
            content = (
                "Hmm, I couldn't analyze that just now — my vision model hit an error. "
                "Mind sending it again?"
            )

        return PluginOutput(
            message=AIMessage(content=content),
            state_update={"active_domain": "general"},
        )


class ReminderPlugin:
    """Sets one-time timers and recurring cron-based reminders on Telegram."""

    name = "reminders"
    keywords = ["remind", "reminder", "schedule", "cron", "alarm", "timer"]
    description = "Sets one-time timers and recurring reminders on Telegram."

    async def execute(self, state: AssistantState) -> PluginOutput:
        user_id = state["user_id"]
        messages = state.get("messages", [])
        last_text = str(messages[-1].content) if messages else ""

        parsed = await parse_reminder_request.ainvoke({"user_text": last_text})
        action = parsed.get("action")

        if action == "list":
            jobs = await list_active_jobs(user_id=user_id)
            if not jobs:
                reply = "📋 No active reminders. Try *\"remind me in 5 minutes to check oven\"* or *\"remind me to drink water every 2 hours\"*."
            else:
                lines = ["📋 **Active Reminders & Timers**:"]
                for job in jobs:
                    next_run = job.get("next_run_time") or "not scheduled"
                    sched_desc = f"`{job['cron_expression']}`" if job.get("type") == "recurring" else "one-time"
                    lines.append(
                        f"- #{job['job_id']} *{job['job_name']}* "
                        f"({sched_desc} @ {job['timezone']}, next: {next_run})"
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

        reminder_type = parsed.get("reminder_type", "recurring")
        delay_seconds = parsed.get("delay_seconds")
        message_text = (parsed.get("message") or "").strip()
        timezone = parsed.get("timezone") or "Asia/Singapore"

        # 1. ONE-TIME RELATIVE REMINDER
        if reminder_type == "once" or delay_seconds is not None:
            if not message_text:
                message_text = "Reminder"
            from core.scheduler import schedule_one_shot_reminder
            import zoneinfo
            try:
                tz = zoneinfo.ZoneInfo(timezone)
            except Exception:
                tz = zoneinfo.ZoneInfo("Asia/Singapore")

            delay = int(delay_seconds) if delay_seconds else 60
            now_local = datetime.now(tz)
            run_time = now_local + timedelta(seconds=delay)

            try:
                task = await schedule_one_shot_reminder(
                    user_id=user_id,
                    message=message_text,
                    run_date=run_time,
                    timezone_str=timezone,
                )
                if delay < 60:
                    time_desc = f"{delay}s"
                elif delay == 60:
                    time_desc = "1 minute"
                elif delay < 3600:
                    mins = delay // 60
                    time_desc = f"{mins} minute{'s' if mins != 1 else ''}"
                elif delay < 86400:
                    hrs = delay // 3600
                    time_desc = f"{hrs} hour{'s' if hrs != 1 else ''}"
                else:
                    days = delay // 86400
                    time_desc = f"{days} day{'s' if days != 1 else ''}"

                time_str = run_time.strftime("%I:%M %p").lstrip("0")
                reply = (
                    f"⏰ **Reminder set** (#{task.id}): *\"{message_text}\"*\n"
                    f"I'll ping you in **{time_desc}** (at {time_str})."
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[REMINDERS] one-shot schedule failed: {exc}")
                reply = f"⚠️ Couldn't schedule reminder: {exc}"

            return PluginOutput(
                message=AIMessage(content=reply),
                state_update={"active_domain": self.name},
            )

        # 2. RECURRING CRON REMINDER
        cron = (parsed.get("cron") or "").strip()
        from capabilities.reminders.tools import has_recurrence_keyword

        if not message_text or not cron or not has_recurrence_keyword(last_text):
            reply = (
                "I can set reminders — try *\"remind me in 5 minutes to check oven\"*, "
                "*\"remind me tomorrow at 9am to call mom\"* "
                "or *\"remind me to drink water every 2 hours\"*."
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
                aps_job.next_run_time.strftime("%a, %b %d at %I:%M %p")
                if (aps_job and aps_job.next_run_time)
                else "soon"
            )
            reply = (
                f"✅ **Recurring reminder set** (#{job.id}): *\"{message_text}\"*\n"
                f"Schedule: `{cron}` ({timezone})\nNext run: {next_run}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[REMINDERS] recurring schedule failed: {exc}")
            reply = (
                f"⚠️ Couldn't parse *\"{cron}\"* as a schedule — try something like "
                "*\"every 2 hours\"* or *\"daily at 9pm\"*."
            )
        return PluginOutput(
            message=AIMessage(content=reply),
            state_update={"active_domain": self.name},
        )


class WhiteboardPlugin:
    """Conversational whiteboard capability: create boards, list them, summarize,
    pin notes, and add checklist cards — backed by the shared whiteboard tools."""

    name = "whiteboard"
    keywords = [
        "whiteboard", "white board", "boards", " board", "planning canvas",
        "plan a trip", "trip to", "itinerary", "shortlist", "packing list",
        "pin to", "pin this", "pin that", "pin it", "brainstorm",
        "plan my", "plan our", "plan for", "plan dinner", "plan the",
    ]
    description = "Create and manage living planning boards (trips, events, projects, meal plans)."

    _CATEGORY_HINTS = [
        (("trip", "travel", "vacation", "holiday", "getaway", "tour"), "trip"),
        (("meal", "food", "dinner", "lunch", "grocer", "recipe", "cook", "menu"), "meal"),
        (("party", "wedding", "event", "birthday", "celebration", "gathering"), "event"),
        (("startup", "mvp", "launch", "feature", "sprint", "roadmap", "project"), "project"),
    ]

    @classmethod
    def _guess_category(cls, text: str) -> str:
        lowered = (text or "").lower()
        for needles, category in cls._CATEGORY_HINTS:
            if any(n in lowered for n in needles):
                return category
        return "general"

    @staticmethod
    def _clean_board_title(raw: str) -> str:
        title = (raw or "").strip().strip("?!. ").strip()
        title = re.sub(
            r"^(?:a|an|the|my|our|new|another)\s+",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
        title = re.sub(r"\s+(board|whiteboard|canvas|planner)$", "", title, flags=re.IGNORECASE).strip()
        if title:
            title = title[0].upper() + title[1:]
        return title or "New Board"

    @staticmethod
    def _extract_board_ref(text: str) -> str:
        """Pull the board-name fragment out of phrases like '... to my tokyo board'."""
        ref = re.sub(
            r"^(?:pin|add)\b[^to]*?\bto\s+(?:my|the|our)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        ref = re.sub(r"\s*(?:board|whiteboard|canvas)s?\s*$", "", ref, flags=re.IGNORECASE).strip()
        return ref

    def _parse_intent(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        lowered = raw.lower()

        if re.search(r"\b(show|list|view|what|my)\b.*\b(boards|whiteboards)\b", lowered) or lowered.startswith("/boards"):
            return {"action": "list"}

        # Capture groups run against the original text so user casing survives.
        pin_match = re.search(r"\bpin\b(.+?)\b(?:to|on)\b(.+)", raw, re.IGNORECASE)
        if pin_match:
            return {
                "action": "pin",
                "content": re.sub(r"^(this|that|it)\b\s*", "", pin_match.group(1).strip(), flags=re.IGNORECASE),
                "board_ref": self._extract_board_ref("pin to " + pin_match.group(2).strip()),
            }

        add_match = re.search(
            r"\badd\s+(?:a\s+)?(note|checklist|card|todo|to-do)?\s*(.*?)\s*(?:to|on)\s+(?:my|the|our)?\s*(.+?)\s*(?:boards?|whiteboards?|canvas)?\s*$",
            raw,
            re.IGNORECASE,
        )
        if add_match and add_match.group(2):
            return {
                "action": "add_card",
                "kind": (add_match.group(1) or "note").lower(),
                "content": add_match.group(2).strip(),
                "board_ref": add_match.group(3).strip(),
            }

        summary_match = re.search(
            r"(?:what(?:'s| is)|show me|summar\w+|overview of)\s+(?:on\s+|of\s+)?(?:my|the|our)?\s*(.+?)\s*(?:boards?|whiteboards?|canvas)\b",
            raw,
            re.IGNORECASE,
        )
        if summary_match:
            return {"action": "summary", "board_ref": summary_match.group(1).strip()}

        create_match = re.search(
            r"^(?:plan|create|start|make|new)\s+(?:a\s+|an\s+|my\s+|our\s+|the\s+|new\s+)*(?:board|whiteboard|canvas)?\s*(?:for|called|named|to)?\s*(.*)$",
            raw,
            re.IGNORECASE,
        )
        if create_match and (create_match.group(1) or "board" in lowered or "whiteboard" in lowered or "canvas" in lowered):
            remainder = create_match.group(1) or ""
            if remainder or re.search(r"\b(board|whiteboard|canvas)\b", lowered):
                return {"action": "create", "topic": remainder or "Untitled"}

        return {"action": None}

    async def execute(self, state: AssistantState) -> PluginOutput:
        from capabilities.whiteboard import tools as wb

        user_id = state["user_id"]
        messages = state.get("messages", [])
        last_text = str(messages[-1].content) if messages else ""

        intent = self._parse_intent(last_text)
        action = intent.get("action")

        if action == "list":
            boards = await wb.list_user_boards(user_id)
            if not boards:
                reply = (
                    "🎨 You have no boards yet. Say *\"plan a trip to Tokyo\"* or "
                    "*\"new board for my startup\"* and I'll create one."
                )
            else:
                lines = ["🎨 **Your Planning Boards**:"]
                for b in boards[:10]:
                    lines.append(
                        f"- {b.emoji_icon} *{b.title}* (`#{b.id}` · {b.category})"
                    )
                lines.append("\n💡 Ask me *\"what's on my Tokyo board\"* or *\"pin this to my Tokyo board\"*.")
                reply = "\n".join(lines)
            return PluginOutput(message=AIMessage(content=reply), state_update={"active_domain": self.name})

        if action == "summary":
            board = await wb.find_board(user_id, intent.get("board_ref", ""))
            if not board:
                reply = "🤔 I couldn't find that board. Send *my boards* to see them all."
            else:
                summary = await wb.board_summary_text(board.id)
                reply = summary or f"{board.emoji_icon} *{board.title}* is empty."
            return PluginOutput(message=AIMessage(content=reply), state_update={"active_domain": self.name})

        if action == "create":
            topic = self._clean_board_title(intent.get("topic", ""))
            category = self._guess_category(topic)
            emoji = {"trip": "✈️", "meal": "🛒", "event": "🎉", "project": "🚀", "general": "📋"}.get(category, "📋")
            board = await wb.create_board(user_id=user_id, title=topic, category=category, emoji_icon=emoji)
            sections = ", ".join(board.section_order or [])
            reply = (
                f"🎨 Created {emoji} *{board.title}* (#{board.id}, {category}).\n"
                f"Sections: {sections}.\n"
                f"Open the Whiteboard tab to fill it in — or ask me to *pin* ideas to it."
            )
            return PluginOutput(message=AIMessage(content=reply), state_update={"active_domain": self.name})

        if action in ("pin", "add_card"):
            board_ref = intent.get("board_ref", "")
            board = await wb.find_board(user_id, board_ref)
            if not board:
                boards = await wb.list_user_boards(user_id)
                names = ", ".join(f"{b.emoji_icon} {b.title}" for b in boards[:5]) or "none yet"
                reply = (
                    f"🤔 Which board? I found: {names}.\n"
                    f"Try *\"pin this to my <board name> board\"*."
                )
                return PluginOutput(message=AIMessage(content=reply), state_update={"active_domain": self.name})

            raw_content = (intent.get("content") or "").strip()
            if not raw_content:
                raw_content = re.sub(
                    r"^\s*pin\b.*?\bto\b.*$|^\s*add\b.*?\bto\b.*$",
                    "",
                    last_text,
                    flags=re.IGNORECASE,
                ).strip() or last_text

            if action == "add_card" and intent.get("kind") in ("checklist", "todo", "to-do"):
                items = [ln.strip("-*• ").strip() for ln in raw_content.split("\n") if ln.strip()]
                block = await wb.add_block_to_whiteboard(
                    project_id=board.id,
                    section_name="Checklist",
                    block_type="checklist",
                    title=(raw_content.split("\n")[0] or "Checklist")[:200],
                    content_payload={"items": [{"id": f"c-{i + 1}", "text": t, "checked": False} for i, t in enumerate(items)]},
                )
                reply = f"☑️ Added checklist *{block.title}* to {board.emoji_icon} *{board.title}* (#{board.id})."
            else:
                block = await wb.add_block_to_whiteboard(
                    project_id=board.id,
                    section_name="Pinned",
                    block_type="note",
                    title=raw_content[:200] or "Pinned note",
                    content_payload={"markdown": raw_content},
                )
                reply = f"📌 Pinned to {board.emoji_icon} *{board.title}* (#{board.id}) as card #{block.id}."
            return PluginOutput(message=AIMessage(content=reply), state_update={"active_domain": self.name})

        # action is None → deep-reasoning planning intake (create/augment from freeform text)
        planned = await self._planning_intake(user_id, last_text)
        if planned is not None:
            return PluginOutput(
                message=AIMessage(content=planned),
                state_update={"active_domain": self.name},
            )

        reply = (
            "🎨 I can run your planning boards from chat:\n"
            "• *\"I want to plan a trip to Bali 3rd-6th Sept...\"* — I'll build the board, "
            "capture bookings, and research the gaps\n"
            "• *\"My boards\"* — list them\n"
            "• *\"What's on my Tokyo board?\"* — summarize\n"
            "• *\"Pin this to my Tokyo board: try the ramen at Ichiran\"* — pin a note"
        )
        return PluginOutput(message=AIMessage(content=reply), state_update={"active_domain": self.name})

    async def _planning_intake(self, user_id: int, last_text: str) -> Optional[str]:
        """Deep comprehension pass: decompose a freeform request into board cards,
        research topics, and follow-up questions. Returns None when the request
        is not planning-related (caller falls back to guidance)."""
        from capabilities.whiteboard import tools as wb
        from capabilities.whiteboard.planner import (
            ENTITY_SECTION_DEFAULTS,
            comprehend_request,
        )

        boards = await wb.list_user_boards(user_id)
        target_board = None
        explicit_match = False
        if boards:
            # 1. Explicit title fragment match in the message
            for b in boards[:3]:
                first_word = next((w for w in re.split(r"\W+", last_text.lower()) if len(w) > 3), "")
                if first_word and first_word in b.title.lower():
                    target_board = b
                    explicit_match = True
                    break
            # 2. Durable pointer: the user's last touched board (survives restarts)
            if target_board is None:
                try:
                    target_board = await wb.get_last_board(user_id)
                    explicit_match = target_board is not None
                except Exception:  # noqa: BLE001
                    target_board = None
            # 3. Recency fallback within 48h
            if target_board is None:
                try:
                    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

                    recent = boards[0]
                    updated = recent.updated_at
                    if updated and updated.tzinfo is None:
                        updated = updated.replace(tzinfo=_tz.utc)
                    if updated and (_dt.now(_tz.utc) - updated) < _td(hours=48):
                        target_board = recent
                except Exception:  # noqa: BLE001
                    target_board = None

        board_context = None
        if target_board is not None:
            details = await wb.fetch_whiteboard_details(target_board.id)
            sections = sorted({b["section_name"] for b in (details or {}).get("blocks", [])})
            board_context = {
                "id": target_board.id,
                "title": target_board.title,
                "category": target_board.category,
                "sections": sections,
                "explicit_match": explicit_match,
            }

        brief = await comprehend_request(last_text, board_context)
        if not brief or brief.get("action") == "none":
            return None

        emoji_map = {"trip": "✈️", "meal": "🛒", "event": "🎉", "project": "🚀", "general": "📋"}
        emoji = emoji_map.get(brief.get("category"), "📋")

        # 1. Create or augment the board
        if brief["action"] == "augment_board" and target_board is not None:
            board = target_board
        else:
            existing = await wb.find_board(user_id, brief["board_title"])
            board = existing or await wb.create_board(
                user_id=user_id,
                title=brief["board_title"],
                category=brief.get("category") or "general",
                emoji_icon=emoji,
                summary=brief.get("summary"),
            )
        try:
            await wb.set_last_board(user_id, board.id)
        except Exception:  # noqa: BLE001 - pointer persistence must never break intake
            pass

        # 2. Materialize entities as cards (grouped by section)
        created_cards: List[tuple] = []
        section_for_kind = dict(ENTITY_SECTION_DEFAULTS)
        for entity in brief.get("entities", []):
            kind = entity.get("kind", "note")
            status = entity.get("status", "tbd")
            status_badge = {"booked": "✅ Booked", "confirmed": "📍 Confirmed", "tbd": "💭 Idea"}.get(status, "")
            markdown_parts = []
            if status_badge:
                markdown_parts.append(f"**{status_badge}**")
            if entity.get("details"):
                markdown_parts.append(entity["details"])
            block = await wb.add_block_to_whiteboard(
                project_id=board.id,
                section_name=section_for_kind.get(kind, "Notes"),
                block_type="note",
                title=entity.get("title", "Untitled")[:200],
                content_payload={"markdown": "\n\n".join(markdown_parts)},
            )
            created_cards.append((section_for_kind.get(kind, "Notes"), block))

        # 3. Skeleton itinerary when a date range exists and no itinerary-typed card yet
        date_range = brief.get("date_range")
        if date_range:
            await wb.add_block_to_whiteboard(
                project_id=board.id,
                section_name="Itinerary",
                block_type="itinerary",
                title=f"Skeleton: {date_range}",
                content_payload={"steps": []},
            )
            created_cards.append(("Itinerary", None))

        # 4. Research pass — concurrent web searches, capped
        research_queries = brief.get("research_queries") or []
        findings_lines: List[str] = []
        research_topics: List[Dict[str, Any]] = []
        if research_queries:
            from capabilities.general.tools import search_web

            async def _run(query: str):
                try:
                    return query, await asyncio.wait_for(
                        search_web.ainvoke({"query": query}), timeout=25
                    )
                except Exception as exc:  # noqa: BLE001
                    return query, f"[search failed: {exc}]"

            results = await asyncio.gather(*[_run(q) for q in research_queries])
            for query, raw_result in results:
                snippet = str(raw_result).strip()
                # Keep the summary line + top 2 result bullets per topic, trimmed
                # to a clean word boundary (Tavily cuts mid-word).
                lines = [ln.strip() for ln in snippet.split("\n") if ln.strip()][:3]

                def _clean(line: str, cap: int = 200) -> str:
                    if len(line) <= cap:
                        return line
                    cut = line[:cap]
                    stop = max(cut.rfind(". "), cut.rfind(", "), cut.rfind(" "))
                    return cut[:stop + 1].rstrip(" ,") if stop > 40 else cut.rstrip() + "…"

                lines = [_clean(ln) for ln in lines]
                condensed = "\n".join(lines)[:700]
                findings_lines.append(f"**{query}**\n{condensed}")

                summary_line = next(
                    (line[len("Summary:"):].strip() for line in lines if line.lower().startswith("summary:")),
                    "",
                )
                sources = []
                for line in lines:
                    source_match = re.match(r"^[-*•]\s+(.+?)\s+\((https?://[^)]+)\)", line)
                    if source_match:
                        sources.append({
                            "title": source_match.group(1).strip()[:120],
                            "url": source_match.group(2).strip()[:400],
                        })
                research_topics.append({
                    "query": query[:160],
                    "summary": summary_line[:300],
                    "sources": sources[:3],
                })

            if findings_lines:
                await wb.add_block_to_whiteboard(
                    project_id=board.id,
                    section_name="🔍 Research",
                    block_type="note",
                    title="Auto-research findings",
                    content_payload={
                        "topics": research_topics,
                        "markdown": "\n\n".join(findings_lines)[:4000],
                    },
                )

        # 5. Compose the intuitive reply: captured → researched → questions
        header = (
            f"🎨 Updated {board.emoji_icon} *{board.title}* (#{board.id})"
            if brief["action"] == "augment_board" and target_board is not None
            else f"🎨 Created {board.emoji_icon} *{board.title}* (#{board.id})"
        )
        parts = [header]

        detail_bits = [b for b in (brief.get("destination"), brief.get("date_range")) if b]
        occasion = brief.get("occasion")
        if occasion:
            detail_bits.append(occasion)
        if detail_bits:
            parts.append("📅 " + " · ".join(detail_bits))

        if created_cards:
            card_lines = []
            for section, block in created_cards[:8]:
                t = block.title if block else f"Skeleton: {date_range}"
                card_lines.append(f"• {t} _({section})_")
            parts.append("Cards added:\n" + "\n".join(card_lines))

        if findings_lines:
            highlights = findings_lines[0].split("\n")
            preview = "\n".join(highlights[:3])[:500]
            parts.append(f"🔎 Quick findings:\n{preview}\n_Full notes saved to the 🔍 Research section._")

        questions = brief.get("follow_up_questions") or []
        if questions:
            q_lines = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
            parts.append(f"To fine-tune the plan:\n{q_lines}")

        parts.append("_Open the Whiteboard tab to see everything laid out._")
        return "\n\n".join(parts)


def _describe_expectation(user_text: str, tags: List[str]) -> str:
    """One-line statement of what the user wanted to accomplish, for gap tickets."""
    text = (user_text or "").strip().replace("\n", " ")
    if len(text) > 240:
        text = text[:237] + "..."
    key = tags[0] if tags else "custom"
    scope = {
        "bank_transfer": "Initiate a bank transfer / send money",
        "calendar": "Schedule, view or manage calendar events",
        "flight_booking": "Search or book flights",
        "smart_home": "Control smart-home devices",
        "email_send": "Compose and send an email",
        "budget": "Set or track a budget",
        "restaurant_booking": "Reserve a restaurant table",
    }.get(key)
    if scope:
        return f"{scope}. Full request: \"{text}\""
    return f"User expected the assistant to carry out: \"{text}\""


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
            (
                "book a flight", "flight ticket", "book flights",
                "book a hotel", "hotel booking", "reserve a hotel",
            ): "flight_booking",
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
    "whiteboard": WhiteboardPlugin(),
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

    _PLANNING_SIGNALS = (
        "trip", "travel", "flight", "hotel", "villa", "airbnb", "stay", "booking", "booked",
        "itinerary", "lunch", "dinner", "breakfast", "brunch", "restaurant", "eat",
        "club", "beach", "party", "bachelor", "activity", "tour", "gym", "fitness",
        "yoga", "spa", "reservation", "check in", "check-in", "pack", "headcount",
        "day 1", "day 2", "day 3", "friday", "saturday", "sunday", "monday",
    )

    @classmethod
    def _has_planning_signal(cls, text: str) -> bool:
        lowered = (text or "").lower()
        return any(signal in lowered for signal in cls._PLANNING_SIGNALS)

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
            reply = AIMessage(
                content=f"⚠️ [Supervisor Guardrail] This transactional capability (`#{primary_tag}`) is not yet supported. Would you like to log it as a feature request?"
            )
            await log_capability_request(
                user_id=user_id,
                requested_task=user_text,
                intent_type="unsupported_transaction",
                tags=missing_tags,
                expectation=_describe_expectation(user_text, missing_tags),
                block_reason=(
                    f"GuardrailPolicy classified the request as an unsupported transactional "
                    f"capability (`{'`, `'.join(missing_tags)}`) — no plugin is registered to carry it out."
                ),
                agent_reply=str(reply.content),
                channel=state.get("channel") or "unknown",
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
            if target_domain == "general" and state.get("active_domain") == "whiteboard":
                # Planning conversations continue on the board: follow-ups like
                # "we need a place for lunch" shouldn't fall out of context.
                if self._has_planning_signal(user_text):
                    target_domain = "whiteboard"
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
