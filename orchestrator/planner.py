"""Decision object and planner for retrieve -> plan -> select a set.

The planner consumes the C2 retrieval shortlist plus thread state and emits a
Decision: a *set* of capabilities with ordering, explicit insufficiency, and
confidence. Managers are derived tags and never appear as routing hops.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

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

AMBIGUITY_PATTERNS = [
    r"^how am i doing",
    r"^how are we doing",
    r"^what('s| is) my status",
    r"^how is everything",
]


def _has(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def missing_policy(text: str) -> list[str]:
    """Missing-capability detection. Deliberately narrower than the legacy guardrail."""
    missing: list[str] = []
    if _has(text, ["calendar", "appointment", "meeting", "invite"]):
        missing.append("calendar")
    if _has(text, ["book a flight", "flight to ", "flight from ", "book a hotel"]):
        missing.append("flight_booking")
    if _has(text, ["transfer", "send money", "wire "]):
        missing.append("bank_transfer")
    if _has(text, ["turn on", "turn off", "lights", "thermostat", "smart home"]):
        missing.append("smart_home")
    if _has(text, ["book a table", "reserve a table", "restaurant booking"]):
        missing.append("restaurant_booking")
    if _has(text, ["budget"]):
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

    add("email", ["email", "gmail", "inbox", "mail"], "email-related intent")
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
        "route", "eta", "drive", "driving", "transit", "bus", "mrt", "train",
        "traffic", "direction", "how do i get", "get to", "fastest way",
        "way home", "way to", "next bus",
    ], "route/transit intent")

    groceries_as_reminder_content = bool(
        re.search(r"remind .*(buy|get) groceries", text)
        or re.search(r"remind .*(buy|get) ingredients", text)
    )
    if not groceries_as_reminder_content:
        add("recipes", ["recipe", "grocery", "groceries", "ingredient", "cook", "pasta", "fridge"],
            "recipe/grocery intent")

    add("reminders", ["remind", "reminder", "cron"], "reminder/scheduling intent")

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
            )
        active = (state or {}).get("active_domain")
        if active and active in {"email", "expenses", "routes", "recipes", "reminders", "general"}:
            return Decision(
                capabilities=[CapabilitySelection(id=active, reason="referent continuation of active domain", confidence=0.8)],
                ordering=[active],
                confidence=0.8,
                source="referent-reuse",
                retrieval_used=False,
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
        )

    missing = missing_policy(text)
    candidates = _candidate_selections(text, missing)

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
        )

    if not candidates:
        candidates = [
            CapabilitySelection(id="general", reason="no specific capability matched", confidence=0.6)
        ]

    if retrieval is not None:
        available = _retrieval_ids(retrieval)
        candidates = [c for c in candidates if c.id in available or c.id == "timezone"]
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


def llm_plan_prompt(user_text: str, shortlist: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Production planner prompt (Anthropic parallel-tool-use style decision).

    Unverified — assumption: this prompt is not exercised in this environment
    (no API keys); the deterministic planner is the measured artifact.
    """
    shortlist_text = "\n".join(
        f"- {item['id']}: {item['description']} (score {item['score']:.3f})"
        for item in shortlist
    )
    system = (
        "You are the Nexus Prime planner. Decide which capabilities to use and in what order. "
        "Reply with ONLY JSON: "
        '{"capabilities":[{"id":"...","reason":"...","confidence":0.0-1.0}], '
        '"ordering":["..."],"insufficient_capability":{"missing_capabilities":["..."],"reasons":["..."]}'
        ',"question":null|"..."}'
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"User message: {user_text}\n\nRetrieval shortlist:\n{shortlist_text}",
        },
    ]


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
    }
