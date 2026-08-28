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

from core.audit import (
    log_capability_request,
    perform_conversation_audit,
    record_operation_event,
    should_audit_conversation,
)
from core.background import fire_and_forget
from core.config import settings
from core.llm import LLM_REQUEST_TIMEOUT_SECONDS, ThinkingLevel, extract_llm_text, get_agent_llm, get_multimodal_llm
from core.tool_guard import bind_user_id, current_user_id
from core.tool_safety import FailureLedger, ToolOutcome, bounded_call, execute_tool_safely
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

# Tool outcomes worth filing an incident for, and at what severity. A tool the
# model cannot successfully call is a defect in that tool -- a wrong schema, a
# misleading description, a broken dependency -- not normal operation.
# "success" and "unknown_tool" are excluded: the former is fine, the latter is
# the model inventing a name, which is a prompt issue rather than a service
# fault.
_REPORTABLE_TOOL_FAILURES = {
    "invalid_args": "P2",
    "timeout": "P2",
    "error": "P2",
    "gave_up": "P1",
}

# Backstop for a single model call -- NOT another disguised wall-clock
# ceiling on the turn (that stays MAX_TOOL_ROUNDS' job, unbounded per the
# docstring above). Padded above core/llm.py's own client-level timeout so
# the client's more specific error gets first chance to fire.
#
# Two earlier attempts at this bound did NOT work, and the reasons matter:
#   1. core/llm.py's timeout= on the client. Never surfaced, because the
#      Gemini SDK retried internally 6 times by default (now capped, see
#      LLM_MAX_RETRIES) -- a ~3min worst case hidden inside one ainvoke().
#   2. PR #74's asyncio.wait_for around ainvoke(). Deployed, correct-looking,
#      and structurally incapable of firing: wait_for awaits the cancellation
#      it issues, and a retrying client swallows CancelledError. Confirmed by
#      direct reproduction -- a cancel-swallowing coroutine hung wait_for
#      indefinitely, and an OUTER wait_for could not break it either.
# Hence bounded_call (core/tool_safety.py), which abandons rather than awaits.
_MODEL_CALL_TIMEOUT_SECONDS = LLM_REQUEST_TIMEOUT_SECONDS + 15.0


async def _invoke_model(llm: Any, messages: List[BaseMessage]) -> AIMessage:
    """await llm.ainvoke(messages), hard-bounded so a stuck call surfaces as
    a normal catchable exception (feeding the existing honest-error
    fallback) instead of hanging the turn -- and the whole process, since
    this always runs inside a fire-and-forget background task -- forever."""
    # bounded_call, NOT asyncio.wait_for: #74 used wait_for here and it never
    # fired in production, because wait_for awaits the cancellation it issues
    # and the Gemini SDK's internal retry loop swallows it. See
    # core.tool_safety.bounded_call.
    return await bounded_call(
        llm.ainvoke(messages), _MODEL_CALL_TIMEOUT_SECONDS, "model call"
    )


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


DEFAULT_TIMEZONE = "Asia/Singapore"


def _runtime_anchors(timezone_name: str) -> str:
    """Authoritative "what time is it, and where" block for the system prompt.

    A model with no explicit clock has to guess "now", and a guessed timestamp
    is the most common source of malformed datetime arguments to the reminder,
    expense and transit tools -- the hallucinated-argument failure mode, at its
    root.

    This also fixes a live bug. The prompt used to hardcode Asia/Singapore and
    label it "Current Singapore time", but ``current_timezone`` is genuinely
    user-settable -- the /timezone command, a shared location pin, and "I just
    landed in Tokyo" all write it through core.scheduler.update_user_timezone,
    and app/ingress.py passes it into graph state on every turn. agent_loop
    read it exactly zero times, so a travelling user kept being anchored to
    Singapore's clock no matter what their profile said.
    """
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - a bad stored tz must never break the turn
        timezone_name = DEFAULT_TIMEZONE
        tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    return (
        "\n\n## Runtime anchors (authoritative -- never guess these)\n"
        f"- current_time_iso: {now.isoformat(timespec='seconds')}\n"
        f"- current_day: {now.strftime('%A, %d %b %Y %H:%M')}\n"
        f"- timezone: {timezone_name}\n"
        "Resolve every relative time ('tonight', 'in 20 minutes', 'next Tuesday') "
        "against current_time_iso, and pass absolute ISO-8601 datetimes to tools "
        "instead of relative phrases."
    )


