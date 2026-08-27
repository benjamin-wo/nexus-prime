"""The agent turn: a safety kernel plus ONE agentic loop with every skill tool.

Replaces the plan -> dispatch subagent pipeline. Deterministic code is reserved
for the kernel (termination, media, money writes, pending-question
continuation, transactional guardrails); everything else is handled by a
single tool-chaining agent whose capabilities are declared by SKILL.md files.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, List
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command
from langgraph.graph import END

from core.config import settings
from core.llm import extract_llm_text, get_agent_llm, get_multimodal_llm, ThinkingLevel
from orchestrator.state import AssistantState
from orchestrator.checkpointer import prune_and_summarize_messages
from core.skill_registry import (
    all_declared_tools,
    discover_skills,
    make_load_skill_tool,
    skill_index_text,
)

MAX_TOOL_ROUNDS = 8

_KERNEL_RULES = """You are Nexus Prime, a personal assistant on Telegram and the web cockpit.
You fulfil the user's requests by chaining the tools you have. Core rules:

1. IDENTITY: user-scoped tools take a user_id argument that is injected for you.
   Never claim another user's data; never ask the user for their ID.
2. SKILLS: check the skill index. When a task matches a skill, call load_skill(name)
   first and follow its how-to guidance exactly.
3. TRUTH: report only what tools return. Never fabricate bus numbers, prices,
   headlines, links, or balances. If a tool fails or returns nothing, say so.
4. WRITES: money, reminders, boards, and other state changes go through their
   tools — never claim you changed something you didn't. Ambiguous entries may
   pause for the user's confirmation; that pause is normal.
5. CHAT: match the user's tone, stay concise, use light emoji like a chat app.
   Ask at most one clarifying question when something critical is missing.
6. Today is {now}. The user's timezone is {tz}."""


def _user_text(state: AssistantState) -> tuple[str, bool]:
    messages = state.get("messages") or []
    if not messages:
        return "", False
    last = messages[-1]
    if getattr(last, "type", "") != "human":
        return "", False
    content = getattr(last, "content", "")
    if isinstance(content, list):
        text = " ".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    else:
        text = str(content).strip()
    return text, True


def _has_media(state: AssistantState) -> bool:
    messages = state.get("messages") or []
    if not messages:
        return False
    content = getattr(messages[-1], "content", "")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "media" for block in content
    )


def _skills_provider():
    return discover_skills()


def _toolset_for(user_id: Any) -> List[Any]:
    from core.skill_registry import build_tool_registry, discover_skills as _discover

    tools = all_declared_tools(_skills_provider())
    tools.append(make_load_skill_tool(_skills_provider))
    user_skills = _discover()
    for skill_name in settings.admin_only_capabilities:
        if skill_name in user_skills and not settings.is_admin(user_id):
            gated = user_skills[skill_name]
            gated_names = set(gated.tools)
            tools = [t for t in tools if t.name not in gated_names]
    if settings.is_admin(user_id):
        code_exec = build_tool_registry().get("run_python_code")
        if code_exec is not None:
            tools.append(code_exec)
    return tools


def _system_prompt(user_id: Any, tz_name: str) -> str:
    now = datetime.now(ZoneInfo(tz_name) if tz_name else None).strftime("%A, %d %b %Y %H:%M %Z")
    return _KERNEL_RULES.format(now=now, tz=tz_name) + "\n\n## Skill index\n" + skill_index_text(
        _skills_provider()
    )


