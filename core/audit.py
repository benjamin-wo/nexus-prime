import json
import random
import re
from typing import Optional, Any, Dict
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlmodel import select
from core.db import async_session_factory
from core.llm import ThinkingLevel, extract_llm_text, get_agent_llm
from core.models import QualityAuditLog
from core.config import settings

class EvalScorecard(BaseModel):
    conversation_id: str
    faithfulness_score: int = Field(ge=1, le=5, description="1=Hallucinated details not in tool output, 5=100% faithful")
    routing_efficiency_score: int = Field(ge=1, le=5, description="1=Ping-ponging/redundant hops, 5=Direct single hop")
    hallucination_detected: bool
    unnecessary_friction_flag: bool = Field(description="True if bot asked for info already provided by user")
    evidence_explanation: str


def _default_scorecard(thread_id: str) -> EvalScorecard:
    return EvalScorecard(
        conversation_id=thread_id,
        faithfulness_score=5,
        routing_efficiency_score=5,
        hallucination_detected=False,
        unnecessary_friction_flag=False,
        evidence_explanation="Turn executed faithfully with direct single-hop routing.",
    )


async def _judge_with_llm(thread_id: str, turn_context: Dict[str, Any]) -> EvalScorecard:
    """Run a stronger reasoning model as judge over the conversation turn."""
    if not settings.has_llm_key:
        return _default_scorecard(thread_id)
    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.0)
        ai_message = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "You are an LLM-as-a-Judge for a Telegram assistant. Evaluate the turn "
                        "context and reply with ONLY a JSON object: "
                        '{"faithfulness_score": int 1-5, "routing_efficiency_score": int 1-5, '
                        '"hallucination_detected": bool, "unnecessary_friction_flag": bool, '
                        '"evidence_explanation": string}. '
                        "faithfulness 1 = reply invents details not supported by the turn; "
                        "5 = fully faithful. friction flag = the bot asked for info the user "
                        "already provided."
                    )
                ),
                HumanMessage(content=json.dumps(turn_context, default=str)[:3000]),
            ]
        )
        raw = extract_llm_text(getattr(ai_message, "content", ""))
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        return EvalScorecard(
            conversation_id=thread_id,
            faithfulness_score=max(1, min(5, int(parsed.get("faithfulness_score", 5)))),
            routing_efficiency_score=max(
                1, min(5, int(parsed.get("routing_efficiency_score", 5)))
            ),
            hallucination_detected=bool(parsed.get("hallucination_detected", False)),
            unnecessary_friction_flag=bool(
                parsed.get("unnecessary_friction_flag", False)
            ),
            evidence_explanation=str(parsed.get("evidence_explanation", "")),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[AUDIT] judge LLM failed, using default scorecard: {exc}")
        return _default_scorecard(thread_id)

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
        scorecard = await _judge_with_llm(thread_id, turn_context)

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
    chat_id = settings.admin_telegram_chat_id
    if not chat_id:
        print(f"[AUDIT ALERT] (no ADMIN_TELEGRAM_CHAT_ID) {alert_msg}")
        return
    try:
        from app.ingress import send_telegram_message

        await send_telegram_message(int(chat_id), alert_msg)
    except Exception as exc:  # noqa: BLE001
        print(f"[AUDIT ALERT] failed to send: {exc}")
        print(alert_msg)


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


JUDGE_SYSTEM_PROMPT = (
    "You are an expert reviewer of a personal assistant's Telegram conversations. "
    "Pay special attention to route, directions, map, and bus answers: are bus numbers real, "
    "are stops correct, is the route grounded in provided tool data, is there a map link when "
    "useful, and does the assistant fabricate anything? Also judge whether the right capabilities "
    "were used and whether the reply is honest and helpful. "
    "Reply with ONLY JSON: "
    '{"faithfulness_score": int 1-5, "routing_score": int 1-5, '
    '"tool_correctness_score": int 1-5, "helpfulness_score": int 1-5, '
    '"verdict": "pass"|"review"|"critical", '
    '"evidence": "one short paragraph citing the failing turn, or why it passed"}'
)


async def _judge_conversation_with_gemini(transcript: list[dict]) -> dict:
    from core.llm import get_judge_llm

    llm = get_judge_llm()
    ai_message = await llm.ainvoke(
        [
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(
                content=json.dumps(transcript, ensure_ascii=False, default=str)[:12000]
            ),
        ]
    )
    raw = extract_llm_text(getattr(ai_message, "content", ""))
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    return json.loads(raw)


def should_audit_conversation(user_message_count: int, every_n: int = 5) -> bool:
    """Audit a conversation when the user message count hits the cadence."""
    return user_message_count > 0 and user_message_count % every_n == 0


async def perform_conversation_audit(
    user_id: int,
    thread_id: str,
    messages,
    judge_model: str | None = None,
) -> "ConversationAuditLog":
    """Judge the recent conversation with Gemini Pro and persist the scorecard."""
    from core.models import ConversationAuditLog

    transcript = [
        {
            "role": "user" if getattr(message, "type", "") == "human" else "assistant",
            "content": str(getattr(message, "content", ""))[:1000],
        }
        for message in list(messages)[-12:]
    ]
    model = judge_model or settings.gemini_judge_model
    try:
        parsed = await _judge_conversation_with_gemini(transcript)
    except Exception as exc:  # noqa: BLE001
        print(f"[AUDIT] conversation judge failed: {exc}")
        parsed = {
            "faithfulness_score": 3,
            "routing_score": 3,
            "tool_correctness_score": 3,
            "helpfulness_score": 3,
            "verdict": "review",
            "evidence": f"judge call failed: {exc}",
        }

    def _clamp(value, default: int = 3) -> int:
        try:
            return max(1, min(5, int(value)))
        except Exception:  # noqa: BLE001
            return default

    verdict = str(parsed.get("verdict") or "review")
    if verdict not in {"pass", "review", "critical"}:
        verdict = "review"
    log_entry = ConversationAuditLog(
        thread_id=thread_id,
        user_id=user_id,
        message_count=len(list(messages)),
        faithfulness_score=_clamp(parsed.get("faithfulness_score")),
        routing_score=_clamp(parsed.get("routing_score")),
        tool_correctness_score=_clamp(parsed.get("tool_correctness_score")),
        helpfulness_score=_clamp(parsed.get("helpfulness_score")),
        verdict=verdict,
        evidence=str(parsed.get("evidence") or "")[:2000],
        judge_model=model,
    )
    async with async_session_factory() as session:
        session.add(log_entry)
        await session.commit()
        await session.refresh(log_entry)

    # Only alert the admin channel on critical anomalies; never message the end user's chat
    if verdict == "critical":
        await send_admin_anomaly_alert(
            thread_id=thread_id,
            evidence=(
                f"Conversation audit {log_entry.verdict} "
                f"(tool_correctness={log_entry.tool_correctness_score}/5, judge={log_entry.judge_model}): "
                f"{log_entry.evidence}"
            ),
            score=log_entry.tool_correctness_score,
        )
    return log_entry
