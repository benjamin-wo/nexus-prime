"""Decision object and planner for retrieve -> plan -> select a set.

The planner consumes the C2 retrieval shortlist plus thread state and emits a
Decision: a *set* of capabilities with ordering, explicit insufficiency, and
confidence. Managers are derived tags and never appear as routing hops.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
import json

from capabilities.retrieval import RetrievalResult
from orchestrator.state import AssistantState


@dataclass(frozen=True)
class CapabilitySelection:
    id: str
    reason: str
    confidence: float


@dataclass(frozen=True)
class InsufficientCapability:
    missing_capabilities: list[str]
    reasons: list[str]
    message: str = ""


@dataclass(frozen=True)
class Decision:
    capabilities: list[CapabilitySelection] = field(default_factory=list)
    ordering: list[str] = field(default_factory=list)
    insufficient: Optional[InsufficientCapability] = None
    question: Optional[str] = None
    confidence: float = 0.0
    source: str = "deterministic"
    retrieval_used: bool = True
    recipe: Optional[str] = None
    rationale: Optional[str] = None

    @property
    def capability_ids(self) -> list[str]:
        return [c.id for c in self.capabilities]

    @property
    def planned_set(self) -> set[str]:
        ids = set(self.capability_ids)
        if self.insufficient:
            ids.update(self.insufficient.missing_capabilities)
        return ids


CONTINUATION_PATTERNS = [
    r"^and what about",
    r"^what about next",
    r"^what about that",
    r"^and next",
    r"^and then",
    r"^how about next",
]

TERMINATION_INTENTS = {
    "stop", "stop it", "cancel", "cancel that", "never mind", "nevermind",
    "forget it", "forget about it", "that's enough", "that's all", "thats all",
    "i'm done", "im done", "i'm good", "im good", "all good", "ok", "okay",
    "ok stop", "okay stop", "that's it", "thats it", "drop it", "quit",
    "enough", "no more", "stop talking", "shut up", "leave it",
}


def is_termination_intent(text: str) -> bool:
    """True for explicit stop/closing commands so the router can terminate an
    active thread instead of re-planning it into a loop."""
    lowered = (text or "").strip().lower()
    if not lowered or len(lowered) > 60:
        return False
    if lowered in TERMINATION_INTENTS:
        return True
    return re.fullmatch(r"stop(?:!|\.)*", lowered) is not None

AMBIGUITY_PATTERNS = [
    r"^how am i doing",
    r"^how are we doing",
    r"^what('s| is) my status",
    r"^how is everything",
]

RECIPE_TRIGGERS: dict[str, list[str]] = {
    "briefing": ["good morning", "goodmorning", "what's up today", "brief me", "morning brief"],
    "spend_autopsy": [
        "where did my money go",
        "where does my money go",
        "analyze my spending",
        "spend analysis",
        "spending analysis",
        "top merchants",
        "top categories",
    ],
    "grocery_run": ["grocery run", "need groceries", "plan my grocery", "do groceries"],
    "commute_conditions": [
        "commute like",
        "commute tomorrow",
        "commute weather",
        "leave early if",
        "commute to",
    ],
    "bill_watch": ["track my bills", "bill watch", "did i pay", "bills due", "my bills"],
}

RECIPE_CAPABILITIES: dict[str, list[str]] = {
    "briefing": ["email", "expenses", "reminders"],
    "spend_autopsy": ["expenses", "code_exec"],
    "grocery_run": ["recipes", "routes", "reminders"],
    "commute_conditions": ["routes", "general", "reminders"],
    "bill_watch": ["email", "expenses", "reminders"],
}


def _recipe_for(text: str) -> Optional[str]:
    for recipe_id, phrases in RECIPE_TRIGGERS.items():
        if any(phrase in text for phrase in phrases):
            return recipe_id
    return None


def _has(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


_STRONG_PLANNING_SIGNALS = (
    "trip", "travel", "vacation", "holiday", "getaway", "itinerary",
    "packing list", "airbnb", "villa", "beach club", "bachelor", "bachelorette",
)


def in_planning_thread(state: Any = None, text: str = "") -> bool:
    """True when this conversation is an active planning/board thread.

    Uses the persisted active domain plus the last few human messages, because a
    single detour through general chat must not orphan an ongoing plan."""
    if (state or {}).get("active_domain") == "whiteboard":
        return True
    lowered_now = (text or "").lower()
    if any(w in lowered_now for w in _STRONG_PLANNING_SIGNALS):
        return True
    messages = (state or {}).get("messages") or []
    humans = [str(getattr(m, "content", "")) for m in messages if getattr(m, "type", "") == "human"]
    return any(
        any(w in msg.lower() for w in _STRONG_PLANNING_SIGNALS)
        for msg in humans[-3:]
    )


def is_email_connection_request(text: str) -> bool:
    """Detect mailbox onboarding before the general planner can call it a gap."""
    lowered = (text or "").lower()
    connect_words = (
        "connect", "link", "integrat", "authoriz", "grant access", "set up", "setup", "add",
    )
    mailbox_words = (
        "email", "mailbox", "gmail", "outlook", "hotmail", "microsoft mail", "office 365",
    )
    return any(word in lowered for word in connect_words) and any(word in lowered for word in mailbox_words)


def is_email_disconnect_request(text: str) -> bool:
    """Detect a request to revoke/remove mailbox access."""
    lowered = (text or "").lower()
    disconnect_words = (
        "disconnect", "unlink", "revoke", "remove access", "stop reading", "stop checking",
        "stop scanning", "forget my", "delete my email connection",
    )
    mailbox_words = (
        "email", "mailbox", "gmail", "outlook", "hotmail", "microsoft mail", "office 365",
    )
    return any(word in lowered for word in disconnect_words) and any(word in lowered for word in mailbox_words)


def is_latest_email_request(text: str) -> bool:
    """Detect an informational "latest email" request (newest messages), as opposed
    to a financial sweep ("find receipts", "log expenses")."""
    lowered = (text or "").lower()
    latest_phrases = (
        "latest email", "latest emails", "latest mail", "latest message", "latest messages",
        "newest email", "newest emails", "newest mail", "newest message", "newest messages",
        "most recent email", "most recent emails", "most recent mail", "most recent message",
        "most recent messages",
        "check the latest", "check my latest", "see the latest", "see my latest",
        "what's the latest", "what is the latest", "whats the latest",
        "any new emails", "any new email", "any new mail",
    )
    return any(phrase in lowered for phrase in latest_phrases)


_FINANCIAL_EMAIL_WORDS = (
    "receipt", "bill", "invoice", "statement", "payment", "transaction", "expense",
    "spent", "spend", "refund", "salary", "payroll", "bank", "transfer", "charge",
    "amount due", "fee", "tax", "credited",
)


def is_financial_email_request(text: str) -> bool:
    """Detect an explicit financial-intent email request that should use the
    keyword sweep instead of the plain newest-messages fetch."""
    lowered = (text or "").lower()
    return any(word in lowered for word in _FINANCIAL_EMAIL_WORDS)


def _has_word(text: str, words: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


_RETROSPECTIVE_QUERY_MARKERS = (
    "did i", "have i", "did we", "have we", "when did i", "when did we",
    "check my email", "check my outlook", "check my gmail", "check my inbox",
)


def missing_policy(text: str) -> list[str]:
    """Missing-capability detection. Deliberately narrower than the legacy guardrail."""
    missing: list[str] = []
    if _has(text, ["calendar", "appointment", "meeting", "invite"]):
        missing.append("calendar")
    # "book a flight"/"book a hotel" are meant to catch forward-looking booking
    # requests. A retrospective status check ("did I book a flight on 24 Jul?
    # Check my outlook") contains the same substring but is really an email
    # lookup — flagging it as a missing flight_booking capability blocks (or
    # muddies) the perfectly-supported email search instead.
    if not _has(text, _RETROSPECTIVE_QUERY_MARKERS) and _has(
        text, ["book a flight", "flight to ", "flight from ", "book a hotel"]
    ):
        missing.append("flight_booking")
    if _has(text, ["transfer", "send money", "wire "]):
        missing.append("bank_transfer")
    if _has(text, ["turn on", "turn off", "lights", "thermostat", "smart home"]):
        missing.append("smart_home")
    if _has(text, ["book a table", "reserve a table", "restaurant booking"]):
        missing.append("restaurant_booking")
    if _has(text, ["budget at risk", "my budget", "set a budget", "budget limit", "track budget", "over budget", "under budget", "trip budget"]):
        missing.append("budget")
    if re.search(r"email .* to me|email me|send me? .* to my email|send .* by email", text):
        missing.append("email_send")
    return missing


def _candidate_selections(text: str, missing: list[str]) -> list[CapabilitySelection]:
    selections: list[CapabilitySelection] = []

    def add(cap_id: str, words: list[str], reason: str, confidence: float = 0.9) -> None:
        if cap_id == "email" and "email_send" in missing:
            return
        if _has(text, words):
            selections.append(CapabilitySelection(id=cap_id, reason=reason, confidence=confidence))

    add("email", ["email", "gmail", "outlook", "hotmail", "inbox", "mail"], "email-related intent")
    if _has(text, ["salary", "paycheck"]):
        selections.append(CapabilitySelection(id="email", reason="salary/paycheck check", confidence=0.85))
    # Finding a receipt (no expense action verb) is an email search, not a log.
    if "receipt" in text and not _has(text, ["spent", "spend", "paid", "log", "expense"]):
        selections.append(CapabilitySelection(id="email", reason="receipt search in inbox", confidence=0.85))

    if "bank_transfer" not in missing:
        add("expenses", ["spent", "spend", "paid", "expense", "cost ", "$", "log "],
            "expense logging/listing intent")
    if "receipt" in text and _has(text, ["spent", "spend", "paid", "log", "expense"]):
        selections.append(CapabilitySelection(id="expenses", reason="receipt expense logging", confidence=0.85))
    if "receipt" in text and _has(text, ["inbox", "email", "gmail"]):
        selections.append(CapabilitySelection(id="expenses", reason="receipts found in email get logged", confidence=0.8))

    add("routes", [
        "route", "drive", "driving", "transit", "mrt", "train",
        "traffic", "direction", "how do i get", "get to", "fastest way",
        "way home", "way to", "next bus",
    ], "route/transit intent")
    # "bus" and "eta" are short tokens: match on word boundaries so "tembusu"
    # (contains 'bus') or "theta" (contains 'eta') never trigger routes.
    if _has_word(text, ["bus", "eta"]):
        selections.append(
            CapabilitySelection(id="routes", reason="transit token match", confidence=0.85)
        )

    groceries_as_reminder_content = bool(
        re.search(r"remind .*(buy|get) groceries", text)
        or re.search(r"remind .*(buy|get) ingredients", text)
    )
    if not groceries_as_reminder_content:
        add("recipes", ["recipe", "grocery", "groceries", "ingredient", "cook", "pasta", "fridge"],
            "recipe/grocery intent")

    add("reminders", ["remind", "reminder", "cron"], "reminder/scheduling intent")

    add("bug_logging", [
        "log it as a bug", "log a bug", "report a bug", "file a bug",
        "log this as a bug", "log that as a bug", "bug report",
        "there seems to be an issue with", "there is an issue with",
    ], "bug logging intent")

    add("scheduled_content_delivery", [
        "daily morning summary", "news briefing", "stock market news",
        "daily briefing", "morning briefing", "news summary", "briefing of the",
        "global news and stock", "send me a daily",
    ], "scheduled content delivery intent")

    add("whiteboard", [
        "whiteboard", "white board", "planning board", " boards",
        "plan a trip", "plan my trip", "plan our trip", "plan a", "plan my",
        "trip to", "vacation", "holiday", "getaway", "bachelor",
        "itinerary", "shortlist", "packing list", "pin to",
    ], "planning/board intent")

    add("general", [
        "who is", "capital", "weather", "rain", "rains", "news", "search the web",
        "search for", "explain", "how many", "translate", "definition",
    ], "general/fallback intent")

    if _has(text, ["timezone", "landed in", "arrived in", "switch my timezone"]):
        selections.append(CapabilitySelection(id="timezone", reason="core timezone fast path", confidence=0.95))

    # De-duplicate while keeping first (highest-priority) reason.
    seen: set[str] = set()
    unique: list[CapabilitySelection] = []
    for sel in selections:
        if sel.id not in seen:
            seen.add(sel.id)
            unique.append(sel)
    return unique


def _retrieval_ids(result: RetrievalResult) -> set[str]:
    ids = {h.id for h in result.top}
    if result.recovered:
        ids.update(h.id for h in result.expanded)
    return ids


def deterministic_plan(
    user_text: str,
    state: dict[str, Any] | AssistantState,
    retrieval: Optional[RetrievalResult] = None,
) -> Decision:
    text = (user_text or "").strip().lower()

    # Probe 3: referent continuation reuses the last decision without full re-retrieval.
    if any(re.match(pattern, text) for pattern in CONTINUATION_PATTERNS):
        last = (state or {}).get("last_decision")
        if last and last.get("capabilities"):
            reused = [
                CapabilitySelection(
                    id=cap["id"],
                    reason="referent continuation of previous turn",
                    confidence=float(cap.get("confidence", 0.8)),
                )
                for cap in last["capabilities"]
            ]
            return Decision(
                capabilities=reused,
                ordering=[cap.id for cap in reused],
                confidence=0.85,
                source="referent-reuse",
                retrieval_used=False,
                rationale="Referent continuation of the previous turn; reusing its capability set without re-retrieval.",
            )
        active = (state or {}).get("active_domain")
        if active and active in {"email", "expenses", "routes", "recipes", "reminders", "whiteboard", "general"}:
            return Decision(
                capabilities=[CapabilitySelection(id=active, reason="referent continuation of active domain", confidence=0.8)],
                ordering=[active],
                confidence=0.8,
                source="referent-reuse",
                retrieval_used=False,
                rationale="Referent continuation using the active thread domain.",
            )

    # Probe 4: ambiguity gets one disambiguating question, never silent guessing.
    if any(re.match(pattern, text) for pattern in AMBIGUITY_PATTERNS):
        return Decision(
            question=(
                "Did you mean your spending, your reminders, or something else? "
                "Tell me which and I'll pull it up."
            ),
            confidence=0.3,
            source="deterministic",
            retrieval_used=False,
            rationale="Ambiguous request; asking one disambiguating question instead of guessing.",
        )

    active_routes_thread = (state or {}).get("active_domain") == "routes" or (
        (state or {}).get("last_decision") or {}
    ).get("ordering") == ["routes"]
    if active_routes_thread and re.fullmatch(r"[a-z0-9 ,'\-\.]{2,40}", text):
        if not re.search(
            r"\b(please|me|my|the|what|when|how|which|route|bus|buses|remind|expense|"
            r"email|grocery|recipe|bill|to|from|at|near|next|arriv|"
            r"no|not|yes|yeah|nah|other|others|different|instead|again|want|wanna|dont)\b",
            text,
        ):
            return Decision(
                capabilities=[
                    CapabilitySelection(
                        id="routes",
                        reason="bare place fragment in an active route thread",
                        confidence=0.8,
                    )
                ],
                ordering=["routes"],
                confidence=0.8,
                source="fragment-reuse",
                retrieval_used=False,
                rationale=(
                    "Short place-name follow-up in an active route thread; reusing routes "
                    "and letting the plugin fill the missing endpoint from last_route."
                ),
            )

    recipe = _recipe_for(text)
    if recipe:
        capabilities = [
            CapabilitySelection(
                id=cap_id,
                reason=f"recipe:{recipe}",
                confidence=0.9,
            )
            for cap_id in RECIPE_CAPABILITIES[recipe]
        ]
        return Decision(
            capabilities=capabilities,
            ordering=[cap.id for cap in capabilities],
            confidence=0.9,
            source="recipe",
            retrieval_used=True,
            recipe=recipe,
            rationale=f"Recipe trigger matched: {recipe}.",
        )

    missing = missing_policy(text)
    candidates = _candidate_selections(text, missing)

    # Active planning thread: keep board follow-ups on the whiteboard instead of
    # letting them dissolve into general chat.
    if (
        in_planning_thread(state, text)
        and any(
            w in text for w in (
                "trip", "villa", "hotel", "airbnb", "flight", "booked", "booking",
                "lunch", "dinner", "breakfast", "brunch", "restaurant", "club",
                "beach", "party", "fitness", "gym", "yoga", "spa", "activity",
                "itinerary", "friday", "saturday", "sunday", "monday", "pack",
                "headcount", "budget", "plan",
            )
        )
        and (not candidates or all(c.id == "general" for c in candidates))
    ):
        candidates = [
            CapabilitySelection(id="whiteboard", reason="planning follow-up in active board thread", confidence=0.85)
        ]

    # Honest insufficiency: if every candidate is blocked by a missing capability,
    # say so directly instead of routing somewhere wrong.
    if not candidates and missing:
        return Decision(
            insufficient=InsufficientCapability(
                missing_capabilities=missing,
                reasons=["no registered capability can fulfil this request"],
                message=_insufficiency_message(missing),
            ),
            confidence=0.9,
            source="deterministic",
            retrieval_used=bool(retrieval),
            rationale="No registered capability can fulfil this request; refusing honestly.",
        )

    if not candidates:
        candidates = [
            CapabilitySelection(id="general", reason="no specific capability matched", confidence=0.6)
        ]

    if retrieval is not None:
        available = _retrieval_ids(retrieval)
        # Timezone is a core fast path; whiteboard follow-ups are validated by
        # conversation context (in_planning_thread), not by keyword retrieval.
        exempt = {"timezone"}
        if in_planning_thread(state, text):
            exempt.add("whiteboard")
        candidates = [c for c in candidates if c.id in available or c.id in exempt]
        if not candidates:
            candidates = [
                CapabilitySelection(id="general", reason="no retrieval corroboration", confidence=0.5)
            ]

    ordering = [c.id for c in candidates]
    confidence = round(min(0.97, 0.75 + 0.04 * len(candidates)), 3)
    return Decision(
        capabilities=candidates,
        ordering=ordering,
        insufficient=(
            InsufficientCapability(
                missing_capabilities=missing,
                reasons=["capability not registered"],
                message=_insufficiency_message(missing),
            )
            if missing
            else None
        ),
        confidence=confidence,
        source="deterministic",
        retrieval_used=True,
        rationale="Retrieved the shortlist and selected matching capabilities by intent rules.",
    )


def _insufficiency_message(missing: list[str]) -> str:
    names = ", ".join(f"#{tag}" for tag in missing)
    if "budget" in missing:
        return (
            f"I can answer the part I have tools for, but I don't have a budget "
            f"capability yet ({names}) — I won't invent a number for it."
        )
    return (
        f"I can't do that yet: no capability exists for {names}. "
        "Want me to log it as a feature request?"
    )


def llm_plan_prompt(
    user_text: str,
    shortlist: list[dict[str, Any]],
    state: dict[str, Any] | AssistantState | None = None,
) -> list[dict[str, str]]:
    """Production planner prompt (Anthropic parallel-tool-use style decision).

    Unverified — assumption: this prompt is not exercised in this environment
    (no API keys); the deterministic planner is the measured artifact.
    """
    shortlist_text = "\n".join(
        f"- {item['id']}: {item['description']} (score {item['score']:.3f})"
        for item in shortlist
    )
    system = (
        "You are the Nexus Prime planner working in the background. Understand the user's intent, "
        "and select the capability plugins needed.\n"
        "CAPABILITY SELECTION RULES:\n"
        "1. 'whiteboard' handles ALL planning requests: creating or updating trip/event/project/meal "
        "boards, itineraries, shortlists, packing lists, bookings to organize, brainstorming ideas, "
        "and follow-ups that add activities, food, spas, or logistics to a plan. It captures structured "
        "cards and researches options — prefer it over 'general' for anything plan-shaped.\n"
        "2. Use 'general' for factual questions, casual chat, definitions, news, or explanations that "
        "do not involve organizing a plan or updating a board. If an active planning thread exists "
        "(Current thread domain: whiteboard), keep planning-related follow-ups on 'whiteboard'.\n"
        "3. The 'question' field MUST BE null unless the input is a single isolated word with zero context (e.g. 'check'). NEVER use 'question' to interview the user or ask for trip details/budgets.\n"
        "4. Route to 'email' whenever the user references a specific message, sender, or bank/company name "
        "they expect you to have seen (e.g. \"did u see the one from DBS today?\", \"there's an email from "
        "payroll\"), even without the literal word 'email' — never answer from memory or assumption about "
        "inbox contents.\n"
        "5. If an active thread domain is given (e.g. \"Current thread domain: routes\") and the message is "
        "a short reactive follow-up about the same thing — a correction, a request for alternatives, "
        "confirming/rejecting an option (e.g. \"no I want other buses\", \"what about walking instead\") — "
        "keep it on that same domain rather than dropping to 'general'. Never invent route steps, bus "
        "numbers, or timings from memory; only report what a route/transit tool call actually returned.\n"
        "Reply ONLY with JSON:\n"
        '{"capabilities":[{"id":"...","reason":"...","confidence":0.0-1.0}], '
        '"ordering":["..."],"insufficient_capability":null|{"missing_capabilities":["..."],"reasons":["..."]}'
        ',"question":null,"rationale":"brief internal reasoning"}'
    )
    context_parts = []
    if state:
        messages = state.get("messages") or []
        history = []
        for message in messages[-6:-1]:
            role = "user" if getattr(message, "type", "") == "human" else "assistant"
            content = str(getattr(message, "content", ""))[:500]
            if content:
                history.append(f"{role}: {content}")
        if history:
            context_parts.append("Conversation so far:\n" + "\n".join(history))
        active = state.get("active_domain")
        if active:
            context_parts.append(f"Current thread domain: {active}")
        last = state.get("last_decision")
        if last and last.get("capabilities"):
            context_parts.append(
                f"Previous plan: {json.dumps(last, ensure_ascii=False)[:500]}"
            )
        feedback = state.get("verification_feedback")
        if feedback:
            context_parts.append(f"Verification feedback from the previous attempt: {feedback}")
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                ("\n".join(context_parts) + "\n\n" if context_parts else "")
                + f"User message: {user_text}\n\nRetrieval shortlist:\n{shortlist_text}"
            ),
        },
    ]


async def plan_with_llm(
    user_text: str,
    state: dict[str, Any] | AssistantState,
    retrieval: RetrievalResult | None,
) -> Optional[Decision]:
    """Production planner: LLM decision with validation; None means fall back to deterministic.

    Unverified — assumption: this path is exercised only with mocked models in
    this environment; with a real API key it runs on the deployed service.
    """
    from core.config import settings
    from core.llm import ThinkingLevel, get_agent_llm

    if not settings.has_llm_key:
        return None
    if retrieval is None or not retrieval.top:
        return None
    # Low-confidence retrieval (retrieval.recovered) means the top-k BM25 hits
    # aren't trustworthy — e.g. a message like "did u see the email from DBS
    # today?" shares no tokens with any manifest, so plain top-k can leave the
    # right capability out of the LLM's candidate set entirely. Widen to the
    # expanded shortlist in that case, matching _retrieval_ids' recovery logic,
    # instead of silently limiting the planner to a possibly-irrelevant top-5.
    candidate_hits = list(retrieval.top)
    if retrieval.recovered:
        seen_ids = {hit.id for hit in candidate_hits}
        candidate_hits.extend(hit for hit in retrieval.expanded if hit.id not in seen_ids)
    shortlist = [
        {
            "id": hit.id,
            "description": hit.manifest.description,
            "score": round(hit.score, 3),
        }
        for hit in candidate_hits
    ]
    llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.0)
    try:
        ai_message = await llm.ainvoke(llm_plan_prompt(user_text, shortlist, state))
    except Exception as exc:  # noqa: BLE001
        print(f"[PLANNER] LLM call failed, falling back to deterministic: {exc}")
        return None
    raw = str(getattr(ai_message, "content", "") or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[PLANNER] LLM JSON parse failed, falling back to deterministic: {exc}")
        return None
    return decision_from_dict(parsed, shortlist_ids={hit["id"] for hit in shortlist})


def decision_from_dict(
    parsed: dict[str, Any],
    shortlist_ids: set[str],
) -> Optional[Decision]:
    """Validate an LLM decision dict against the retrieval shortlist."""
    try:
        capabilities = []
        for item in parsed.get("capabilities") or []:
            cap_id = str(item.get("id", ""))
            if cap_id not in shortlist_ids and cap_id != "timezone":
                continue
            capabilities.append(
                CapabilitySelection(
                    id=cap_id,
                    reason=str(item.get("reason", "")),
                    confidence=float(item.get("confidence", 0.8)),
                )
            )
        ordering = [
            str(cap_id)
            for cap_id in parsed.get("ordering") or []
            if str(cap_id) in {c.id for c in capabilities}
        ]
        missing = [
            str(tag)
            for tag in (parsed.get("insufficient_capability") or {}).get("missing_capabilities", [])
        ]
        insufficient = None
        if missing:
            insufficient = InsufficientCapability(
                missing_capabilities=missing,
                reasons=(parsed.get("insufficient_capability") or {}).get("reasons", []),
                message=_insufficiency_message(missing),
            )
        question = parsed.get("question")
        question = str(question) if question else None
        rationale = str(parsed.get("rationale") or "") or None
        if not capabilities and not insufficient and not question:
            return None
        return Decision(
            capabilities=capabilities,
            ordering=ordering or [c.id for c in capabilities],
            insufficient=insufficient,
            question=question,
            confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.8)))),
            source="llm",
            retrieval_used=True,
            rationale=rationale,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[PLANNER] invalid LLM decision, falling back to deterministic: {exc}")
        return None


def decision_to_dict(decision: Decision) -> dict[str, Any]:
    return {
        "capabilities": [
            {"id": c.id, "reason": c.reason, "confidence": c.confidence}
            for c in decision.capabilities
        ],
        "ordering": decision.ordering,
        "insufficient": (
            {
                "missing_capabilities": decision.insufficient.missing_capabilities,
                "reasons": decision.insufficient.reasons,
            }
            if decision.insufficient
            else None
        ),
        "question": decision.question,
        "confidence": decision.confidence,
        "source": decision.source,
        "retrieval_used": decision.retrieval_used,
        "recipe": decision.recipe,
        "rationale": decision.rationale,
    }
