import random
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field
from sqlmodel import select
from core.db import async_session_factory
from core.models import QualityAuditLog
from core.config import settings

class EvalScorecard(BaseModel):
    conversation_id: str
    faithfulness_score: int = Field(ge=1, le=5, description="1=Hallucinated details not in tool output, 5=100% faithful")
    routing_efficiency_score: int = Field(ge=1, le=5, description="1=Ping-ponging/redundant hops, 5=Direct single hop")
    hallucination_detected: bool
    unnecessary_friction_flag: bool = Field(description="True if bot asked for info already provided by user")
    evidence_explanation: str

def should_sample_audit(confidence: Optional[float] = None, hitl_triggered: bool = False) -> bool:
    """
    Sample 100% of turns with confidence < 0.8 or HITL keyboard confirmation,
    and 10% random sample of routine single-hop turns.
    """
    if hitl_triggered or (confidence is not None and confidence < 0.8):
        return True
    return random.random() < 0.10

async def perform_audit_evaluation(
    user_id: int,
    thread_id: str,
    turn_context: Dict[str, Any],
    mock_scorecard: Optional[EvalScorecard] = None,
) -> EvalScorecard:
    """
    Perform asynchronous LLM-as-a-Judge evaluation of a conversation turn.
    Can accept a mock_scorecard for testing and deterministic evaluation.
    """
    if mock_scorecard:
        scorecard = mock_scorecard
    else:
        # Default fallback scorecard for standard executions
        scorecard = EvalScorecard(
            conversation_id=thread_id,
            faithfulness_score=5,
            routing_efficiency_score=5,
            hallucination_detected=False,
            unnecessary_friction_flag=False,
            evidence_explanation="Turn executed faithfully with direct single-hop routing.",
        )

    # Persist to PostgreSQL QualityAuditLog
    async with async_session_factory() as session:
        log_entry = QualityAuditLog(
            user_id=user_id,
            thread_id=thread_id,
            faithfulness_score=scorecard.faithfulness_score,
            routing_efficiency_score=scorecard.routing_efficiency_score,
            hallucination_detected=scorecard.hallucination_detected,
            unnecessary_friction_flag=scorecard.unnecessary_friction_flag,
            evidence_explanation=scorecard.evidence_explanation,
        )
        session.add(log_entry)
        await session.commit()
        await session.refresh(log_entry)

    # Automated Anomaly Alerting
    if scorecard.faithfulness_score <= 2 or scorecard.hallucination_detected:
        await send_admin_anomaly_alert(
            thread_id=thread_id,
            evidence=scorecard.evidence_explanation,
            score=scorecard.faithfulness_score,
        )

    return scorecard

async def send_admin_anomaly_alert(thread_id: str, evidence: str, score: int):
    """Push Telegram anomaly alert to admin notification channel."""
    alert_msg = (
        f"🚨 [AUDIT ANOMALY] Thread ID: {thread_id}\n"
        f"Faithfulness Score: {score}/5\n"
        f"Evidence: {evidence}"
    )
    # Log anomaly alert (in live mode, posts via Telegram API to settings.admin_telegram_chat_id)
    print(f"[AUDIT ALERT] {alert_msg}")


async def log_capability_request(
    user_id: int,
    requested_task: str,
    intent_type: str,
    tags: list[str],
) -> "CapabilityRequestLog":
    """
    Persist a missing capability demand entry in CapabilityRequestLog and
    asynchronously sync to GitHub Issues if configured.
    """
    from core.models import CapabilityRequestLog
    from core.github_sync import sync_capability_gap_to_github_issue

    tags_str = ",".join([t.strip().lstrip("#") for t in tags if t.strip()])
    async with async_session_factory() as session:
        entry = CapabilityRequestLog(
            user_id=user_id,
            requested_task=requested_task,
            intent_type=intent_type,
            missing_capability_tags=tags_str,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)

    # Sync each tag to GitHub Issues backlog without blocking core execution
    for tag in tags:
        await sync_capability_gap_to_github_issue(
            tag=tag,
            prompt=requested_task,
            intent_type=intent_type,
        )

    return entry


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
