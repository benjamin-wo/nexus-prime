"""Deep-reasoning planning intake for whiteboards.

Turns freeform multi-part requests ("trip to Bali 3rd-6th Sept, villa booked,
bachelor party, Finn's beach club Saturday...") into a validated PlanningBrief:
entities that become cards, questions worth asking, and topics worth researching.
"""

import json
import re
from typing import Any, Dict, List, Optional

from core.config import settings

ALLOWED_ACTIONS = {"create_board", "augment_board", "none"}
ALLOWED_CATEGORIES = {"trip", "event", "project", "meal", "general"}
ALLOWED_ENTITY_KINDS = {
    "accommodation", "event", "activity", "food", "transport", "note",
}
ALLOWED_STATUS = {"booked", "confirmed", "tbd"}

ENTITY_SECTION_DEFAULTS = {
    "accommodation": "Stays & Options",
    "event": "Itinerary",
    "activity": "Day Plans",
    "food": "Food & Drinks",
    "transport": "Transport",
    "note": "Notes",
}

COMPREHEND_SYSTEM_PROMPT = (
    "You are the deep-reasoning intake engine of a personal assistant's planning whiteboard.\n"
    "Analyze EVERY part of the user's request and reply with ONLY a JSON object:\n"
    "{\n"
    '  "action": "create_board" | "augment_board" | "none",\n'
    '  "board_title": string,\n'
    '  "category": "trip"|"event"|"project"|"meal"|"general",\n'
    '  "summary": string,\n'
    '  "destination": string,\n'
    '  "date_range": string,\n'
    '  "occasion": string,\n'
    '  "entities": [\n'
    '     {"kind": "accommodation"|"event"|"activity"|"food"|"transport"|"note",\n'
    '      "title": string, "details": string,\n'
    '      "status": "booked"|"confirmed"|"tbd"}\n'
    '  ],\n'
    '  "follow_up_questions": [string],\n'
    '  "research_queries": [string]\n'
    "}\n\n"
    "Reasoning rules:\n"
    "1. Decompose the request clause by clause. Each concrete thing mentioned "
    "(a booked villa, a beach club visit, a meal idea, a fitness class) becomes ONE entity. "
    "Use the details field for addresses, dates, day-of-week, who it is for.\n"
    "2. status='booked' only when the user says it is already paid/reserved; "
    "'confirmed' for firm plans; 'tbd' for ideas.\n"
    "3. follow_up_questions: max 3, only genuinely useful gaps (headcount, budget, arrival time, dietary needs). Never ask what is already stated.\n"
    "4. research_queries: max 4 web-search queries for things the user wants figured out "
    "(venues, restaurants, activities). Make them specific with location + constraint.\n"
    "5. action='augment_board' when a target board already exists and the request adds to it; "
    "'create_board' for a new plan; 'none' when the text is not a planning request at all.\n"
    "6. board_title: short and evocative (e.g. 'Bali Bachelor Party'). Include destination when known.\n"
)


def validate_brief(raw: Any) -> Optional[Dict[str, Any]]:
    """Normalize + validate an LLM PlanningBrief; returns clean dict or None."""
    if not isinstance(raw, dict):
        return None
    action = raw.get("action")
    if action not in ALLOWED_ACTIONS:
        return None
    if action == "none":
        return {"action": "none"}

    entities_raw = raw.get("entities") or []
    entities = []
    for e in entities_raw[:12]:
        if not isinstance(e, dict):
            continue
        title = str(e.get("title") or "").strip()
        if not title:
            continue
        kind = e.get("kind") if e.get("kind") in ALLOWED_ENTITY_KINDS else "note"
        status = e.get("status") if e.get("status") in ALLOWED_STATUS else "tbd"
        entities.append({
            "kind": kind,
            "title": title[:120],
            "details": str(e.get("details") or "").strip()[:600],
            "status": status,
        })

    questions = [
        str(q).strip()[:200]
        for q in (raw.get("follow_up_questions") or [])[:3]
        if isinstance(q, str) and q.strip()
    ]
    research = [
        str(q).strip()[:160]
        for q in (raw.get("research_queries") or [])[:4]
        if isinstance(q, str) and q.strip()
    ]

    category = raw.get("category") if raw.get("category") in ALLOWED_CATEGORIES else "general"
    title = str(raw.get("board_title") or "").strip()[:80] or "New Plan"

    return {
        "action": action,
        "board_title": title,
        "category": category,
        "summary": str(raw.get("summary") or "").strip()[:300] or None,
        "destination": str(raw.get("destination") or "").strip()[:100] or None,
        "date_range": str(raw.get("date_range") or "").strip()[:60] or None,
        "occasion": str(raw.get("occasion") or "").strip()[:100] or None,
        "entities": entities,
        "follow_up_questions": questions,
        "research_queries": research,
    }


