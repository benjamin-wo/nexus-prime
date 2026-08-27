"""Safety kernel: the deterministic checks that must never be delegated to the LLM.

Money-in parsing, transactional guardrails, and closing intents stay as code —
everything else is the agent's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


TERMINATION_INTENTS = {
    "stop", "stop it", "cancel", "cancel that", "never mind", "nevermind",
    "forget it", "forget about it", "that's enough", "that's all", "thats all",
    "i'm done", "im done", "i'm good", "im good", "all good", "ok", "okay",
    "ok stop", "okay stop", "that's it", "thats it", "drop it", "quit",
    "enough", "no more", "stop talking", "shut up", "leave it",
}


def is_termination_intent(text: str) -> bool:
    """True for explicit stop/closing commands so the kernel terminates the
    thread instead of routing it anywhere."""
    lowered = (text or "").strip().lower()
    if not lowered or len(lowered) > 60:
        return False
    if lowered in TERMINATION_INTENTS:
        return True
    return re.fullmatch(r"stop(?:!|\.)*", lowered) is not None


@dataclass(frozen=True)
class Refusal:
    tags: List[str]
    reasons: List[str] = field(default_factory=lambda: ["no registered capability can fulfil this request"])
    message: str = ""


def missing_policy(text: str) -> List[str]:
    """Transactional categories that must be refused, never improvised by the
    agent: money movement, bookings, and account-access requests."""
    lowered = (text or "").lower()
    missing: List[str] = []

    def _has(words: List[str]) -> bool:
        return any(word in lowered for word in words)

    if _has(["calendar", "appointment", "meeting", "invite"]):
        missing.append("calendar")
    if _has(["book a flight", "flight to ", "flight from ", "book a hotel"]):
        missing.append("flight_booking")
    if _has(["transfer", "send money", "wire "]):
        missing.append("bank_transfer")
    if _has(["turn on", "turn off", "lights", "thermostat", "smart home"]):
        missing.append("smart_home")
    if _has(["book a table", "reserve a table", "restaurant booking"]):
        missing.append("restaurant_booking")
    if re.search(r"email .* to me|email me|send .* by email", lowered):
        missing.append("email_send")
    return missing


def insufficiency_refusal(tags: List[str]) -> Refusal:
    label = ", ".join(f"#{tag}" for tag in tags)
    needs_human = any(tag in tags for tag in ("bank_transfer", "payments", "send_money"))
    if needs_human:
        message = (
            f"I can't do this without a human — {label} needs your explicit approval "
            "and a connected account. Nothing was sent or changed."
        )
    else:
        message = (
            f"I can't do that — no integration exists for {label} yet. "
            "Nothing was changed. Want me to log it as a feature request?"
        )
    return Refusal(tags=tags, message=message)
