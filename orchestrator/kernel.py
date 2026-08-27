"""Safety kernel: the deterministic checks that must never be delegated to the LLM."""

from __future__ import annotations

import re


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
