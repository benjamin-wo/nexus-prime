"""Live incident (chat=149917165, "Coffee at hive Adelphi Samuel paid me
5.50..."): round-by-round tracing added to _run_tool_loop caught a model
call hanging forever -- "[AGENT_LOOP] round 1: awaiting model completion"
printed, then total silence for 6+ minutes straight, no TimeoutError, no
reply, nothing -- despite core/llm.py already configuring
timeout=LLM_REQUEST_TIMEOUT_SECONDS on every LLM client. Whatever the
client-level timeout's blind spot is, a turn must never be able to hang
the whole (fire-and-forget, per app/webhook.py) background task forever.

Fix: orchestrator/agent_loop.py's _invoke_model wraps every llm.ainvoke()
call in an explicit asyncio.wait_for, independent of the client's own
timeout config -- a stuck call now surfaces as a normal TimeoutError
instead of hanging, and the existing honest-error fallback takes it from
there exactly like any other tool-loop exception."""
import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from orchestrator.agent_loop import _ERROR_REPLY_FALLBACK, agent_loop


class _HangsForeverLLM:
    """Reproduces the exact live shape: bind_tools().ainvoke() never
    returns and never raises on its own -- the client-level timeout that's
    supposed to guard against exactly this simply didn't fire."""

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        await asyncio.Event().wait()  # never set -- hangs forever
        return AIMessage(content="unreachable")


@pytest.mark.asyncio
async def test_a_hung_model_call_times_out_instead_of_hanging_the_turn_forever(monkeypatch):
    import orchestrator.agent_loop as agent_loop_module

    # Real timeout mechanics, just fast enough for a test.
    monkeypatch.setattr(agent_loop_module, "_MODEL_CALL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(agent_loop_module, "get_agent_llm", lambda *a, **k: _HangsForeverLLM())
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")

    command = await asyncio.wait_for(
        agent_loop({
            "user_id": 149917165,
            "messages": [HumanMessage(content="Coffee at hive Adelphi Samuel paid me 5.50 because I paid first")],
        }),
        timeout=5.0,  # the test's own outer bound -- must never actually be needed
    )

    reply = str(command.update["messages"][-1].content)
    assert reply == _ERROR_REPLY_FALLBACK