def _build_system_prompt(is_admin: bool, timezone_name: str) -> str:
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
        f"{capabilities_desc}"
        f"{_runtime_anchors(timezone_name)}"
    )


# Regression (live incident): mid-conversation (e.g. mid a bus-stop
# disambiguation), a genuinely empty model completion or a tool-loop
# exception used to fall back to _generate_rule_based_response's canned
# "here's what I can help with" capabilities blurb -- appropriate only for
# a fresh/unclear message with no context, but jarring and misleading when
# it interrupts a conversation the bot was just actively engaged in (reads
# as total context loss). These stay distinct from that fallback and from
# each other so each failure mode gets an honest, situation-appropriate reply.
# Regression (live incident, "what other routes"): the model blanked twice
# in a row and the old fallback told the user to "rephrase" -- but the user's
# identical re-send worked, so the phrasing was never the problem. The text
# must own the blank, not imply user error.
_EMPTY_REPLY_FALLBACK = "🫥 I blanked out for a second there — say that once more?"
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


def _visible_skills(is_admin: bool) -> dict:
    """Skills this turn's user may see and call.

    ``settings.admin_only_capabilities`` names skills that are hidden from
    non-admin users entirely — no index entry, no bound tools, no loadable
    body — so a gated skill's tools never reach a non-admin turn. Admins see
    everything; with no admin configured (local/dev), every skill is visible.
    """
    from core.skill_registry import discover_skills

    skills = discover_skills()
    if is_admin or not settings.admin_only_capabilities:
        return skills
    return {
        name: skill
        for name, skill in skills.items()
        if name not in settings.admin_only_capabilities
    }


def _skill_index_text(visible_skills: dict) -> str:
    """Compact one-line-per-skill index appended to the system prompt."""
    from core.skill_registry import skill_index_text

    if not visible_skills:
        return "\n\n## Skill index\n(none available)"
    return "\n\n## Skill index\n" + skill_index_text(visible_skills)


def _build_tool_roster(visible_skills: dict) -> List[Any]:
    """The agent's full tool set, resolved from the installed skills.

    Skills are declared in ``skills/<name>/SKILL.md`` (YAML frontmatter: name,
    description, side_effect, tools) and ``core/skill_registry.py`` resolves
    every declared tool name against the global tool registry. Adding a tool
    to the agent = adding its name to a SKILL.md frontmatter; adding a whole
    skill = dropping a folder. Late binding is preserved: the registry is
    rebuilt each turn, so tests (and hot skill edits) see fresh modules.

    ``visible_skills`` is already filtered by ``_visible_skills`` for admin
    gating, so tools only a gated skill declares are simply never bound for a
    non-admin turn. Sensitive tools (money writes, board writes, ...) remain
    agent-callable like any other; each guards itself via
    core.tool_guard.identity_bound.
    """
    from core.skill_registry import (
        all_declared_tools,
        make_load_skill_tool,
    )

    tools = all_declared_tools(visible_skills)
    tools.append(make_load_skill_tool(lambda: visible_skills))
    # Loop machinery, not a skill: the agent self-reports capability gaps so
    # telemetry keeps flowing without a deterministic intent matcher.
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
            ai_message = await _invoke_model(llm, history)
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



def _read_only_tool_names(visible_skills: dict) -> set:
    """Tool names belonging to skills declared ``side_effect: read``.

    This is the concurrency boundary. Read-only tools have no side effects and
    never raise interrupt(), so a round's read-only calls are safe to run
    under asyncio.gather -- three transit lookups become one wall-clock
    round-trip instead of three. Anything a skill declares ``write``
    (expenses, whiteboard, reminders, ...) stays sequential in the order the
    model asked for, which is what preserves HITL semantics:
    process_extracted_expense's interrupt() fires before any later write in
    the same round has run, so a resume -- which re-enters this node from the
    top -- cannot double-apply one.
    """
    names: set = set()
    for skill in (visible_skills or {}).values():
        if getattr(skill, "side_effect", "read") == "read":
            names.update(getattr(skill, "tools", ()) or ())
    return names


