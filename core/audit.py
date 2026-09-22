from typing import Optional
from sqlmodel import select
from core.db import async_session_factory
# Intent types that represent a genuine capability gap. Other calls
# (informational_fallback, in_scope) are counters for the leaderboard only.
GAP_INTENT_TYPES = {"unsupported_transaction", "insufficient_capability"}


async def log_capability_request(
    user_id: int,
    requested_task: str,
    intent_type: str,
    tags: list[str],
    expectation: Optional[str] = None,
    block_reason: Optional[str] = None,
    agent_reply: Optional[str] = None,
    channel: Optional[str] = None,
) -> "CapabilityRequestLog":
    """
    Persist a missing capability demand entry in CapabilityRequestLog.
    """
    from core.models import CapabilityRequestLog

    tags_str = ",".join([t.strip().lstrip("#") for t in tags if t.strip()])
    async with async_session_factory() as session:
        entry = CapabilityRequestLog(
            user_id=user_id,
            requested_task=requested_task,
            intent_type=intent_type,
            missing_capability_tags=tags_str,
            expectation=expectation,
            block_reason=block_reason,
            agent_reply=agent_reply,
            channel=channel,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)

    return entry


# ── Stubs for stripped audit/telemetry infra ──────────────────────────
# These were removed during the expense/finance-only cleanup but are
# still imported by orchestrator/agent_loop.py. Safe no-ops.


def should_audit_conversation(_human_count: int) -> bool:
    """Return False — conversation audit infra was stripped."""
    return False


async def perform_conversation_audit(
    user_id: int,
    thread_id: str,
    messages: list,
) -> None:
    """No-op — conversation audit (LLM-as-Judge) was stripped."""


async def record_operation_event(
    subsystem: str,
    error_context: str,
    detection_source: str,
    user_id: int | None = None,
    thread_id: str | None = None,
    error_traceback: str | None = None,
    fingerprint: str | None = None,
    severity: str = "P3",
) -> None:
    """No-op — incident/telemetry recording was stripped."""


async def get_capability_leaderboard(limit: int = 10) -> list[dict]:
    """
    Aggregate missing capability requests by tag and return top requested capabilities.
    """
    from core.models import CapabilityRequestLog

    async with async_session_factory() as session:
        result = await session.execute(select(CapabilityRequestLog))
        logs = result.scalars().all()

    counts: dict[str, int] = {}
    sample_prompts: dict[str, str] = {}

    for log_entry in logs:
        tags = [t.strip().lstrip("#") for t in log_entry.missing_capability_tags.split(",") if t.strip()]
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
            if tag not in sample_prompts:
                sample_prompts[tag] = log_entry.requested_task

    sorted_tags = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [
        {
            "tag": tag,
            "count": count,
            "sample_prompt": sample_prompts[tag],
        }
        for tag, count in sorted_tags
    ]
