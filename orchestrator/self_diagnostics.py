"""Self-diagnosis: when the user asks why the bot did something or why
something isn't working, answer honestly from the bot's own last routing
decision plus live integration health -- instead of running the question
through normal capability routing.

Routing it normally is exactly the failure mode this exists to avoid: this
class of message ("this is broken", "is it not working?", "why is this
happening") has repeatedly gotten misrouted into a random capability's own
disambiguation flow (see #48's "🤔 Which board?" misfire) rather than
actually being answered. Intercepting it deterministically, before the
planner ever sees it, sidesteps that whole bug class for this one intent.

Deliberately scoped to "self-explain + integration health": it explains the
bot's own last turn and names real, live-checkable causes (a missing API
key, a disconnected mailbox, a known tracked bug). It does not pull tool
call tracebacks or raw error logs -- that's a heavier, separate feature.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from orchestrator.state import AssistantState

# Deliberately narrow and self-referential: these patterns target the bot's
# OWN recent behavior/state ("why did YOU...", "is THIS broken"), not a
# domain question that happens to contain "why" -- e.g. "why is my flight
# not showing up" is a real email-capability question and must NOT be
# intercepted here. When in doubt, patterns stay narrow: a missed self-
# diagnostic question just falls through to normal routing (unchanged
# behavior), but a false positive here hijacks the turn from a legitimate
# capability, which is the more expensive mistake.
_SELF_DIAGNOSTIC_PATTERNS = (
    r"\bwhy\s+(?:did|didn'?t|does|doesn'?t|is|isn'?t|are|aren'?t|won'?t|can'?t|couldn'?t)\s+you\b",
    r"\bwhy\s+(?:is|isn'?t|did|didn'?t)\s+(?:this|it|that)\s+(?:happen|happening|not\s+work|broken)",
    r"\b(?:this|it|that)\s+(?:is|'s)\s+(?:broken|not\s+working|glitch\w*|bugg\w*)\b",
    r"\bis\s+(?:this|it|something)\s+(?:broken|wrong|not\s+working)\b",
    r"\bwhat(?:'?s| is| went)\s+(?:wrong|broken|going on)\b",
    r"\b(?:can you )?(?:debug|troubleshoot)\s+(?:this|that|it)\b",
)
_SELF_DIAGNOSTIC_RE = re.compile("|".join(_SELF_DIAGNOSTIC_PATTERNS), re.IGNORECASE)


def looks_like_self_diagnostic_question(text: str) -> bool:
    """True when `text` reads as a meta-question about the bot's own
    recent behavior/state, rather than an ordinary domain request."""
    return bool(_SELF_DIAGNOSTIC_RE.search(text or ""))


async def check_integration_health(user_id: int) -> dict[str, Any]:
    """Lightweight, presence-only health snapshot: what's configured and
    connected right now. Not a deep live probe -- no outbound call to
    verify a token still actually works, just whether one is on file."""
    from core.config import settings
    from capabilities.email.tools import get_user_gmail_token, get_user_outlook_token

    gmail_token: Optional[str] = None
    outlook_token: Optional[str] = None
    try:
        gmail_token = await get_user_gmail_token(user_id)
    except Exception:  # noqa: BLE001 - health check must never itself fail the turn
        pass
    try:
        outlook_token = await get_user_outlook_token(user_id)
    except Exception:  # noqa: BLE001
        pass

    return {
        "llm_provider_configured": settings.has_llm_key,
        "web_search_configured": bool(
            settings.tavily_api_key and not settings.tavily_api_key.startswith("your_")
        ),
        "maps_configured": bool(settings.google_maps_api_key),
        "transit_live_data_configured": bool(settings.lta_account_key),
        "gmail_connected": bool(gmail_token),
        "outlook_connected": bool(outlook_token),
    }


async def recent_known_issues(user_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """Open, already-tracked production bugs for this user -- lets the bot
    say "yeah, that's a known issue, already being looked at" instead of
    re-diagnosing something the audit pipeline already caught and filed."""
    from sqlmodel import select
    from core.db import async_session_factory
    from core.models import ProductionBugLog

    async with async_session_factory() as session:
        result = await session.execute(
            select(ProductionBugLog)
            .where(ProductionBugLog.user_id == user_id, ProductionBugLog.status == "open")
            .order_by(ProductionBugLog.updated_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
    return [
        {
            "title": row.title,
            "subsystem": row.subsystem,
            "severity": row.severity,
            "github_issue_url": row.github_issue_url,
        }
        for row in rows
    ]


_SYSTEM_PROMPT = (
    "You are Nexus Prime, debugging your own recent behavior for the user who "
    "just asked why something happened or isn't working. You are given three "
    "sources of ground truth: (1) the recent conversation, (2) your own internal "
    "routing decision for the last turn (which capability you picked, your "
    "confidence, whether you had to re-plan, your internal rationale), and (3) "
    "the current live status of your own integrations/API keys and any known "
    "tracked bugs already filed for this user.\n\n"
    "Explain honestly and simply what happened and why, in plain conversational "
    "language -- never mention internal field names, code, file paths, or raw "
    "JSON. If a real, nameable cause is present in the data below (a missing API "
    "key, a disconnected mailbox, a known open bug), say so plainly and suggest "
    "one concrete next step. If nothing below explains it, say you're not sure "
    "and offer to have the user try again or rephrase -- never invent a cause "
    "that isn't backed by the data given."
)


async def explain_last_turn(state: AssistantState) -> Optional[str]:
    """Compose an honest, plain-language explanation of the bot's own last
    turn plus current integration health. Returns None when there's nothing
    to introspect yet (e.g. the very first message in a conversation) or the
    LLM call fails, so the caller can fall back to normal routing."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from core.llm import ThinkingLevel, extract_llm_text, get_agent_llm

    user_id = state.get("user_id", 0)
    last_decision = state.get("last_decision")
    messages = state.get("messages", [])

    # Recent turns for context, excluding the "why" question itself (the
    # newest message) -- a handful of prior turns is enough to ground the
    # explanation without ballooning the prompt.
    tail = messages[-7:-1] if len(messages) > 1 else []
    transcript_lines = []
    for m in tail:
        if isinstance(m, HumanMessage):
            transcript_lines.append(f"User: {str(m.content)[:300]}")
        elif isinstance(m, AIMessage):
            transcript_lines.append(f"Assistant: {str(m.content)[:300]}")

    if not last_decision and not transcript_lines:
        return None

    health = await check_integration_health(user_id)
    known_issues = await recent_known_issues(user_id)

    context_parts = [
        "Recent conversation:\n" + ("\n".join(transcript_lines) or "(none)"),
        "Your last routing decision:\n"
        + (json.dumps(last_decision, ensure_ascii=False) if last_decision else "(none recorded)"),
        "Your integration health right now:\n" + json.dumps(health, ensure_ascii=False),
        "Known open bugs already tracked for this user:\n"
        + (json.dumps(known_issues, ensure_ascii=False) if known_issues else "(none)"),
    ]

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.MEDIUM, temperature=0.3)
        ai_message = await llm.ainvoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content="\n\n".join(context_parts)),
            ]
        )
    except Exception as exc:  # noqa: BLE001 - never let self-diagnosis itself break the turn
        print(f"[SELF_DIAGNOSTIC] explain_last_turn failed: {exc}")
        return None

    return extract_llm_text(getattr(ai_message, "content", "")).strip() or None
