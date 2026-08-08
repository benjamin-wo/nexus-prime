"""First-class insufficiency: distinct refusal kinds, gap records, no fake confirmations."""

from __future__ import annotations

from typing import Optional

from orchestrator.planner import Decision, InsufficientCapability


def classify_insufficiency(missing_capabilities: list[str], user_text: str = "") -> str:
    """Return 'needs_human' or 'no_integration'."""
    if any(tag in missing_capabilities for tag in ("bank_transfer", "payments", "send_money")):
        return "needs_human"
    return "no_integration"


def insufficiency_message(kind: str, missing_capabilities: list[str]) -> str:
    tags = ", ".join(f"#{tag}" for tag in missing_capabilities)
    if kind == "needs_human":
        return (
            f"I can't do this without a human — {tags} needs your explicit approval "
            "and a connected account. Nothing was sent or changed."
        )
    return (
        f"I can't do that — no integration exists for {tags} yet. "
        "Nothing was changed. Want me to log it as a feature request?"
    )


def refusal_decision(missing_capabilities: list[str], user_text: str = "") -> Decision:
    kind = classify_insufficiency(missing_capabilities, user_text)
    return Decision(
        insufficient=InsufficientCapability(
            missing_capabilities=missing_capabilities,
            reasons=["capability not registered"],
            message=insufficiency_message(kind, missing_capabilities),
        ),
        confidence=0.9,
        source="deterministic-insufficiency",
        retrieval_used=True,
    )


async def record_gap(user_id: int, requested_task: str, decision: Decision) -> Optional[object]:
    """Persist a gap record for any decision carrying insufficiency."""
    if not decision.insufficient or not decision.insufficient.missing_capabilities:
        return None
    from core.audit import log_capability_request

    return await log_capability_request(
        user_id=user_id,
        requested_task=requested_task,
        intent_type="insufficient_capability",
        tags=decision.insufficient.missing_capabilities,
    )
