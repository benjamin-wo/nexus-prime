"""Agentic orchestration core.

A single bounded tool-calling loop that reads the full tool roster and
decides for itself which tool(s) to call, in what order, and how many times
-- replacing orchestrator/planner.py's deterministic keyword/BM25 capability
selection and orchestrator/plan_router.py's 13-branch dispatch. Per the
user's direction: "I like the skills because the agent can read each skill
and decide how to use it. time is important but it should not limit the
agent." There is no wall-clock ceiling on this loop -- see MAX_TOOL_ROUNDS
below and app/webhook.py's fire-and-forget dispatch.

Kept as a single LangGraph node (not a plain Python loop) specifically so
langgraph.types.interrupt() keeps working for HITL-gated writes (see
capabilities/expenses/tools.py's process_extracted_expense) --
app/ingress.py's existing __interrupt__/Command(resume=...) handling is
untouched by this file. GraphBubbleUp (interrupt()'s signal, and Command
routing) is explicitly re-raised rather than swallowed by the per-tool
try/except below.

Sensitive tools (money writes, board writes, ...) are agent-callable like
any other tool; each guards itself via core.tool_guard.identity_bound rather
than being kept out of the agent's reach or special-cased here.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, List
from zoneinfo import ZoneInfo

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END
from langgraph.types import Command

from core.audit import log_capability_request, perform_conversation_audit, should_audit_conversation
from core.config import settings
from core.llm import ThinkingLevel, extract_llm_text, get_agent_llm, get_multimodal_llm
from core.tool_guard import bind_user_id, current_user_id
from orchestrator.checkpointer import prune_and_summarize_messages, recent_turns
from orchestrator.state import AssistantState

URL_PATTERN = re.compile(r"https?://\S+")

# Runaway-loop backstop, NOT a time limit. The old per-turn wall-clock
# ceilings (GENERAL_TOOL_LOOP_TIMEOUT_SECONDS, WEBHOOK_PROCESSING_TIMEOUT_SECONDS,
# PLANNING_INTAKE_TIMEOUT_SECONDS) are gone along with the deterministic
# router they protected -- app/webhook.py now acks Telegram immediately and
# this loop runs as long as it genuinely needs to (see app/webhook.py,
# app/ingress.py's per-chat_id lock). This constant exists only to kill a
# truly broken loop (a tool whose result always makes the model want to call
# it again); a real multi-step request should never come remotely close.
MAX_TOOL_ROUNDS = 40

# Old GuardrailPolicy's tag vocabulary (orchestrator/router.py, deleted) --
# kept only as illustrative examples in the system prompt, not as a matcher:
# the agent decides for itself when a request is out of scope now.
_UNSUPPORTED_EXAMPLES = "bank_transfer, calendar, flight_booking, hotel_booking, smart_home"

# orchestrator/recipes.py's old fixed-shape playbooks (briefing, spend
# autopsy, grocery run, commute conditions, bill watch) bypassed the plugin
# registry to compose several tool calls into one coherent digest. That
# domain knowledge is worth keeping as guidance the agent can use and
# deviate from -- not as forced call sequences (recipes.py itself is
# deleted; every tool it called directly below is still available).
_RECIPE_GUIDANCE = """
When a request matches one of these shapes, use it as a starting point (not a fixed script) -- gather the same information, then compose a natural reply:
- "morning briefing" / "what's new": sweep_email_for_expenses (or search_my_email if no write is wanted) + list_my_reminders, composed into one digest.
- "spend autopsy" / "where did my money go": get_user_expenses (limit ~500), then run_python_code to total by merchant/category rather than eyeballing a long list.
- "grocery run" / meal-planning follow-ups: get_user_grocery_list, and if the user names a start/end place, plan_route or transit_journey for getting to the store.
- "commute conditions": plan_route or transit_journey for the trip, plus search_web for local weather.
- "bill watch" / upcoming bills: search_my_email for bill/statement/invoice-like messages, cross-checked against get_user_expenses and list_my_reminders.
""".strip()


def _build_system_prompt(is_admin: bool, now: str) -> str:
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
        "check, instead of inventing plausible-sounding details.\n\n"
        "You have direct access to every tool below -- read each tool's own description to "
        "decide whether and how to use it, and call as many of them, in whatever order, as a "
        "request genuinely needs (e.g. researching a trip may mean search_web several times, "
        "then create_planning_board, then several pin_note_to_whiteboard/add_checklist_to_whiteboard "
        "calls). You are not limited to one tool call per turn or one domain per turn. "
        "NEVER say you're about to look something up, search, or check without actually calling "
        "the tool that does it in this same turn -- 'let me check that for you...' with no tool "
        "call behind it leaves the user waiting on nothing. Call the tool, then answer from what "
        "it returned, all in one turn.\n\n"
        "Tools tagged as writing money or board data enforce their own safety checks "
        "internally (ownership, confirmation, duplicate detection) -- call them as directly as "
        "any read-only tool; if one comes back asking for confirmation or reports a problem, "
        "relay that honestly rather than working around it.\n\n"
        f"If the user asks for something no tool below can do (e.g. {_UNSUPPORTED_EXAMPLES}), "
        "don't attempt it or pretend it's done -- call log_capability_gap once with a short tag "
        "and one-line description, then tell them plainly it isn't supported yet and that you've "
        "logged it as a feature request.\n\n"
        f"{_RECIPE_GUIDANCE}\n\n"
        f"Current Singapore time: {now}. "
        f"{capabilities_desc}"
    )


# Regression (live incident): mid-conversation (e.g. mid a bus-stop
# disambiguation), a genuinely empty model completion or a tool-loop
# exception used to fall back to _generate_rule_based_response's canned
# "here's what I can help with" capabilities blurb -- appropriate only for
# a fresh/unclear message with no context, but jarring and misleading when
# it interrupts a conversation the bot was just actively engaged in (reads
# as total context loss). These stay distinct from that fallback and from
# each other so each failure mode gets an honest, situation-appropriate reply.
_EMPTY_REPLY_FALLBACK = "sorry, I didn't quite catch that — could you rephrase or try again?"
_ERROR_REPLY_FALLBACK = "😵‍💫 sorry, something glitched on my end there — mind trying that again?"


def _generate_rule_based_response(text: str) -> str:
    """Graceful conversational fallback for greetings/help when no LLM key is configured."""
    text_lower = text.strip().lower()

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
    if any(w in text_lower for w in ["thank", "thanks", "thx", "appreciate", "cheers"]):
        return "You're very welcome! Let me know if there's anything else you need. 😊"
    if any(phrase in text_lower for phrase in ["how are you", "how's it going", "how r u", "whats up", "what's up"]):
        return "I'm doing great and ready to assist! What can I help you tackle today? 🚀"
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
    return (
        "I'm here to help! You can ask me to track expenses (*Spent $15 on lunch*), split a bill (*"
        "/split $50 with Sam*), set reminders (*Remind me at 4pm*), or tap /dashboard to view your cockpit.\n\n"
        "How can I assist you right now?"
    )


@tool
async def log_capability_gap(tag: str, expectation: str) -> str:
    """
    Log a genuinely unsupported request as a feature-wishlist item instead of
    attempting it or pretending it's done. Use ONLY when the user asked for
    something no available tool can do (e.g. moving real money via bank
    transfer, calendar scheduling, smart-home control, flight/hotel booking)
    -- never for something a tool above already covers.

    Args:
        tag: short snake_case tag for the missing capability, e.g. "bank_transfer".
        expectation: one-line description of what the user wanted to happen.
    """
    return await _log_capability_gap({"tag": tag, "expectation": expectation})


def _skill_index_text() -> str:
    """Compact one-line-per-skill index appended to the system prompt."""
    from core.skill_registry import discover_skills, skill_index_text

    return "\n\n## Skill index\n" + skill_index_text(discover_skills())


def _build_tool_roster() -> List[Any]:
    """The agent's full tool set, resolved from the installed skills.

    Skills are declared in ``skills/<name>/SKILL.md`` (YAML frontmatter: name,
    description, side_effect, tools) and ``core/skill_registry.py`` resolves
    every declared tool name against the global tool registry. Adding a tool
    to the agent = adding its name to a SKILL.md frontmatter; adding a whole
    skill = dropping a folder. Late binding is preserved: the registry is
    rebuilt each turn, so tests (and hot skill edits) see fresh modules.

    Sensitive tools (money writes, board writes, ...) remain agent-callable
    like any other; each guards itself via core.tool_guard.identity_bound.
    """
    from core.skill_registry import (
        all_declared_tools,
        discover_skills,
        make_load_skill_tool,
    )

    skills = discover_skills()
    tools = all_declared_tools(skills)
    tools.append(make_load_skill_tool(lambda: discover_skills()))
    # Loop machinery, not a skill: the agent self-reports capability gaps so
    # telemetry keeps flowing without a deterministic intent matcher.
    tools.append(log_capability_gap)
    return tools


def _user_text(state: AssistantState) -> tuple[str, bool, list]:
    """(text, is_real_user_turn, media_blocks). Mirrors the old plan_dispatch's
    _user_text, plus media detection (old CapabilityRouter.dispatch)."""
    messages = state.get("messages", [])
    if not messages:
        return "", False, []
    last = messages[-1]
    if isinstance(last, AIMessage):
        return "", False, []
    content = getattr(last, "content", "")
    if isinstance(content, list):
        text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        media = [b for b in content if isinstance(b, dict) and b.get("type") == "media"]
        return " ".join(text_parts).strip(), True, media
    return str(content).strip(), True, []


async def _handle_multimodal_turn(
    user_id: int, text: str, media_blocks: list, history: List[BaseMessage]
) -> "PluginTurnResult":
    """Photos/voice go through Gemini (DeepSeek, the main agent model, has no
    vision) -- the one deliberate exception to "the agent decides which tool
    to call": the agent literally cannot see the image to decide. A receipt-
    shaped photo goes through the same extract_expense_from_photo ->
    process_extracted_expense pipeline any agent tool call would use
    (interrupt()-capable, propagates uncaught); anything else gets a plain
    Gemini description."""
    from capabilities.expenses.tools import (
        extract_expense_from_photo,
        extract_expense_from_text,
        process_extracted_expense,
    )

    image_block = next(
        (b for b in media_blocks if (b.get("mime_type") or "").startswith("image/")), None
    )
    lowered = text.lower()
    expense_hint = any(p in lowered for p in ("receipt", "expense", "spent", "paid", "bill", "cost", "$"))

    if not image_block or not (not lowered or expense_hint):
        if (
            not settings.active_gemini_api_key
            or settings.active_gemini_api_key == "test_google_key"
        ):
            return PluginTurnResult(
                "I got your photo/voice, but my vision model isn't configured on this deployment yet (GEMINI_API_KEY missing).",
                [],
            )
        try:
            llm = get_multimodal_llm(temperature=0.2)
            ai_message = await llm.ainvoke(history)
            content = extract_llm_text(getattr(ai_message, "content", "")).strip()
            content = content or "I processed your media message, but couldn't generate a description."
        except Exception as exc:  # noqa: BLE001
            print(f"[AGENT_LOOP] multimodal call failed: {exc}")
            content = "Hmm, I couldn't analyze that just now — my vision model hit an error. Mind sending it again?"
        return PluginTurnResult(content, [])

    extracted = await extract_expense_from_photo.ainvoke(
        {
            "image_b64": image_block.get("data", ""),
            "mime_type": image_block.get("mime_type", "image/jpeg"),
            "caption": text or None,
        }
    )
    if not extracted.get("amount"):
        # The photo wasn't a (legible) receipt. Don't assume the caption was
        # therefore also worthless -- it can carry its own, independent
        # expense ("also spent $10 on parking") even when the photo itself
        # doesn't. Try that before giving up (regression #25).
        if text:
            caption_extracted = await extract_expense_from_text.ainvoke({"user_text": text})
            if caption_extracted and caption_extracted.get("amount"):
                extracted = caption_extracted
            else:
                description = extracted.get("description")
                if description:
                    reply = f"📷 That's not a receipt — looks like {description}.\nI don't have a way to track that yet."
                else:
                    reply = (
                        "📷 I don't see a clear receipt in that photo — try a closer, "
                        "well-lit shot of the total, or just tell me the amount in text."
                    )
                reply += f'\nI did note what you wrote: "{text}" — just can\'t act on it yet.'
                return PluginTurnResult(reply, [])
        else:
            description = extracted.get("description") or "I couldn't make out what this photo shows."
            return PluginTurnResult(f"📷 {description}", [])

    # May raise GraphBubbleUp (interrupt()) for low-confidence extraction --
    # let it propagate to the graph runtime, same as the tool-loop below.
    result = await process_extracted_expense.ainvoke(
        {
            "user_id": user_id,
            "amount": extracted["amount"],
            "currency": extracted.get("currency", "SGD"),
            "merchant": extracted.get("merchant", "Unknown"),
            "category": extracted.get("category", "General"),
            "date_iso": extracted.get("date_iso") or datetime.now().isoformat(),
            "confidence": extracted.get("confidence", 0.9),
            "needs_clarification": extracted.get("needs_clarification", False),
        }
    )
    status = result.get("status")
    if status == "saved_silently":
        reply = (
            f"🧾 Logged {extracted.get('currency', 'SGD')} {extracted['amount']:.2f} at "
            f"{extracted.get('merchant', 'Unknown')} ({extracted.get('category', 'General')})."
        )
    elif status == "duplicate":
        reply = "🧾 Looks like I already logged that one."
    else:
        reply = f"🧾 {result}"
    return PluginTurnResult(reply, [])


class PluginTurnResult:
    """Lightweight (content, extra_messages) pair -- not the old PluginOutput
    dataclass, since this loop returns a Command directly rather than being
    called through a plugin registry."""

    __slots__ = ("content", "extra_messages")

    def __init__(self, content: str, extra_messages: List[BaseMessage]):
        self.content = content
        self.extra_messages = extra_messages


async def _run_tool_loop(hist: List[BaseMessage], tools: List[Any], gap_calls: list) -> tuple[str, bool]:
    """Bounded tool-call loop against `hist` in place. Returns (final_text,
    link_tool_used); link_tool_used is True only if search_web/fetch_url
    actually ran, so a raw URL in the reply with link_tool_used=False is
    provably unverified. Appends any log_capability_gap calls' args to
    `gap_calls` so the caller can surface the wishlist button."""
    llm = get_agent_llm(complexity=ThinkingLevel.MEDIUM, temperature=0.7)
    llm_with_tools = llm.bind_tools(tools)
    link_tool_used = False

    ai_message = await llm_with_tools.ainvoke(hist)
    for _round in range(MAX_TOOL_ROUNDS):
        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if not tool_calls:
            break
        hist.append(ai_message)
        for call in tool_calls:
            call_name = str(call.get("name") or "")
            call_args = dict(call.get("args") or {})
            if call_name in ("search_web", "fetch_url"):
                link_tool_used = True
            if call_name == "log_capability_gap":
                gap_calls.append(call_args)
            tool_obj = next((t for t in tools if t.name == call_name), None)
            if tool_obj is None:
                observation: Any = f"[{call_name}] Unknown tool."
            else:
                try:
                    observation = await tool_obj.ainvoke(call_args)
                except GraphBubbleUp:
                    # interrupt() / Command routing -- must reach the
                    # graph runtime, never be treated as a tool failure.
                    raise
                except Exception as tool_exc:  # noqa: BLE001
                    print(f"[AGENT_LOOP] tool {call_name} failed: {tool_exc}")
                    observation = f"[{call_name}] failed: {tool_exc}"
            hist.append(
                ToolMessage(content=str(observation), tool_call_id=str(call.get("id") or call_name))
            )
        ai_message = await llm_with_tools.ainvoke(hist)

    text = extract_llm_text(getattr(ai_message, "content", "")).strip()
    round_budget_exhausted = False
    if not text and getattr(ai_message, "tool_calls", None):
        round_budget_exhausted = True
        hist.append(ai_message)
        for call in ai_message.tool_calls:
            hist.append(
                ToolMessage(
                    content="[tool] Round budget exhausted; answer from what you have.",
                    tool_call_id=str(call.get("id") or call.get("name") or ""),
                )
            )
        final_message = await llm_with_tools.ainvoke(hist)
        text = extract_llm_text(getattr(final_message, "content", "")).strip()

    # Regression (live incident): mid-conversation, the model sometimes
    # returns a genuinely empty completion -- no text, no tool call at all
    # (observed following up a bus-stop disambiguation: "That should be the
    # name" got back nothing). Without this, the caller's fallback used to
    # be the "no LLM key configured" canned capabilities blurb, which reads
    # as the bot having completely forgotten the conversation -- worse than
    # useless mid-thread. One corrective nudge first; a distinct honest
    # "I missed that" message (not the capabilities blurb) is the caller's
    # fallback if this still comes back empty. Skipped if we already hit
    # the round-budget-exhausted branch above: that's a different, already-
    # bounded situation (a genuinely runaway tool-calling loop, MAX_TOOL_ROUNDS'
    # own concern) -- retrying again here would just add unbounded extra
    # calls on top of an already-confirmed-broken loop.
    if not text and not round_budget_exhausted:
        hist.append(
            SystemMessage(
                content=(
                    "Your last response was empty. Answer the user's most recent "
                    "message directly -- either with a real reply, or by calling "
                    "a tool if one is needed to answer it."
                )
            )
        )
        retry_message = await llm_with_tools.ainvoke(hist)
        text = extract_llm_text(getattr(retry_message, "content", "")).strip()
        if not text and getattr(retry_message, "tool_calls", None):
            # The retry decided it needs a tool after all -- let the caller
            # see that via link_tool_used bookkeeping is out of scope here;
            # simplest correct move is one more direct answer pass after
            # actually running that tool call.
            hist.append(retry_message)
            for call in retry_message.tool_calls:
                call_name = str(call.get("name") or "")
                call_args = dict(call.get("args") or {})
                if call_name in ("search_web", "fetch_url"):
                    link_tool_used = True
                tool_obj = next((t for t in tools if t.name == call_name), None)
                if tool_obj is None:
                    observation: Any = f"[{call_name}] Unknown tool."
                else:
                    try:
                        observation = await tool_obj.ainvoke(call_args)
                    except GraphBubbleUp:
                        raise
                    except Exception as tool_exc:  # noqa: BLE001
                        print(f"[AGENT_LOOP] tool {call_name} failed: {tool_exc}")
                        observation = f"[{call_name}] failed: {tool_exc}"
                hist.append(
                    ToolMessage(content=str(observation), tool_call_id=str(call.get("id") or call_name))
                )
            final_retry_message = await llm_with_tools.ainvoke(hist)
            text = extract_llm_text(getattr(final_retry_message, "content", "")).strip()
    return text, link_tool_used


async def _log_capability_gap(args: dict) -> str:
    tag = re.sub(r"[^a-z0-9_]", "_", str(args.get("tag") or "custom").strip().lower()) or "custom"
    expectation = str(args.get("expectation") or "").strip()[:500]
    user_id = int(current_user_id.get() or 0)
    await log_capability_request(
        user_id=user_id,
        requested_task=expectation or "(no description given)",
        intent_type="unsupported_transaction",
        tags=[tag],
        expectation=expectation,
        block_reason="Agent judged this request outside its available tools.",
    )
    return f"Logged as an unsupported capability request (#{tag})."


async def _compose_reply(history: List[BaseMessage], tools: List[Any], gap_calls: list) -> tuple[str, List[BaseMessage]]:
    pre_loop_len = len(history)
    content, link_tool_used = await _run_tool_loop(history, tools, gap_calls)

    # Regression (#42, #43, carried over from GeneralPlugin): a raw URL in
    # the reply that this pass never backed with a real search_web/fetch_url
    # call is unverifiable and very likely invented -- one corrective retry,
    # then strip it.
    if content and URL_PATTERN.search(content) and not link_tool_used:
        history.append(
            SystemMessage(
                content=(
                    "Your draft reply included a link, but you did not call "
                    "search_web or fetch_url this turn -- that link is "
                    "unverified and must not be sent as-is. Call search_web "
                    "or fetch_url now to find a real link, or rewrite your "
                    "reply without inventing one."
                )
            )
        )
        retried_content, link_tool_used = await _run_tool_loop(history, tools, gap_calls)
        if retried_content:
            content = retried_content
        if URL_PATTERN.search(content) and not link_tool_used:
            content = URL_PATTERN.sub("", content).strip()
            content += "\n\n(I don't have a verified link for that right now — want me to search for one?)"

    extra_messages = [m for m in history[pre_loop_len:] if not isinstance(m, SystemMessage)]
    return content, extra_messages


async def agent_loop(state: AssistantState) -> Command[str]:
    """The graph's single node. Replaces capability_router_node /
    orchestrator/plan_router.py's plan_dispatch."""
    text, is_user, media_blocks = _user_text(state)
    if not is_user:
        return Command(goto=END)

    messages = state.get("messages", [])
    user_id = int(state.get("user_id") or 0)
    now_sg = datetime.now(ZoneInfo("Asia/Singapore")).strftime("%A, %d %b %Y %H:%M")
    is_admin = settings.is_admin(user_id)

    # Safety kernel: deterministic checks that never reach the LLM.
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

    pending_stops = state.get("pending_bus_stops")
    if pending_stops:
        from capabilities.routes.tools import (
            handle_bus_query,
            is_bus_arrival_query,
            is_bus_disambiguation_answer,
        )

        if is_bus_arrival_query(text) or is_bus_disambiguation_answer(text, pending_stops):
            bus_result = await handle_bus_query(text, pending_stops=pending_stops)
            return Command(
                goto=END,
                update={
                    "messages": [AIMessage(content=bus_result.get("message") or "No bus information returned.")],
                    "active_domain": "agent",
                    "pending_bus_stops": bus_result.get("pending_stops"),
                },
            )

    if len(messages) > 12:
        pruned, _ = prune_and_summarize_messages(messages, threshold=12)
    else:
        pruned = messages

    skill_index = _skill_index_text()
    history: List[BaseMessage] = [SystemMessage(content=_build_system_prompt(is_admin=is_admin, now=now_sg) + skill_index)]
    for message in pruned:
        if isinstance(message, SystemMessage):
            history.append(SystemMessage(content=str(message.content)))
        elif isinstance(message, HumanMessage):
            history.append(
                HumanMessage(content=message.content if isinstance(message.content, list) else str(message.content))
            )
        elif isinstance(message, AIMessage):
            history.append(AIMessage(content=str(message.content)))

    # Trusted, server-resolved identity for this turn -- every identity_bound
    # tool call below (however deep) reads this back, regardless of what a
    # model-supplied user_id argument says. Always reset in `finally` so it
    # never leaks into unrelated work on the same event loop.
    token = bind_user_id(user_id)
    gap_calls: list = []
    extra_messages: List[BaseMessage] = []
    try:
        if media_blocks:
            result = await _handle_multimodal_turn(user_id, text, media_blocks, history)
            content = result.content
        else:
            has_key = bool(
                settings.active_gemini_api_key
                or (settings.deepseek_api_key and settings.deepseek_api_key != "test_deepseek_key")
            )
            if not has_key:
                content = _generate_rule_based_response(text)
            else:
                tools = _build_tool_roster()
                try:
                    content, extra_messages = await _compose_reply(history, tools, gap_calls)
                    # _run_tool_loop already retries once internally on a
                    # genuinely empty completion -- if it's STILL empty here,
                    # that's a real (if rare) model hiccup, not "no LLM
                    # configured". _generate_rule_based_response's canned
                    # capabilities blurb is jarring mid-conversation (reads as
                    # the bot forgetting everything just discussed); a short,
                    # honest miss is more true to what happened.
                    if not content:
                        content = _EMPTY_REPLY_FALLBACK
                except GraphBubbleUp:
                    raise
                except Exception as exc:  # noqa: BLE001 - never let an LLM error kill the turn
                    print(f"[AGENT_LOOP] tool loop failed, using fallback: {exc}")
                    content = _ERROR_REPLY_FALLBACK
    finally:
        current_user_id.reset(token)

    update: dict[str, Any] = {
        # Regression (#53), carried over from GeneralPlugin: persist the
        # real tool-call/tool-result messages produced this turn into
        # checkpointed state alongside the final reply, not just the reply
        # itself -- otherwise a reply genuinely grounded in a real tool call
        # is indistinguishable from a hallucination to any later reader
        # (next turn's history, the audit pipeline, a human reviewing logs).
        "messages": [*extra_messages, AIMessage(content=content)],
        "active_domain": "agent",
    }
    if gap_calls:
        update["intent_type"] = "unsupported_transaction"
        update["missing_capability_tags"] = [
            re.sub(r"[^a-z0-9_]", "_", str(c.get("tag") or "custom").strip().lower()) or "custom"
            for c in gap_calls
        ]

    if should_audit_conversation(sum(1 for m in messages if getattr(m, "type", "") == "human")):
        turn_messages: List[BaseMessage] = [HumanMessage(content=text), *extra_messages, AIMessage(content=content)]
        asyncio.create_task(
            perform_conversation_audit(
                user_id=user_id,
                thread_id=str(user_id),
                messages=turn_messages,
            )
        )

    return Command(goto=END, update=update)