async def _execute_tool_calls(
    calls: List[dict],
    tools: List[Any],
    hist: List[BaseMessage],
    gap_calls: list,
    ledger: FailureLedger,
    read_only: set,
    *,
    round_label: str,
) -> bool:
    """Run one round's tool calls, appending each result to ``hist`` in the
    order the model requested them -- a provider rejects a tool_calls message
    whose results are missing or reordered, so the ordering here is a
    correctness requirement, not a nicety. Returns whether a link tool ran.

    Every call goes through core.tool_safety.execute_tool_safely, so a bad
    argument comes back as an actionable correction, a hung tool is bounded,
    and a repeatedly-failing call is cut off instead of burning the whole
    round budget. Read-only calls run concurrently; writes run sequentially
    (see _read_only_tool_names).
    """
    link_tool_used = False
    resolved = []
    for call in calls:
        name = str(call.get("name") or "")
        args = dict(call.get("args") or {})
        if name in ("search_web", "fetch_url"):
            link_tool_used = True
        if name == "log_capability_gap":
            gap_calls.append(args)
        resolved.append((call, name, args, next((t for t in tools if t.name == name), None)))

    outcomes: dict = {}
    concurrent = [i for i, (_c, n, _a, _t) in enumerate(resolved) if n in read_only]
    concurrent_set = set(concurrent)
    sequential = [i for i in range(len(resolved)) if i not in concurrent_set]

    if concurrent:
        print(
            f"[AGENT_LOOP] {round_label}: {len(concurrent)} read-only tool(s) concurrently: "
            + ", ".join(resolved[i][1] for i in concurrent)
        )
        results = await asyncio.gather(
            *(
                execute_tool_safely(
                    resolved[i][3], resolved[i][2], tool_name=resolved[i][1], ledger=ledger
                )
                for i in concurrent
            ),
            return_exceptions=True,
        )
        for i, result in zip(concurrent, results):
            if isinstance(result, GraphBubbleUp):
                # A read-only tool should never interrupt, but if one does the
                # signal still belongs to the graph runtime, not to us.
                raise result
            if isinstance(result, BaseException):
                outcomes[i] = ToolOutcome("error", f"[{resolved[i][1]}] FAILED: {result}")
            else:
                outcomes[i] = result

    for i in sequential:
        _call, name, args, tool_obj = resolved[i]
        print(f"[AGENT_LOOP] {round_label}: calling tool {name}")
        outcomes[i] = await execute_tool_safely(tool_obj, args, tool_name=name, ledger=ledger)

    for i, (call, name, _args, _tool) in enumerate(resolved):
        outcome = outcomes[i]
        status = "returned" if outcome.ok else f"-> {outcome.status}"
        print(f"[AGENT_LOOP] {round_label}: tool {name} {status}")
        if outcome.status in _REPORTABLE_TOOL_FAILURES:
            # A tool the model could not successfully call is a defect in that
            # tool's schema, description or implementation -- never routine.
            # The 12 identity_bound tools fixed in #76 returned invalid_args on
            # every single call for as long as they existed, and nothing
            # anywhere noticed. Deduped per (tool, failure kind), so this is
            # one issue per broken tool carrying an occurrence count.
            _report_agent_failure(
                subsystem=f"tool:{name}",
                error_context=f"Tool {name} returned {outcome.status}: {outcome.observation[:800]}",
                severity=_REPORTABLE_TOOL_FAILURES[outcome.status],
                fingerprint=f"agent_tool_{name}_{outcome.status}",
                user_id=int(current_user_id.get() or 0),
            )
        hist.append(
            ToolMessage(content=outcome.observation, tool_call_id=str(call.get("id") or name))
        )

    return link_tool_used