async def _handle_media(state: AssistantState, text: str) -> Command:
    """Photo/voice turn: try receipt-expense extraction first (a primary
    feature), fall back to describing the media."""
    import hashlib

    from capabilities.expenses.tools import (
        extract_expense_from_photo,
        process_extracted_expense,
        SPLIT_ALERT_THRESHOLD,
    )

    messages = state.get("messages") or []
    last_content = getattr(messages[-1], "content", "")
    if isinstance(last_content, list):
        image_block = next(
            (
                block
                for block in last_content
                if isinstance(block, dict) and block.get("type") == "media"
                and str(block.get("mime_type") or "").startswith("image/")
            ),
            None,
        )
    else:
        image_block = None

    if image_block is not None:
        extracted = await extract_expense_from_photo.ainvoke(
            {
                "image_b64": image_block.get("data", ""),
                "mime_type": image_block.get("mime_type", "image/jpeg"),
                "caption": text or None,
            }
        )
        if extracted and extracted.get("amount"):
            image_digest = hashlib.md5((image_block.get("data") or "").encode("utf-8")).hexdigest()[:12]
            res = await process_extracted_expense.ainvoke(
                {
                    "user_id": int(state.get("user_id") or 0),
                    "amount": extracted["amount"],
                    "currency": extracted.get("currency", "USD"),
                    "merchant": extracted["merchant"],
                    "category": extracted.get("category", "General"),
                    "date_iso": extracted.get("date_iso") or "",
                    "confidence": extracted.get("confidence", 0.9),
                    "needs_clarification": extracted.get("needs_clarification", False),
                    "source_message_id": f"exp-photo-{state.get('user_id')}-{image_digest}",
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
            return Command(goto=END, update={"messages": [AIMessage(content=reply)], "active_domain": "agent"})

    reply = await _multimodal_reply(state)
    return Command(goto=END, update={"messages": [reply], "active_domain": "agent"})


async def _multimodal_reply(state: AssistantState) -> AIMessage:
    if not settings.active_gemini_api_key or settings.active_gemini_api_key == "test_google_key":
        return AIMessage(
            content="I got your photo/voice, but my vision model isn't configured on this deployment yet."
        )
    history = [
        SystemMessage(content="You are Nexus Prime, the user's personal assistant. Respond to their photo/voice message helpfully and concisely.")
    ] + list(state.get("messages") or [])[-6:]
    try:
        llm = get_multimodal_llm(temperature=0.2)
        ai_message = await llm.ainvoke(history)
        content = extract_llm_text(getattr(ai_message, "content", "")).strip()
        return AIMessage(content=content or "I processed that, but couldn't generate a description.")
    except Exception as exc:  # noqa: BLE001
        print(f"[AGENT] multimodal call failed: {exc}")
        return AIMessage(content="Hmm, I couldn't analyze that just now — mind sending it again?")


async def _run_income_write(state: AssistantState, text: str) -> Command:
    """Deterministic finance write: incoming-money statements never go through the LLM.

    Friend repayments additionally settle a matching IOU — the settlement is a
    money write, so it stays deterministic with the rest of this path.
    """
    from capabilities.expenses.tools import (
        income_source_id,
        is_duplicate_income,
        parse_incoming_transaction_text,
        save_income_transaction,
    )

    user_id = int(state.get("user_id") or 0)
    incoming = parse_incoming_transaction_text(text)
    source_id = income_source_id(user_id, text)
    if incoming is None:
        return Command(goto=END)

    if incoming.get("category") == "Friend Repayment":
        from capabilities.expenses.settlement import settle_matching_iou

        received_at = None
        try:
            received_at = datetime.fromisoformat(
                str(incoming.get("date_iso") or "").replace("Z", "+00:00")
            )
        except ValueError:
            pass
        settlement = await settle_matching_iou(
            user_id=user_id,
            participant=str(incoming.get("source") or ""),
            amount=float(incoming.get("amount") or 0.0),
            received_at=received_at,
            notes=str(incoming.get("notes") or "").strip() or None,
        )
        if settlement is not None and settlement.get("status") in {
            "settled", "partially_settled", "already_settled",
        }:
            status = settlement["status"]
            if status == "already_settled":
                reply_text = (
                    f"ℹ️ {settlement['participant']}'s repayment is already marked as paid "
                    f"({settlement['currency']} {settlement['amount_due']:.2f})."
                )
            elif status == "partially_settled":
                outstanding = settlement["amount_due"] - settlement["total_received"]
                reply_text = (
                    f"💵 Logged {settlement['currency']} {settlement['amount_received']:.2f} from "
                    f"{settlement['participant']}. Their IOU still has "
                    f"{settlement['currency']} {outstanding:.2f} outstanding."
                )
            else:
                reply_text = (
                    f"✅ Logged {settlement['currency']} {settlement['amount_received']:.2f} from "
                    f"{settlement['participant']} and marked their IOU as paid."
                )
            return Command(
                goto=END,
                update={"messages": [AIMessage(content=reply_text)], "active_domain": "agent"},
            )

    if await is_duplicate_income(source_id):
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content="↩️ That incoming transaction is already logged.")],
                "active_domain": "agent",
            },
        )

    item = await save_income_transaction(user_id, incoming, source_id)
    reply = AIMessage(
        content=(
            f"💵 Logged *{item.currency} {item.amount:.2f}* from *{item.source}* ({item.category})."
        )
    )
    return Command(goto=END, update={"messages": [reply], "active_domain": "agent"})


