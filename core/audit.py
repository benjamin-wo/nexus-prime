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
from core.github_sync import (
    sync_capability_gap_to_github_issue,
    sync_production_bug_to_github_issue,
)

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
    if not settings.audit_telegram_alerts:
        print("[AUDIT ALERT] Telegram delivery disabled; anomaly retained in DB/GitHub.")
        return
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


# Intent types that represent a genuine capability gap and therefore deserve a
# GitHub wishlist/backlog ticket. Other calls (informational_fallback, in_scope)
# are counters for the leaderboard only — syncing them would spam the repo.
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
    Persist a missing capability demand entry in CapabilityRequestLog and
    asynchronously sync genuine gaps (guardrail refusals / insufficiency) to
    GitHub Issues with full context: request, expectation, missing areas,
    block reason, and the reply shown to the user.
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
            expectation=expectation,
            block_reason=block_reason,
            agent_reply=agent_reply,
            channel=channel,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)

    # Sync each tag to GitHub Issues backlog without blocking core execution.
    # Only genuine gaps create tickets; leaderboard-only calls stay local.
    if intent_type in GAP_INTENT_TYPES:
        for tag in tags:
            await sync_capability_gap_to_github_issue(
                tag=tag,
                prompt=requested_task,
                intent_type=intent_type,
                expectation=expectation,
                block_reason=block_reason,
                agent_reply=agent_reply,
                channel=channel,
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
    "You are an expert reviewer of ONE completed turn from a personal assistant's Telegram conversation. "
    "Judge only the newest user request and the assistant reply in the supplied transcript; "
    "do not attribute claims from older turns to the newest reply. "
    "The transcript may include 'role': 'tool' entries showing actual tool invocations "
    "and their raw outputs. Cross-check every claim in the assistant's replies against "
    "the real tool data: numbers, IDs, names, and times must come from tool outputs, "
    "never be invented. Pay special attention to route, directions, map, and bus answers: "
    "are bus numbers real, are stops correct, is the route grounded in provided tool data, "
    "is there a map link when useful, and does the assistant fabricate anything? Also judge "
    "whether the right capabilities were used (was a relevant tool skipped or mis-called?) "
    "and whether the reply is honest and helpful. Deterministic responses such as OAuth links, "
    "capability refusals, confirmations, and routing messages do not require a tool call; "
    "do not label those as hallucinations merely because no tool message is present. "
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


def should_audit_conversation(user_message_count: int, every_n: int = 4) -> bool:
    """Audit a conversation when the user message count hits the cadence."""
    return user_message_count > 0 and user_message_count % every_n == 0


def _build_audit_transcript(messages, tail: int = 12, content_cap: int = 1000) -> list[dict]:
    """
    Build a redacted audit transcript including tool invocations.
    ToolMessages carry the raw tool name + output so the judge/triage can
    verify the assistant's reply against actual tool data (deeper coverage).
    """
    transcript = []
    for message in list(messages)[-tail:]:
        msg_type = getattr(message, "type", "")
        if msg_type == "tool":
            transcript.append(
                {
                    "role": "tool",
                    "tool_name": str(getattr(message, "name", "") or "unknown_tool"),
                    "content": redact_sensitive_info(str(getattr(message, "content", ""))[:content_cap]),
                }
            )
        else:
            transcript.append(
                {
                    "role": "user" if msg_type == "human" else "assistant",
                    "content": redact_sensitive_info(str(getattr(message, "content", ""))[:content_cap]),
                }
            )
    return transcript


async def perform_conversation_audit(
    user_id: int,
    thread_id: str,
    messages,
    judge_model: str | None = None,
) -> "ConversationAuditLog":
    """Judge the recent conversation with Gemini Pro and persist the scorecard."""
    from core.models import ConversationAuditLog

    transcript = _build_audit_transcript(messages, tail=12, content_cap=1000)
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

    # If critical or severe tool failure, asynchronously triage bug & sync to GitHub Issues
    if verdict == "critical" or log_entry.tool_correctness_score <= 2:
        try:
            await report_production_bug(
                user_id=user_id,
                thread_id=thread_id,
                messages=messages,
                detection_source="conversation_audit",
                error_context=f"Conversation Audit Failure ({log_entry.verdict}): {log_entry.evidence}",
            )
        except Exception as bug_err:  # noqa: BLE001
            print(f"[AUDIT] Failed to report production bug from conversation audit: {bug_err}")

    return log_entry


def redact_sensitive_info(text: str) -> str:
    """Scrub tokens, API keys, authorization headers, Fernet keys, and secrets from logs and payloads."""
    if not text:
        return ""
    # Redact Telegram bot tokens (e.g. 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)
    cleaned = re.sub(r"\b\d{8,12}:[A-Za-z0-9_-]{30,50}\b", "[REDACTED_TELEGRAM_TOKEN]", text)
    # Redact Bearer tokens
    cleaned = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{15,}", r"\1[REDACTED_BEARER_TOKEN]", cleaned, flags=re.IGNORECASE)
    # Redact OpenAI / DeepSeek / Google keys
    cleaned = re.sub(r"\b(?:sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z-_]{35})\b", "[REDACTED_API_KEY]", cleaned)
    # Redact Fernet symmetric keys (base64 44 chars ending in =)
    cleaned = re.sub(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{43}=(?![A-Za-z0-9+/_-])", "[REDACTED_ENCRYPTION_KEY]", cleaned)
    # Redact standard password query parameters or assignments
    cleaned = re.sub(r"(password|secret|token|api_key)\s*[:=]\s*['\"][^'\"]+['\"]", r"\1='[REDACTED]'", cleaned, flags=re.IGNORECASE)
    return cleaned


BUG_TRIAGE_SYSTEM_PROMPT = (
    "You are an expert Site Reliability Engineer (SRE) and software architect analyzing a production bug "
    "or audit failure in an AI personal assistant backend (Nexus Prime). "
    "The payload may include 'role': 'tool' entries showing the actual tool invoked and its raw output — "
    "use these to pinpoint whether the bug is in the tool itself (bad data, parse error, timeout) or in "
    "how the assistant interpreted the tool result. "
    "IMPORTANT: several subsystems (whiteboard board create/list/summary/pin/add-card, reminders, "
    "expenses, recipes, routes) execute through deterministic Python dispatch, not LLM tool-calling -- "
    "a correct, real reply from these (e.g. 'Pinned to *Bali Bachelor Party* (#21) as card #79.') will "
    "NEVER show a 'role': 'tool' entry in the transcript, by design. Do NOT flag these as a hallucination "
    "or 'bypassed tool execution' merely because no tool message is present; only flag them when the "
    "reply's specific claims (place names, numbers, dates) contradict something stated earlier in the "
    "same transcript, or contain details that could not plausibly have come from the user's own words. "
    "Given the conversation transcript, tool outputs, error context, or traceback, perform root-cause "
    "analysis and return ONLY a JSON object with: "
    "{\n"
    '  "title": "Short descriptive bug title (max 80 chars)",\n'
    '  "subsystem": "One of: routes, expenses, email, whiteboard, reminders, ingress, general",\n'
    '  "severity": "One of: P0 (system crash), P1 (major capability broken/hallucination), P2 (minor tool/format issue), P3 (cosmetic)",\n'
    '  "root_cause": "Detailed explanation of why the bug or hallucination happened, citing the specific tool or code path",\n'
    '  "reproduction_context": "Minimal user prompt or state that triggered this issue",\n'
    '  "suggested_fix": "Concrete code change, regex fix, prompt correction, or tool update to prevent recurrence",\n'
    '  "fingerprint": "Deterministic alphanumeric snake_case identifier (e.g. routes_lta_4digit_code_parse_error) for issue deduplication"\n'
    "}"
)


async def _triage_bug_with_gemini(triage_input: Dict[str, Any]) -> Dict[str, Any]:
    from core.llm import get_judge_llm

    llm = get_judge_llm()
    ai_message = await llm.ainvoke(
        [
            SystemMessage(content=BUG_TRIAGE_SYSTEM_PROMPT),
            HumanMessage(
                content=json.dumps(triage_input, ensure_ascii=False, default=str)[:12000]
            ),
        ]
    )
    raw = extract_llm_text(getattr(ai_message, "content", ""))
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    return json.loads(raw)


async def record_operation_event(
    subsystem: str,
    error_context: str,
    detection_source: str = "runtime_exception",
    user_id: Optional[int] = None,
    thread_id: Optional[str] = None,
    error_traceback: Optional[str] = None,
    fingerprint: Optional[str] = None,
    severity: str = "P2",
    title: Optional[str] = None,
) -> Optional["ProductionBugLog"]:
    """
    Record an operational event (runtime error, health-probe failure, delivery
    failure) through the production-bug pipeline without an LLM triage call.

    Falls back to a deterministic fingerprint when none is supplied so identical
    failures keep deduplicating into one open issue + recurrence comments.
    """
    from core.models import ProductionBugLog
    from datetime import datetime

    text = redact_sensitive_info(str(error_context or ""))
    trace = redact_sensitive_info(str(error_traceback or ""))
    if not fingerprint:
        handle = (title or text or "operation")[:120]
        seed = f"{detection_source}:{subsystem}:{handle}"
        fingerprint = f"op_{subsystem}_{abs(hash(seed)) % 100000}".lower().replace(" ", "_")

    occurrence_count = 1
    async with async_session_factory() as session:
        result = await session.execute(
            select(ProductionBugLog).where(
                ProductionBugLog.fingerprint == fingerprint,
                ProductionBugLog.status == "open",
            )
        )
        existing = result.scalars().first()
        if existing:
            existing.occurrence_count += 1
            existing.updated_at = datetime.utcnow()
            if not existing.error_traceback and error_traceback:
                existing.error_traceback = error_traceback
            occurrence_count = existing.occurrence_count
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            log_record = existing
        else:
            log_record = ProductionBugLog(
                fingerprint=fingerprint,
                title=(title or (f"{subsystem.replace('_', ' ').title()} operation failure")[:120]),
                severity=severity if severity in {"P0", "P1", "P2", "P3"} else "P2",
                subsystem=subsystem.lower(),
                detection_source=detection_source,
                user_id=user_id,
                thread_id=thread_id,
                root_cause=text,
                reproduction_context=text[:500],
                error_traceback=trace or None,
                occurrence_count=1,
                status="open",
            )
            session.add(log_record)
            await session.commit()
            await session.refresh(log_record)

    # Sync straight away (dedups into existing issue / creates new one).
    gh_result = await sync_production_bug_to_github_issue(
        fingerprint=fingerprint,
        title=log_record.title,
        severity=log_record.severity,
        subsystem=log_record.subsystem,
        detection_source=detection_source,
        root_cause=text,
        reproduction_context=text[:500],
        error_traceback=trace or None,
        occurrence_count=occurrence_count,
    )
    if gh_result and isinstance(gh_result, dict):
        async with async_session_factory() as session:
            db_entry = await session.get(ProductionBugLog, log_record.id)
            if db_entry:
                db_entry.github_issue_url = gh_result.get("url")
                db_entry.github_issue_number = gh_result.get("number")
                session.add(db_entry)
                await session.commit()
    return log_record


async def report_production_bug(
    user_id: Optional[int] = None,
    thread_id: Optional[str] = None,
    error_context: Optional[str] = None,
    messages: Optional[Any] = None,
    error_traceback: Optional[str] = None,
    detection_source: str = "conversation_audit",
    mock_triage: Optional[Dict[str, Any]] = None,
) -> "ProductionBugLog":
    """
    Triage a production bug or audit anomaly with Gemini 3.1 Pro in the background,
    persist to ProductionBugLog, and sync/deduplicate to GitHub Issues.
    This runs completely in the background without affecting end-user UX.
    """
    from datetime import datetime
    from core.models import ProductionBugLog

    # 1. Build context payload (includes tool invocations + outputs for deeper coverage)
    transcript = _build_audit_transcript(messages, tail=8, content_cap=800) if messages else []

    triage_payload = {
        "detection_source": detection_source,
        "error_context": redact_sensitive_info(str(error_context or "")[:2000]),
        "transcript": transcript,
        "error_traceback": redact_sensitive_info(str(error_traceback or "")[:3000]),
    }

    # 2. Gemini 3.1 Pro SRE Triage
    if mock_triage:
        triage_result = mock_triage
    else:
        try:
            triage_result = await _triage_bug_with_gemini(triage_payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[AUDIT BUG TRIAGE] Gemini triage failed, falling back to heuristic: {exc}")
            clean_hash = abs(hash(str(error_context or error_traceback))) % 100000
            triage_result = {
                "title": f"Production Anomaly in {detection_source}",
                "subsystem": "general",
                "severity": "P1" if detection_source == "runtime_exception" else "P2",
                "root_cause": f"Automated audit detected an anomaly: {error_context or exc}",
                "reproduction_context": str(error_context or transcript or "N/A")[:300],
                "suggested_fix": "Investigate logs and add missing error handling or validation.",
                "fingerprint": f"anomaly_{detection_source}_{clean_hash}",
            }

    fingerprint = (
        str(triage_result.get("fingerprint") or f"bug_{abs(hash(str(error_context))) % 100000}")
        .lower()
        .replace(" ", "_")
        .strip()
    )
    title = str(triage_result.get("title") or "Unspecified Production Bug")[:120]
    severity = str(triage_result.get("severity") or "P2").upper()
    if severity not in {"P0", "P1", "P2", "P3"}:
        severity = "P2"
    subsystem = str(triage_result.get("subsystem") or "general").lower()
    root_cause = redact_sensitive_info(str(triage_result.get("root_cause") or ""))
    reproduction_context = redact_sensitive_info(str(triage_result.get("reproduction_context") or ""))
    suggested_fix = str(triage_result.get("suggested_fix") or "")
    clean_traceback = redact_sensitive_info(str(error_traceback or ""))

    # 3. Check for existing open bug in DB with same fingerprint
    occurrence_count = 1

    async with async_session_factory() as session:
        result = await session.execute(
            select(ProductionBugLog).where(
                ProductionBugLog.fingerprint == fingerprint,
                ProductionBugLog.status == "open",
            )
        )
        existing_log = result.scalars().first()
        if existing_log:
            existing_log.occurrence_count += 1
            existing_log.updated_at = datetime.utcnow()
            if root_cause and not existing_log.root_cause:
                existing_log.root_cause = root_cause
            occurrence_count = existing_log.occurrence_count
            session.add(existing_log)
            await session.commit()
            await session.refresh(existing_log)
            log_record = existing_log
        else:
            log_record = ProductionBugLog(
                fingerprint=fingerprint,
                title=title,
                severity=severity,
                subsystem=subsystem,
                detection_source=detection_source,
                user_id=user_id,
                thread_id=thread_id,
                root_cause=root_cause,
                reproduction_context=reproduction_context,
                suggested_fix=suggested_fix,
                error_traceback=clean_traceback,
                occurrence_count=1,
                status="open",
            )
            session.add(log_record)
            await session.commit()
            await session.refresh(log_record)

    # 4. Sync to GitHub Issues
    gh_result = await sync_production_bug_to_github_issue(
        fingerprint=fingerprint,
        title=title,
        severity=severity,
        subsystem=subsystem,
        detection_source=detection_source,
        root_cause=root_cause,
        reproduction_context=reproduction_context,
        suggested_fix=suggested_fix,
        error_traceback=clean_traceback,
        occurrence_count=occurrence_count,
    )

    if gh_result and isinstance(gh_result, dict):
        async with async_session_factory() as session:
            db_entry = await session.get(ProductionBugLog, log_record.id)
            if db_entry:
                db_entry.github_issue_url = gh_result.get("url")
                db_entry.github_issue_number = gh_result.get("number")
                session.add(db_entry)
                await session.commit()
                await session.refresh(db_entry)
                log_record = db_entry

    return log_record
