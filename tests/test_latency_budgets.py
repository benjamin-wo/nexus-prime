"""Runaway-loop backstop test: confirms orchestrator/agent_loop.py's
MAX_TOOL_ROUNDS actually terminates a tool-calling loop that never stops
wanting to call another tool.

This file used to be a "latency budget" chaos suite -- sweeping every multi-
call pipeline for individually-bounded async calls whose SUM exceeded an
even-more-outer webhook deadline (the bug behind #45 and GeneralPlugin's
tool loop). That whole class of bug is gone along with the deterministic
router and its per-turn timeouts (GENERAL_TOOL_LOOP_TIMEOUT_SECONDS,
WEBHOOK_PROCESSING_TIMEOUT_SECONDS, PLANNING_INTAKE_TIMEOUT_SECONDS) -- the
user explicitly asked that time not limit the agent, and app/webhook.py now
acks Telegram immediately and lets a turn run as long as it genuinely needs
(see app/webhook.py's docstring).

What still needs a backstop is a genuinely broken loop: a tool whose result
always makes the model want to call it again. MAX_TOOL_ROUNDS exists purely
to catch that -- not to protect any external deadline -- so this test scripts
an LLM that always requests another tool call and confirms the loop
terminates after MAX_TOOL_ROUNDS rounds rather than running forever.
"""
import asyncio
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage


@pytest.mark.asyncio
async def test_agent_loop_tool_round_cap_terminates_a_runaway_loop(monkeypatch):
    import orchestrator.agent_loop as agent_loop_module
    from orchestrator.agent_loop import agent_loop

    class _AlwaysToolCallingLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            # Always requests another tool call -- the true worst case
            # (a genuinely broken loop), not the typical 1-round happy path.
            return AIMessage(content="", tool_calls=[{
                "name": "search_web",
                "args": {"query": "test"},
                "id": f"call_{self.calls}",
                "type": "tool_call",
            }])

    fake_llm = _AlwaysToolCallingLLM()

    class _FastSearchTool:
        name = "search_web"

        async def ainvoke(self, args):
            return "Summary: fine"

    import capabilities.general.tools as general_tools

    monkeypatch.setattr(general_tools, "search_web", _FastSearchTool())
    monkeypatch.setattr(agent_loop_module, "get_agent_llm", lambda *a, **k: fake_llm)
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")

    started = time.monotonic()
    command = await asyncio.wait_for(
        agent_loop({
            "user_id": 9301,
            "messages": [HumanMessage(content="what's new in the news today")],
        }),
        # A generous outer bound on the *test itself* -- every mocked call
        # above is instant, so a correctly-capped loop finishes in
        # well under a second. This is not simulating any production
        # timeout; it's just so a genuinely broken loop fails the test
        # fast instead of hanging the test suite.
        timeout=10.0,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"loop took {elapsed:.2f}s -- MAX_TOOL_ROUNDS backstop did not engage"
    # MAX_TOOL_ROUNDS rounds, plus the one initial call before the loop's
    # first round check, plus the round-budget-exhausted final call.
    assert fake_llm.calls <= agent_loop_module.MAX_TOOL_ROUNDS + 2
    assert fake_llm.calls > agent_loop_module.MAX_TOOL_ROUNDS, (
        "the loop stopped suspiciously early -- confirm it actually ran to the cap"
    )
    # A capped-out loop still answers from whatever it has, never a hang.
    assert command.update["messages"][-1].content
