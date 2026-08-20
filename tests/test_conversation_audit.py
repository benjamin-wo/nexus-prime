import pytest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from sqlmodel import select

from core.audit import perform_conversation_audit, should_audit_conversation
from core.db import async_session_factory
from core.models import ConversationAuditLog


def test_conversation_audit_cadence():
    assert should_audit_conversation(5) is True
    assert should_audit_conversation(10) is True
    assert should_audit_conversation(4) is False
    assert should_audit_conversation(0) is False
    assert should_audit_conversation(6, every_n=3) is True
    assert should_audit_conversation(4, every_n=3) is False


@pytest.mark.asyncio
async def test_conversation_audit_persists_scorecard():
    messages = [
        HumanMessage(content="what bus should I take from Tembusu Grand to Suntec"),
        AIMessage(content="Take 27 from Tembusu Grand to Suntec City"),
    ]
    payload = {
        "faithfulness_score": 5,
        "routing_score": 4,
        "tool_correctness_score": 2,
        "helpfulness_score": 3,
        "verdict": "review",
        "evidence": "Bus number was wrong in turn 1.",
    }
    with patch("core.audit._judge_conversation_with_gemini", new=AsyncMock(return_value=payload)):
        row = await perform_conversation_audit(
            user_id=42, thread_id="t42", messages=messages, judge_model="gemini-3.1-pro"
        )
    assert row.message_count == 2
    assert row.tool_correctness_score == 2
    assert row.verdict == "review"
    assert row.judge_model == "gemini-3.1-pro"
    async with async_session_factory() as session:
        rows = (await session.execute(select(ConversationAuditLog))).scalars().all()
        assert any(r.thread_id == "t42" for r in rows)


@pytest.mark.asyncio
async def test_conversation_audit_alerts_admin_on_critical():
    messages = [HumanMessage(content="bus route"), AIMessage(content="wrong answer")]
    payload = {
        "faithfulness_score": 1,
        "routing_score": 2,
        "tool_correctness_score": 1,
        "helpfulness_score": 2,
        "verdict": "critical",
        "evidence": "Wrong bus number hallucinated.",
    }
    sent = {}

    async def _fake_send(chat_id, text, reply_markup=None):
        sent["chat_id"] = chat_id
        sent["text"] = text
        return True

    with patch("core.audit._judge_conversation_with_gemini", new=AsyncMock(return_value=payload)):
        with patch("core.audit.settings.admin_telegram_chat_id", "999888"):
            with patch("app.ingress.send_telegram_message", new=_fake_send):
                await perform_conversation_audit(
                    user_id=149917165, thread_id="149917165", messages=messages
                )
    # Admin channel notified, NOT the user chat
    assert sent.get("chat_id") == 999888
    assert "AUDIT ANOMALY" in sent.get("text", "")
    assert "Wrong bus number hallucinated" in sent.get("text", "")


@pytest.mark.asyncio
async def test_conversation_audit_falls_back_when_judge_fails():
    messages = [HumanMessage(content="hi")]
    with patch(
        "core.audit._judge_conversation_with_gemini",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        row = await perform_conversation_audit(user_id=43, thread_id="t43", messages=messages)
    assert row.verdict == "review"
    assert "judge call failed" in row.evidence