async def _run_bus_continuation(state: AssistantState, text: str) -> Command | None:
    """Pending bus-stop disambiguation: the answer must stay in the bus handler."""
    from capabilities.routes.tools import handle_bus_query, is_bus_arrival_query, is_bus_disambiguation_answer

    pending = state.get("pending_bus_stops")
    if not pending or not (is_bus_arrival_query(text) or is_bus_disambiguation_answer(text, pending)):
        return None
    result = await handle_bus_query(text, pending_stops=pending)
    reply = AIMessage(content=result.get("message") or "No bus information returned.")
    return Command(
        goto=END,
        update={
            "messages": [reply],
            "active_domain": "agent",
            "pending_bus_stops": result.get("pending_stops"),
        },
    )


async def _guardrail(text: str, user_id: int) -> Command | None:
    """Unsupported transactional categories are refused, never improvised."""
    from core.audit import log_capability_request
    from orchestrator.kernel import insufficiency_refusal, missing_policy

    missing = missing_policy(text)
    if not missing:
        return None
    refusal = insufficiency_refusal(missing)
    try:
        await log_capability_request(
            user_id=user_id,
            requested_task=text,
            intent_type="insufficient_capability",
            tags=missing,
            block_reason="; ".join(refusal.reasons),
            agent_reply=refusal.message,
            channel="agent_kernel",
        )
    except Exception as exc:  # noqa: BLE001 - telemetry must never break the turn
        print(f"[AGENT] gap telemetry failed: {exc}")
    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=refusal.message)],
            "active_domain": None,
            "intent_type": "unsupported_transaction",
            "missing_capability_tags": missing,
        },
    )


async def _run_agent_loop(state: AssistantState, text: str) -> Command:
    user_id = state.get("user_id")
    tz_name = state.get("current_timezone") or "Asia/Singapore"

    if not settings.has_llm_key:
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(
                    content=(
                        "Hey there! 👋 I'm Nexus Prime. I can track expenses, split bills, "
                        "set reminders, check buses, plan boards and more — but my language "
                        "model isn't configured on this deployment yet."
                    )
                )],
                "active_domain": "agent",
            },
        )

    tools = _toolset_for(user_id)
    llm = get_agent_llm(complexity=ThinkingLevel.MEDIUM, temperature=0.3)
    llm_with_tools = llm.bind_tools(tools)

    history: List[Any] = [SystemMessage(content=_system_prompt(user_id, tz_name))]
    pruned_messages, _summary = prune_and_summarize_messages(state.get("messages") or [], threshold=12)
    history.extend(pruned_messages)

    collected: List[Any] = []
    final_text = ""

    async def _loop_once() -> str:
        nonlocal llm_with_tools
        text_out = ""
        for _round in range(MAX_TOOL_ROUNDS):
            ai_message = await llm_with_tools.ainvoke(history)
            tool_calls = getattr(ai_message, "tool_calls", None) or []
            if not tool_calls:
                text_out = extract_llm_text(getattr(ai_message, "content", "")).strip()
                collected.append(ai_message)
                break
            history.append(ai_message)
            collected.append(ai_message)
            for call in tool_calls:
                call_name = str(call.get("name") or "")
                call_args = dict(call.get("args") or {})
                observation = await _execute_call(tools, call_name, call_args, user_id)
                tool_msg = ToolMessage(content=str(observation), tool_call_id=str(call.get("id") or call_name))
                history.append(tool_msg)
                collected.append(tool_msg)
        return text_out

    try:
        final_text = await _loop_once()
    except Exception as exc:  # noqa: BLE001 - provider outages must degrade, not crash the turn
        print(f"[AGENT] LLM loop failed: {exc}")
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(
                    content=(
                        "I couldn't reach my language model just now, so I can't work on that "
                        "yet — try again in a moment. 🛠️"
                    )
                )],
                "active_domain": "agent",
            },
        )

    # Anti-hallucination guard (#42, #43): a raw URL in the reply is only
    # trustworthy if a web tool actually ran this turn. One corrective retry,
    # then strip any still-unverified link instead of shipping it.
    url_pattern = re.compile(r"https?://\S+")

    def _web_tool_ran() -> bool:
        return any(
            isinstance(m, AIMessage) and any(
                str(c.get("name")) in {"search_web", "fetch_url"} for c in (m.tool_calls or [])
            )
            for m in collected
        )

    if final_text and url_pattern.search(final_text) and not _web_tool_ran():
        history.append(HumanMessage(
            content=(
                "Your reply contains a link but you never ran search_web or fetch_url this "
                "turn, so it is probably invented. Either call a real web tool now or rewrite "
                "the reply without any URL. Do not keep the unverified link."
            )
        ))
        final_text = await _loop_once() or final_text
        if final_text and url_pattern.search(final_text) and not _web_tool_ran():
            final_text = url_pattern.sub("", final_text)
            final_text = re.sub(r"\s{2,}", " ", final_text).strip()
            final_text += "\n\n(I removed an unverified link — ask me to search and I'll find a real one.)"

    if not final_text:
        last_tool = next((m for m in reversed(collected) if isinstance(m, ToolMessage)), None)
        final_text = (
            f"I hit my tool budget working on that — last result: {str(last_tool.content)[:400]}"
            if last_tool
            else "I'm here! What would you like to do?"
        )

    return Command(
        goto=END,
        update={
            "messages": [m for m in collected if isinstance(m, (AIMessage, ToolMessage))],
            "active_domain": "agent",
        },
    )


