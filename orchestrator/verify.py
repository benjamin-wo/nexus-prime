"""Backend reply verification with a bounded re-plan loop.

Verification is internal: the user never sees the plan or the check. The LLM
verifier runs when API keys are configured; the deterministic verifier is the
measured offline fallback.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class VerifyResult:
    fulfilled: bool
    needs_replan: bool = False
    reason: Optional[str] = None
    missing: Optional[str] = None


def verify_deterministic(
    decision: Any,
    reply_text: str,
    user_text: str = "",
) -> VerifyResult:
    """Offline verification rules. Never triggers a loop on honest refusals."""
    if not reply_text or not reply_text.strip():
        return VerifyResult(
            fulfilled=False,
            needs_replan=True,
            reason="reply was empty",
            missing="the reply was empty",
        )
    if reply_text.strip().startswith("I couldn't work out what to do with that."):
        return VerifyResult(
            fulfilled=False,
            needs_replan=True,
            reason="planner fallback reply",
            missing="no capability could handle the request",
        )
    if decision.insufficient and not decision.capabilities:
        return VerifyResult(
            fulfilled=True,
            needs_replan=False,
            reason="honest refusal is the correct outcome",
        )
    return VerifyResult(fulfilled=True, needs_replan=False, reason="reply produced")


async def verify_with_llm(
    decision: Any,
    user_text: str,
    reply_text: str,
    tool_summary: str,
    state: dict[str, Any],
) -> Optional[VerifyResult]:
    """LLM verifier; returns None (deterministic fallback) when no real key."""
    from core.config import settings
    from core.llm import ThinkingLevel, get_agent_llm

    if not settings.deepseek_api_key or settings.deepseek_api_key == "test_deepseek_key":
        return None
    system = (
        "You verify whether the assistant's reply fulfils the user's request. "
        "Reply with ONLY JSON: "
        '{"fulfilled": bool, "missing": string|null, "replan": bool}. '
        "Replan only if the reply is empty, clearly wrong, or a needed capability was skipped."
    )
    plan = json.dumps(decision_to_dict(decision), ensure_ascii=False) if hasattr(decision, "recipe") else str(decision)
    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.0)
        ai_message = await llm.ainvoke(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"User request: {user_text[:1000]}\n"
                        f"Plan: {plan[:1500]}\n"
                        f"Tool output summary: {tool_summary[:1200]}\n"
                        f"Reply: {reply_text[:1500]}"
                    ),
                },
            ]
        )
        raw = str(getattr(ai_message, "content", "") or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        missing = str(parsed.get("missing") or "") or None
        return VerifyResult(
            fulfilled=bool(parsed.get("fulfilled", True)),
            needs_replan=bool(parsed.get("replan", False)),
            reason=missing or ("replan requested by verifier" if parsed.get("replan") else "fulfilled"),
            missing=missing,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[VERIFY] LLM verification failed, using deterministic rules: {exc}")
        return None


def decision_to_dict(decision: Any) -> dict[str, Any]:
    from orchestrator.planner import decision_to_dict as _to_dict

    return _to_dict(decision)