async def comprehend_request(
    text: str,
    board_context: Optional[Dict[str, Any]] = None,
    recent_context: str = "",
) -> Optional[Dict[str, Any]]:
    """Run the deep-reasoning comprehension pass over a freeform planning request.

    recent_context (#35): the last few conversation turns, for resolving a
    reactive follow-up ("no budget but thinking of some fitness club Friday")
    against what was just discussed -- planning is inherently multi-turn, and
    this plugin previously only ever saw the single latest message. Purely
    additional grounding for the LLM pass; board_context and the deterministic
    entity-materialization pipeline below are unaffected.
    """
    if not settings.has_llm_key:
        return _heuristic_brief(text)

    from langchain_core.messages import HumanMessage, SystemMessage
    from core.llm import ThinkingLevel, get_agent_llm

    context_lines = []
    if recent_context:
        context_lines.append(
            "Recent conversation, for resolving references like 'that one too' or "
            "a reactive follow-up -- the request below the --- separator is the "
            f"user's CURRENT message and takes priority:\n{recent_context}"
        )
    if board_context:
        if board_context.get("explicit_match"):
            context_lines.append(
                f"The user is referring to an existing board: #{board_context.get('id')} titled "
                f"'{board_context.get('title')}' (category: {board_context.get('category')}). "
                "Prefer action='augment_board' for this board."
            )
        else:
            context_lines.append(
                f"Note: board #{board_context.get('id')} '{board_context.get('title')}' was recently active, "
                "but the user did not name it. If the request describes a DIFFERENT trip or occasion, "
                "choose action='create_board' with a fresh board_title; only choose 'augment_board' "
                "when the request clearly continues that same plan."
            )
        sections = board_context.get("sections") or []
        if sections:
            context_lines.append(f"Existing sections: {sections}")

    user_content = text[:4000]
    if context_lines:
        user_content = "\n".join(context_lines) + "\n\n---\n\n" + user_content

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.HIGH, temperature=0.2)
        ai_message = await llm.ainvoke(
            [SystemMessage(content=COMPREHEND_SYSTEM_PROMPT), HumanMessage(content=user_content)]
        )
        raw = str(getattr(ai_message, "content", "") or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return _heuristic_brief(text)
        parsed = json.loads(raw[start:end + 1])
        brief = validate_brief(parsed)
        return brief or _heuristic_brief(text)
    except Exception as exc:  # noqa: BLE001 - intake must degrade gracefully
        print(f"[WHITEBOARD] comprehension failed, using heuristics: {exc}")
        return _heuristic_brief(text)


def _heuristic_brief(text: str) -> Optional[Dict[str, Any]]:
    """Offline fallback: minimal create brief so basic flows still work without an LLM key."""
    lowered = (text or "").lower()
    trip_words = ("trip", "travel", "vacation", "holiday", "getaway")
    planish = ("plan", "organize", "organise", "bachelor", "itinerary", "party")
    if not any(w in lowered for w in planish + trip_words):
        return {"action": "none"}
    m = re.search(
        r"(?:trip|travel|vacation|holiday|getaway)\s+(?:to|in)\s+([a-z][a-z\s\-]{2,38}?)"
        r"(?=\s+(?:for|from|on|with|and|during)\b|\s+\d|\s*$)",
        lowered,
    )
    destination = m.group(1).strip() if m else None
    if destination:
        destination = re.sub(r"\s+(for|the|a|on|with|and)$", "", destination).strip().title()
    title = f"{('Trip to ' + destination) if destination else 'New Trip'}"
    return {
        "action": "create_board",
        "board_title": title,
        "category": "trip" if any(w in lowered for w in trip_words) else "general",
        "summary": None,
        "destination": destination,
        "date_range": None,
        "occasion": None,
        "entities": [],
        "follow_up_questions": [],
        "research_queries": [],
    }