async def _execute_call(tools: List[Any], call_name: str, call_args: dict, user_id: Any) -> Any:
    tool_obj = next((t for t in tools if t.name == call_name), None)
    if tool_obj is None:
        return f"[{call_name}] Unknown tool."
    if _tool_takes_user_id(tool_obj) or "user_id" in call_args:
        # Identity guard: never trust a model-supplied user_id. Covers both
        # user-scoped tools (schema/signature detection) and a model trying to
        # smuggle a user_id into a tool that doesn't declare one.
        call_args["user_id"] = int(user_id or 0)
    try:
        return await tool_obj.ainvoke(call_args)
    except Exception as exc:  # noqa: BLE001
        from langgraph.types import NodeInterrupt

        if isinstance(exc, NodeInterrupt) or type(exc).__name__ == "NodeInterrupt":
            raise
        print(f"[AGENT] tool {call_name} failed: {exc}")
        return f"[{call_name}] failed: {exc}"


def _tool_takes_user_id(tool_obj: Any) -> bool:
    schema = getattr(tool_obj, "args_schema", None)
    if schema is not None:
        fields = getattr(schema, "model_fields", None)
        if fields is None:
            fields = getattr(schema, "__fields__", {})
        if "user_id" in fields:
            return True
    fn = getattr(tool_obj, "func", None) or getattr(tool_obj, "coroutine", None)
    if fn is not None:
        try:
            import inspect

            return "user_id" in inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return False
    return False


async def agent_turn(state: AssistantState) -> Command:
    text, is_user = _user_text(state)
    if not is_user:
        return Command(goto=END)

    user_id = int(state.get("user_id") or 0)

    from orchestrator.kernel import is_termination_intent

    if is_termination_intent(text):
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content="Got it — I'll stop here. 👋")],
                "active_domain": "agent",
                "intent_type": "close",
            },
        )

    if _has_media(state):
        return await _handle_media(state, text)

    # Self-diagnosis intercepts BEFORE the agent loop: "why did you..."/"is this
    # broken" questions must be answered from the bot's own health, not routed
    # into a random skill's disambiguation flow.
    from orchestrator.self_diagnostics import (
        explain_last_turn,
        looks_like_self_diagnostic_question,
    )

    if looks_like_self_diagnostic_question(text):
        try:
            explanation = await explain_last_turn(state)
            if explanation:
                return Command(
                    goto=END,
                    update={"messages": [AIMessage(content=explanation)], "active_domain": "agent"},
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[AGENT] self-diagnostic failed: {exc}")

    from capabilities.expenses.tools import parse_incoming_transaction_text

    if parse_incoming_transaction_text(text) is not None:
        return await _run_income_write(state, text)

    bus = await _run_bus_continuation(state, text)
    if bus is not None:
        return bus

    guardrail = await _guardrail(text, user_id)
    if guardrail is not None:
        return guardrail

    result = await _run_agent_loop(state, text)

    # Conversation-quality audit stays on the kernel cadence (every 4 user turns).
    try:
        from core.audit import perform_conversation_audit, should_audit_conversation

        user_message_count = sum(
            1 for m in (state.get("messages") or []) if getattr(m, "type", "") == "human"
        )
        if should_audit_conversation(user_message_count):
            reply_text = ""
            for m in reversed(result.update.get("messages", []) if isinstance(result.update, dict) else []):
                if isinstance(m, AIMessage) and m.content and not m.tool_calls:
                    reply_text = str(m.content)
                    break
            asyncio.create_task(
                perform_conversation_audit(
                    user_id=user_id,
                    thread_id=str(user_id),
                    messages=[HumanMessage(content=text), AIMessage(content=reply_text)],
                )
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[AGENT] audit scheduling failed: {exc}")

    return result
