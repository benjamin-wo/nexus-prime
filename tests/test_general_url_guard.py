"""Regression (#42, #43): the model was asked directly for a link and
fabricated one -- a plausible-looking Instagram reel URL, dead
Foodadvisor/Burpple/Tripadvisor links -- instead of calling
search_web/fetch_url. Confirmed against real production logs (both bugs
occurred *after* fetch_url (#22/PR #41) was already deployed, so the tool
existed and simply wasn't invoked).

orchestrator/agent_loop.py's _compose_reply() (formerly GeneralPlugin.execute,
carried over verbatim in shape when the deterministic capability router was
replaced by direct agentic tool-calling) tracks whether search_web/fetch_url
actually ran this turn; a raw http(s) URL in the reply without either tool
having run triggers one corrective retry (an explicit reminder to call a real
tool or drop the link), and if that retry still produces an unverified URL,
it gets stripped rather than shipped.
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from orchestrator.agent_loop import agent_loop

USER_ID = 5252


class _ScriptedToolLLM:
    """Replays a fixed sequence of AIMessage responses, one per ainvoke call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        idx = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[idx]


def _tool_call(name, call_id, query="claypot chicken rice orchard towers"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"query": query}, "id": call_id, "type": "tool_call"}],
    )


async def _run(monkeypatch, llm, text="Can send me the claypot chicken rice link?"):
    import orchestrator.agent_loop as agent_loop_module

    monkeypatch.setattr(agent_loop_module, "get_agent_llm", lambda *a, **k: llm)
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")

    command = await agent_loop({
        "user_id": USER_ID,
        "messages": [HumanMessage(content=text)],
    })
    # The final reply is always last -- any tool-call/tool-result messages
    # from this turn are persisted ahead of it (regression #53).
    return str(command.update["messages"][-1].content)


@pytest.mark.asyncio
async def test_hallucinated_link_stripped_when_no_tool_ever_called(monkeypatch):
    """Exact #42/#43 shape: the model never calls search_web or fetch_url at
    all, even after the corrective nudge -- the fabricated link must not
    reach the user."""
    llm = _ScriptedToolLLM([
        AIMessage(content="here's a reel about it! https://www.instagram.com/reel/DN9-WtLAZHk"),
        AIMessage(content="here's a link: https://www.foodadvisor.com.sg/restaurant/fake-listing"),
    ])

    reply = await _run(monkeypatch, llm)

    assert "http" not in reply, f"unverified URL leaked into the reply: {reply!r}"
    assert "verified link" in reply.lower()
    assert llm.calls == 2, "should have retried exactly once after the nudge"


@pytest.mark.asyncio
async def test_real_search_backed_link_passes_through_untouched(monkeypatch):
    """When the model calls search_web and the link comes from its result,
    nothing should be stripped or retried."""
    import capabilities.general.tools as general_tools

    class _SpySearchTool:
        name = "search_web"
        calls = 0

        async def ainvoke(self, args):
            type(self).calls += 1
            return "Summary: found it.\n- Claypot Rice (https://real-search-result.example.com/page): great reviews"

    monkeypatch.setattr(general_tools, "search_web", _SpySearchTool())
    llm = _ScriptedToolLLM([
        _tool_call("search_web", "call_1"),
        AIMessage(content="here's a real link: https://real-search-result.example.com/page"),
    ])

    reply = await _run(monkeypatch, llm)

    assert "https://real-search-result.example.com/page" in reply
    assert _SpySearchTool.calls == 1
    assert llm.calls == 2, "no corrective retry should fire when a tool actually backed the link"


@pytest.mark.asyncio
async def test_retry_succeeds_once_model_actually_calls_search(monkeypatch):
    """First pass hallucinates with no tool call (triggers the guard); the
    corrective retry then genuinely calls search_web and the real result
    should ship, not get stripped."""
    import capabilities.general.tools as general_tools

    class _SpySearchTool:
        name = "search_web"
        calls = 0

        async def ainvoke(self, args):
            type(self).calls += 1
            return "Summary: found it.\n- Isle Eating House (https://real-foodblog.example.com/isle): great reviews"

    monkeypatch.setattr(general_tools, "search_web", _SpySearchTool())
    llm = _ScriptedToolLLM([
        AIMessage(content="here's a link: https://www.foodadvisor.com.sg/fake"),  # pass 1: hallucinated, no tool
        _tool_call("search_web", "call_1"),  # pass 2, round 1: now actually searches
        AIMessage(content="found it: https://real-foodblog.example.com/isle"),  # pass 2, round 2: real answer
    ])

    reply = await _run(monkeypatch, llm, text="Any links")

    assert "https://real-foodblog.example.com/isle" in reply
    assert "foodadvisor.com.sg/fake" not in reply
    assert _SpySearchTool.calls == 1
