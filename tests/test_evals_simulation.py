import pytest
from langchain_core.messages import AIMessage

from evals.config import EvalConfig
from evals.scenarios import get_scenario
from evals.simulation import run_persona, run_scripted

CFG = EvalConfig()


async def _echo_bot(messages, cfg):
    last = str(messages[-1].content)
    return f"Echo: {last}", [AIMessage(content=f"Echo: {last}")], 0.1


async def _tool_bot(messages, cfg):
    return (
        "Logged 15.50 for you",
        [
            AIMessage(content="", tool_calls=[{"name": "process_extracted_expense", "id": "c1", "args": {}}]),
            AIMessage(content="Logged 15.50 for you"),
        ],
        0.2,
    )


@pytest.mark.asyncio
async def test_run_scripted_passes_kernel_scenario():
    scenario = get_scenario("termination_kernel")
    result = await run_scripted(scenario, CFG, bot=_echo_bot)
    assert result.status == "passed"
    assert result.metrics["goal_completed"] is True
    assert result.conversation is not None
    assert len(result.conversation.turns) == 2  # user + assistant


@pytest.mark.asyncio
async def test_run_scripted_tracks_tool_usage():
    scenario = get_scenario("expense_log")
    result = await run_scripted(scenario, CFG, bot=_tool_bot)
    assert result.status == "passed"
    assert "process_extracted_expense" in result.metrics["tools_used"]
    assert result.metrics["tools_ok"] is True


@pytest.mark.asyncio
async def test_run_scripted_fails_missing_slot():
    async def _wrong_bot(messages, cfg):
        return "Echo: nope", [AIMessage(content="Echo: nope")], 0.1

    scenario = get_scenario("expense_log")
    result = await run_scripted(scenario, CFG, bot=_wrong_bot)
    assert result.status == "failed"
    assert result.metrics["goal_completed"] is False


@pytest.mark.asyncio
async def test_run_scripted_error_status():
    async def _broken_bot(messages, cfg):
        raise RuntimeError("boom")

    scenario = get_scenario("expense_log")
    result = await run_scripted(scenario, CFG, bot=_broken_bot)
    assert result.status == "error"
    assert "boom" in result.error


@pytest.mark.asyncio
async def test_run_persona_immediate_done_fails():
    class _FakePersona:
        async def ainvoke(self, messages):
            return AIMessage(content="[[DONE]]")

    scenario = get_scenario("persona_expense_flow")
    result = await run_persona(scenario, CFG, _FakePersona(), bot=_echo_bot)
    assert result.status == "failed"
    assert result.metrics["goal_completed"] is False


@pytest.mark.asyncio
async def test_run_persona_completes_flow():
    class _FakePersona:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls > 1:
                return AIMessage(content="[[DONE]]")
            return AIMessage(content="Log 16 for lunch at kopitiam")

    scenario = get_scenario("persona_expense_flow")
    result = await run_persona(scenario, CFG, _FakePersona(), bot=_echo_bot)
    assert result.status == "passed"
    assert result.metrics["persona_done"] is True
    assert len(result.turns) == 1