"""The model-fallback circuit breaker: primary Gemini capacity failures
(503 high-demand / 504 deadline) degrade the turn to llm_fallback_model
instead of shipping an error."""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

import orchestrator.agent_loop as al
from core.config import settings
from orchestrator.agent_loop import agent_loop


class _FakeLLM:
    def __init__(self, kind: str):
        self.kind = kind

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if self.kind == "primary":
            raise Exception(
                "504 DEADLINE_EXCEEDED. {'error': {'code': 504, 'message': "
                "'Deadline expired before operation could complete.', 'status': 'DEADLINE_EXCEEDED'}}"
            )
        return AIMessage(content="hi there! (degraded-model reply)")


@pytest.mark.asyncio
async def test_capacity_error_degrades_to_fallback_model(monkeypatch):
    made = []

    def fake_get_llm(*args, **kwargs):
        kind = "fallback" if kwargs.get("model") else "primary"
        made.append(kind)
        return _FakeLLM(kind)

    monkeypatch.setattr(al, "get_agent_llm", fake_get_llm)
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_fallback_model", "gemini-2.5-flash")

    result = await agent_loop({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="hi")],
    })

    assert made == ["primary", "fallback"], made
    reply = str(result.update["messages"][-1].content)
    assert "degraded-model reply" in reply


@pytest.mark.asyncio
async def test_non_capacity_error_does_not_degrade(monkeypatch):
    """A non-capacity failure (bad request shape, auth, bug) must NOT silently
    switch models -- it propagates to the honest-error path."""
    made = []

    class _BrokenLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            raise ValueError("malformed request")

    def fake_get_llm(*args, **kwargs):
        made.append(kwargs.get("model") or "primary")
        return _BrokenLLM()

    monkeypatch.setattr(al, "get_agent_llm", fake_get_llm)
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_fallback_model", "gemini-2.5-flash")

    result = await agent_loop({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="hi")],
    })

    assert made == ["primary"], made
    reply = str(result.update["messages"][-1].content)
    assert "glitched" in reply  # _ERROR_REPLY_FALLBACK


@pytest.mark.asyncio
async def test_fallback_disabled_ships_error(monkeypatch):
    monkeypatch.setattr(al, "get_agent_llm", lambda *a, **k: _FakeLLM("primary"))
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_fallback_model", "")

    result = await agent_loop({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="hi")],
    })
    assert "glitched" in str(result.update["messages"][-1].content)