def _report_agent_failure(
    subsystem: str,
    error_context: str,
    *,
    severity: str = "P2",
    fingerprint: str,
    user_id: int,
    error_traceback: str | None = None,
) -> None:
    """File an operational incident for a failure the agent recovered from.

    The detection gap this closes: agent_loop catches every exception from the
    tool loop and answers with _ERROR_REPLY_FALLBACK, so a model timeout, a
    provider 400 or a crashed tool became a friendly "something glitched"
    message and nothing else. app/ingress.py's report_production_bug sits
    OUTSIDE that catch, so it never fired for anything the agent loop handled
    -- which is nearly everything. Meanwhile the 15-minute operations sweep
    probes only static config (credentials present, DB reachable, scheduler
    object running), all of which stayed green throughout a total
    silent-reply outage.

    record_operation_event dedups on `fingerprint`, so a failure that repeats
    keeps ONE open issue with a recurrence count rather than filing hundreds.
    Reporting is fire-and-forget and defensive: telemetry must never be able
    to break the turn it is describing.
    """
    try:
        fire_and_forget(
            record_operation_event(
                subsystem=subsystem,
                error_context=error_context,
                detection_source="agent_loop",
                user_id=user_id or None,
                thread_id=str(user_id) if user_id else None,
                error_traceback=error_traceback,
                fingerprint=fingerprint,
                severity=severity,
            )
        )
    except Exception as exc:  # noqa: BLE001 - telemetry must never break a turn
        print(f"[AGENT_LOOP] failed to record incident {fingerprint}: {exc}")


async def _run_tool_loop(
    hist: List[BaseMessage],
    tools: List[Any],
    gap_calls: list,
    ledger: FailureLedger,
    read_only: set,
) -> tuple[str, bool]:
    """Bounded tool-call loop against `hist` in place. Returns (final_text,
    link_tool_used); link_tool_used is True only if search_web/fetch_url
    actually ran, so a raw URL in the reply with link_tool_used=False is
    provably unverified. Appends any log_capability_gap calls' args to
    `gap_calls` so the caller can surface the wishlist button."""
    llm = get_agent_llm(complexity=ThinkingLevel.MEDIUM, temperature=0.7)
    llm_with_tools = llm.bind_tools(tools)
    link_tool_used = False

    # Round-progress tracing: with no per-turn wall-clock ceiling (by design,
    # see MAX_TOOL_ROUNDS above), any single await here -- the model call or
    # a tool call -- can in principle hang without ever raising, and a hung
    # fire-and-forget turn (app/webhook.py) produces zero further log output
    # to explain it. These lines cost one print per round/tool-call so that,
    # if a turn does go silent, Railway logs show exactly which round and
    # which call it was last seen entering instead of nothing at all.
    print("[AGENT_LOOP] round 0: awaiting model completion")
    ai_message = await _invoke_model(llm_with_tools, hist)
    for _round in range(MAX_TOOL_ROUNDS):
        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if not tool_calls:
            break
        hist.append(ai_message)
        if await _execute_tool_calls(
            tool_calls, tools, hist, gap_calls, ledger, read_only,
            round_label=f"round {_round}",
        ):
            link_tool_used = True
        print(f"[AGENT_LOOP] round {_round + 1}: awaiting model completion")
        ai_message = await _invoke_model(llm_with_tools, hist)

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
        final_message = await _invoke_model(llm_with_tools, hist)
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
        retry_message = await _invoke_model(llm_with_tools, hist)
        text = extract_llm_text(getattr(retry_message, "content", "")).strip()
        if not text and getattr(retry_message, "tool_calls", None):
            # The retry decided it needs a tool after all -- let the caller
            # see that via link_tool_used bookkeeping is out of scope here;
            # simplest correct move is one more direct answer pass after
            # actually running that tool call.
            hist.append(retry_message)
            if await _execute_tool_calls(
                retry_message.tool_calls, tools, hist, gap_calls, ledger, read_only,
                round_label="empty-reply retry",
            ):
                link_tool_used = True
            final_retry_message = await _invoke_model(llm_with_tools, hist)
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


