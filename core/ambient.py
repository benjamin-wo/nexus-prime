"""Ambient trigger policy: triggers invoke the agent; quiet hours gate delivery."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

URGENT_AMOUNT_THRESHOLD = 100.0
QUIET_HOUR_END = 9  # nothing non-urgent before 09:00 local
URGENT_KEYWORDS = (
    "medical", "security", "fraud", "urgent", "critical", "overdraft",
    "emergency", "breach",
)


def classify_urgency(trigger: dict) -> str:
    """'urgent' or 'routine'."""
    if trigger.get("kind") == "expense_mismatch":
        diff = abs(float(trigger.get("amount_diff", 0.0)))
        return "urgent" if diff >= URGENT_AMOUNT_THRESHOLD else "routine"
    if trigger.get("urgency") == "urgent":
        return "urgent"
    text = str(trigger.get("message") or trigger.get("instruction_prompt") or "").lower()
    if any(keyword in text for keyword in URGENT_KEYWORDS):
        return "urgent"
    return "routine"


def should_deliver(
    trigger: dict | None,
    now_utc: datetime | None = None,
    user_timezone: str = "Asia/Singapore",
) -> tuple[bool, str]:
    """Return (deliver, reason). Without a trigger record, nothing is delivered."""
    if not trigger or not trigger.get("kind") or not trigger.get("trigger_id"):
        return False, "no trigger record — proactivity never guesses"
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    local = now_utc.astimezone(ZoneInfo(user_timezone))
    urgency = classify_urgency(trigger)
    if local.hour < QUIET_HOUR_END and urgency != "urgent":
        return False, f"quiet hours before 09:00 {user_timezone} and urgency={urgency}"
    return True, f"deliverable (urgency={urgency})"
