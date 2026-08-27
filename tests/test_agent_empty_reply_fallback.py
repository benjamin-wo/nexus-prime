"""Live incident: mid-conversation (following up a bus-stop disambiguation
with "That should be the name"), the model returned a genuinely empty
completion -- no text, no tool call. orchestrator/agent_loop.py's fallback
for that case used to be _generate_rule_based_response's canned "here's
what I can help with" capabilities blurb, which reads as the bot having
completely forgotten the conversation it was just actively engaged in --
confirmed live via Railway production logs (chat=149917165, 2026-08-27
10:01 UTC): the bot's very next reply to "That should be the name" was
that exact capabilities blurb, a total non-sequitur.

Fix: _run_tool_loop retries once on a genuinely empty completion (same
shape as the existing URL-guard retry), and the fallback if it's still
empty is a short, honest miss -- not the "no LLM configured" blurb, which
is now reserved for the genuine no-API-key case.
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from orchestrator.agent_loop import agent_loop, _EMPTY_REPLY_FALLBACK, _ERROR_REPLY_FALLBACK


class _EmptyThenRealLLM:
    """First call returns a genuinely empty completion (no text, no tool
    call) -- the exact reproduction; second call (the retry) answers."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        idx = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[idx]


async def _run(monkeypatch, llm, text="That should be the name"):
    import orchestrator.agent_loop as agent_loop_module

    monkeypatch.setattr(agent_loop_module, "get_agent_llm", lambda *a, **k: llm)
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")

    command = await agent_loop({
        "user_id": 149917165,
        "messages": [HumanMessage(content=text)],
    })
    return str(command.update["messages"][-1].content)


@pytest.mark.asyncio
async def test_empty_completion_retries_and_recovers(monkeypatch):
    llm = _EmptyThenRealLLM([
        AIMessage(content=""),  # the exact reproduction: nothing at all
        AIMessage(content="Got it — searching bus stops near Fullerton Sq now."),
    ])

    reply = await _run(monkeypatch, llm)

    assert reply == "Got it — searching bus stops near Fullerton Sq now."
    assert llm.calls == 2, "should have retried exactly once after the empty completion"


@pytest.mark.asyncio
async def test_empty_completion_still_empty_after_retry_gives_an_honest_miss_not_the_capabilities_blurb(monkeypatch):
    """If the retry ALSO comes back empty, the fallback must not be the
    "here's what I can help with" blurb -- that specific message is reserved
    for the no-LLM-key path and is actively misleading mid-conversation."""
    llm = _EmptyThenRealLLM([
        AIMessage(content=""),
        AIMessage(content=""),
    ])

    reply = await _run(monkeypatch, llm)

    assert reply == _EMPTY_REPLY_FALLBACK
    assert "here is what i can help you with" not in reply.lower()
    assert "track expenses" not in reply.lower()
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_tool_loop_exception_gives_an_honest_error_not_the_capabilities_blurb(monkeypatch):
    """Same reasoning for a genuine exception mid-loop: a crash still
    shouldn't look like the bot forgot the conversation."""
    import orchestrator.agent_loop as agent_loop_module

    class _BrokenLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            raise RuntimeError("simulated provider failure")

    monkeypatch.setattr(agent_loop_module, "get_agent_llm", lambda *a, **k: _BrokenLLM())
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")

    command = await agent_loop({
        "user_id": 149917165,
        "messages": [HumanMessage(content="what time is the next bus")],
    })

    reply = str(command.update["messages"][-1].content)
    assert reply == _ERROR_REPLY_FALLBACK
    assert "track expenses" not in reply.lower()