async def _compose_reply(
    history: List[BaseMessage], tools: List[Any], gap_calls: list, read_only: set
) -> tuple[str, List[BaseMessage]]:
    pre_loop_len = len(history)
    # One ledger for the whole turn, so a call that keeps failing is still
    # recognised as the same failure across the URL-guard retry below.
    ledger = FailureLedger()
    content, link_tool_used = await _run_tool_loop(history, tools, gap_calls, ledger, read_only)

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
        retried_content, link_tool_used = await _run_tool_loop(
            history, tools, gap_calls, ledger, read_only
        )
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
    timezone_name = str(state.get("current_timezone") or DEFAULT_TIMEZONE)
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

    visible_skills = _visible_skills(is_admin)
    skill_index = _skill_index_text(visible_skills)
    history: List[BaseMessage] = [SystemMessage(content=_build_system_prompt(is_admin=is_admin, timezone_name=timezone_name) + skill_index)]
    # Rebuild provider-facing history WITH prior tool-call provenance: the
    # #53 feature persists AIMessage(tool_calls) + ToolMessage pairs into
    # state, but this loop used to drop every ToolMessage -- so follow-ups
    # like "what other routes" reached the model with zero visibility into
    # the data its own earlier answer was grounded in. The pairing guard
    # keeps the provider history well-formed: a tool result whose request
    # was pruned away (the -10 slice can split a pair) is skipped rather
    # than sent as an orphan, and an AIMessage whose results were split off
    # is flattened to content-only.
    #
    # Regression (live incident, chat=149917165, "Coffee at hive ..."):
    # Gemini rejected the very first call of the turn with 400 INVALID_ARGUMENT
    # "function call turn comes immediately after a user turn or after a
    # function response turn." Root cause -- the -10 prune window can start
    # mid-pair, landing an AIMessage(tool_calls) as the FIRST substantive
    # message in the rebuilt window, with no HumanMessage/ToolMessage turn
    # in front of it at all (the old check only verified its ToolMessage
    # pair existed somewhere *later*, never that a valid anchor turn came
    # *before* it -- SystemMessages don't count, langchain_google_genai
    # merges every non-first one into system_instruction and drops it from
    # the turn sequence entirely, so a tool-calling AIMessage right after
    # one is effectively the conversation's opening turn). Preserve
    # tool_calls only when the turn immediately preceding it in the
    # rebuilt history is itself a human/tool turn -- exactly Gemini's own
    # rule -- otherwise flatten to content-only, same as any other
    # malformed pair.
    def _tool_ids(message: BaseMessage) -> set:
        return {
            str(c.get("id") or c.get("name") or "")
            for c in (getattr(message, "tool_calls", None) or [])
        }

    expected_tool_ids: set = set()
    last_turn_kind: str | None = None  # "human" | "tool" | "ai" | "ai_tc" | None
    for idx, message in enumerate(pruned):
        if isinstance(message, SystemMessage):
            history.append(SystemMessage(content=str(message.content)))
            # Not a turn a provider ever sees (see comment above) -- doesn't
            # change what the *next* message can safely anchor against.
        elif isinstance(message, HumanMessage):
            expected_tool_ids = set()
            history.append(
                HumanMessage(content=message.content if isinstance(message.content, list) else str(message.content))
            )
            last_turn_kind = "human"
        elif isinstance(message, AIMessage):
            ids = _tool_ids(message)
            if ids and last_turn_kind in ("human", "tool"):
                remaining_ids = {
                    str(getattr(m, "tool_call_id", "") or "")
                    for m in pruned[idx + 1:]
                    if isinstance(m, ToolMessage)
                }
                if ids <= remaining_ids:
                    history.append(message)  # well-formed pair: keep tool_calls
                    expected_tool_ids = ids
                    last_turn_kind = "ai_tc"
                    continue
            history.append(AIMessage(content=str(message.content)))
            expected_tool_ids = set()
            last_turn_kind = "ai"
        elif isinstance(message, ToolMessage):
            tool_id = str(getattr(message, "tool_call_id", "") or "")
            if tool_id in expected_tool_ids:
                history.append(message)
                expected_tool_ids.discard(tool_id)
                last_turn_kind = "tool"
            # else: orphaned by pruning -- skip to keep provider history valid

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
                tools = _build_tool_roster(visible_skills)
                try:
                    content, extra_messages = await _compose_reply(
                        history, tools, gap_calls, _read_only_tool_names(visible_skills)
                    )
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
                    import traceback

                    print(f"[AGENT_LOOP] tool loop failed, using fallback: {exc}")
                    # The user just got a non-answer. That is a P1 incident, and
                    # until now it was only ever a print: this except swallows
                    # the failure, so ingress's report_production_bug (which
                    # sits outside it) never saw a single one of them.
                    _report_agent_failure(
                        subsystem="agent_loop",
                        error_context=f"Agent turn failed and fell back to an error reply: {exc}",
                        severity="P1",
                        fingerprint=f"agent_loop_failure_{type(exc).__name__}",
                        user_id=user_id,
                        error_traceback=traceback.format_exc(),
                    )
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
        fire_and_forget(
            perform_conversation_audit(
                user_id=user_id,
                thread_id=str(user_id),
                messages=turn_messages,
            )
        )

    return Command(goto=END, update=update)
