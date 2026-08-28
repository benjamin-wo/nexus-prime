"""Fault-tolerant tool execution harness.

Covers core/tool_safety.py's three failure modes (malformed arguments,
endless retry loops, hangs) and orchestrator/agent_loop.py's execution
layer (safe concurrency, result ordering, runtime anchors).

The concurrency boundary under test is deliberate: only tools belonging to
a skill declared ``side_effect: read`` are batched. Writes stay sequential
so process_extracted_expense's interrupt() still fires before any later
write in the same round has run -- a resume re-enters the node from the
top, so a concurrent write could otherwise be applied twice.
"""
import asyncio
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.errors import GraphBubbleUp

from core.tool_safety import (
    MAX_REPEATED_FAILURES,
    FailureLedger,
    execute_tool_safely,
)
from orchestrator.agent_loop import (
    DEFAULT_TIMEZONE,
    _execute_tool_calls,
    _read_only_tool_names,
    _runtime_anchors,
)


@tool
async def book_slot(when_iso: str, seats: int) -> str:
    """Book a slot.

    Args:
        when_iso: ISO-8601 datetime.
        seats: number of seats to book.
    """
    return f"booked {seats} at {when_iso}"


# --------------------------------------------------------------------------
# 1. Malformed arguments -> actionable correction, not a stack-trace blob
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_args_produce_an_actionable_correction():
    outcome = await execute_tool_safely(
        book_slot, {"when_iso": "tonight", "seats": "not-a-number"}, tool_name="book_slot"
    )

    assert outcome.status == "invalid_args"
    assert outcome.retryable, "an argument mistake is the model's to fix -- it must be retryable"
    # Names the offending field and what was wrong with it...
    assert "seats" in outcome.observation
    assert "valid integer" in outcome.observation
    # ...and restates the schema, so the correction doesn't have to be guessed.
    assert "Expected arguments" in outcome.observation
    assert "when_iso" in outcome.observation
    assert "call the tool again" in outcome.observation.lower()


@pytest.mark.asyncio
async def test_the_self_correction_loop_succeeds_on_retry():
    """Spec case: malformed args trigger self-correction and succeed on retry."""
    ledger = FailureLedger()

    bad = await execute_tool_safely(
        book_slot, {"when_iso": "tonight", "seats": "two"}, tool_name="book_slot", ledger=ledger
    )
    assert bad.status == "invalid_args"

    good = await execute_tool_safely(
        book_slot,
        {"when_iso": "2026-08-28T18:00:00+08:00", "seats": 2},
        tool_name="book_slot",
        ledger=ledger,
    )
    assert good.ok
    assert "booked 2" in good.observation


# --------------------------------------------------------------------------
# 2. Endless retry loops are bounded
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_same_failing_call_is_cut_off_instead_of_burning_the_round_budget():
    """Before this, MAX_TOOL_ROUNDS (40) was the only thing stopping a model
    that kept repeating one broken call."""
    ledger = FailureLedger()
    calls = {"n": 0}

    class _AlwaysFails:
        name = "flaky"

        async def ainvoke(self, args):
            calls["n"] += 1
            raise RuntimeError("upstream is down")

    tool_obj = _AlwaysFails()
    args = {"q": "same every time"}

    for _ in range(MAX_REPEATED_FAILURES):
        outcome = await execute_tool_safely(tool_obj, args, tool_name="flaky", ledger=ledger)
        assert outcome.status == "error"

    terminal = await execute_tool_safely(tool_obj, args, tool_name="flaky", ledger=ledger)
    assert terminal.status == "gave_up"
    assert not terminal.retryable
    assert calls["n"] == MAX_REPEATED_FAILURES, "the exhausted call must not reach the tool again"
    assert "tell the user" in terminal.observation.lower()


@pytest.mark.asyncio
async def test_a_genuinely_different_call_is_not_penalised_by_the_ledger():
    """The cap keys on (tool, exact args) -- correcting the arguments must
    give the model a clean slate, or self-correction would be punished."""
    ledger = FailureLedger()

    class _FailsOnEmptyQuery:
        name = "search"

        async def ainvoke(self, args):
            if not args.get("q"):
                raise RuntimeError("empty query")
            return "found it"

    tool_obj = _FailsOnEmptyQuery()
    for _ in range(MAX_REPEATED_FAILURES + 1):
        await execute_tool_safely(tool_obj, {"q": ""}, tool_name="search", ledger=ledger)

    corrected = await execute_tool_safely(
        tool_obj, {"q": "fullerton sq"}, tool_name="search", ledger=ledger
    )
    assert corrected.ok
    assert corrected.observation == "found it"


# --------------------------------------------------------------------------
# 3. Hangs are bounded; interrupts are never swallowed
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_hung_tool_is_bounded_and_reports_honestly():
    class _Hangs:
        name = "stuck"

        async def ainvoke(self, args):
            await asyncio.Event().wait()

    outcome = await execute_tool_safely(_Hangs(), {}, tool_name="stuck", timeout=0.05)

    assert outcome.status == "timeout"
    assert "stuck" in outcome.observation
    assert "isn't responding" in outcome.observation


@pytest.mark.asyncio
async def test_an_interrupt_signal_is_never_treated_as_a_tool_failure():
    """HITL confirmation rides on GraphBubbleUp reaching the graph runtime.
    Swallowing it here would silently break every confirmation-gated write."""

    class _Interrupts:
        name = "process_extracted_expense"

        async def ainvoke(self, args):
            raise GraphBubbleUp()

    with pytest.raises(GraphBubbleUp):
        await execute_tool_safely(_Interrupts(), {}, tool_name="process_extracted_expense")


@pytest.mark.asyncio
async def test_an_unknown_tool_name_is_reported_not_crashed():
    outcome = await execute_tool_safely(None, {}, tool_name="does_not_exist")
    assert outcome.status == "unknown_tool"
    assert "does_not_exist" in outcome.observation


# --------------------------------------------------------------------------
# 4. Execution layer: concurrency, ordering
# --------------------------------------------------------------------------

class _RecordingTool:
    def __init__(self, name, delay, log):
        self.name = name
        self._delay = delay
        self._log = log

    async def ainvoke(self, args):
        self._log.append(("start", self.name))
        await asyncio.sleep(self._delay)
        self._log.append(("end", self.name))
        return f"{self.name} ok"


def _call(name, i):
    return {"name": name, "args": {}, "id": f"call_{i}", "type": "tool_call"}


@pytest.mark.asyncio
async def test_read_only_tools_run_concurrently():
    """Three independent transit lookups should cost one round-trip, not three."""
    log = []
    delay = 0.15
    tools = [_RecordingTool(n, delay, log) for n in ("get_bus_timings", "transit_journey", "search_web")]
    calls = [_call(t.name, i) for i, t in enumerate(tools)]
    hist = []

    started = time.monotonic()
    await _execute_tool_calls(
        calls, tools, hist, [], FailureLedger(), {t.name for t in tools}, round_label="round 0"
    )
    elapsed = time.monotonic() - started

    assert elapsed < delay * 2, f"expected concurrent execution, took {elapsed:.2f}s"
    # All three had started before any had finished -- the definition of concurrent.
    assert log[:3] == [("start", "get_bus_timings"), ("start", "transit_journey"), ("start", "search_web")]


@pytest.mark.asyncio
async def test_write_tools_stay_strictly_sequential():
    """Interleaved starts would mean a later write could land before an
    earlier one's interrupt() had a chance to fire."""
    log = []
    tools = [_RecordingTool(n, 0.05, log) for n in ("process_extracted_expense", "pin_note_to_whiteboard")]
    calls = [_call(t.name, i) for i, t in enumerate(tools)]

    await _execute_tool_calls(calls, tools, [], [], FailureLedger(), set(), round_label="round 0")

    assert log == [
        ("start", "process_extracted_expense"),
        ("end", "process_extracted_expense"),
        ("start", "pin_note_to_whiteboard"),
        ("end", "pin_note_to_whiteboard"),
    ]


@pytest.mark.asyncio
async def test_results_are_appended_in_the_order_the_model_asked_for():
    """A provider rejects a tool_calls message whose results are reordered or
    missing, so ordering is a correctness requirement -- and concurrency is
    exactly what could break it."""
    log = []
    # Deliberately inverted durations: the last call finishes first.
    tools = [
        _RecordingTool("slow_read", 0.12, log),
        _RecordingTool("fast_read", 0.01, log),
        _RecordingTool("a_write", 0.01, log),
    ]
    calls = [_call(t.name, i) for i, t in enumerate(tools)]
    hist = []

    await _execute_tool_calls(
        calls, tools, hist, [], FailureLedger(), {"slow_read", "fast_read"}, round_label="round 0"
    )

    assert [m.tool_call_id for m in hist] == ["call_0", "call_1", "call_2"]
    assert all(isinstance(m, ToolMessage) for m in hist)
    assert "slow_read ok" in hist[0].content


@pytest.mark.asyncio
async def test_a_failing_tool_in_a_concurrent_batch_does_not_lose_its_siblings():
    log = []
    good = _RecordingTool("good_read", 0.01, log)

    class _Explodes:
        name = "bad_read"

        async def ainvoke(self, args):
            raise RuntimeError("boom")

    tools = [good, _Explodes()]
    calls = [_call("good_read", 0), _call("bad_read", 1)]
    hist = []

    await _execute_tool_calls(
        calls, tools, hist, [], FailureLedger(), {"good_read", "bad_read"}, round_label="round 0"
    )

    assert len(hist) == 2
    assert "good_read ok" in hist[0].content
    assert "boom" in hist[1].content


def test_read_only_names_come_from_declared_skill_side_effects():
    class _Skill:
        def __init__(self, side_effect, tools):
            self.side_effect = side_effect
            self.tools = tools

    names = _read_only_tool_names({
        "transit": _Skill("read", ["get_bus_timings", "transit_journey"]),
        "expenses": _Skill("write", ["process_extracted_expense"]),
    })
    assert names == {"get_bus_timings", "transit_journey"}
    assert "process_extracted_expense" not in names


# --------------------------------------------------------------------------
# 5. Runtime anchors
# --------------------------------------------------------------------------

def test_runtime_anchors_follow_the_users_actual_timezone():
    """Live bug: current_timezone is user-settable (/timezone, a location pin,
    "I just landed in Tokyo") and passed into graph state, but the prompt
    hardcoded Asia/Singapore and called it "Current Singapore time"."""
    anchors = _runtime_anchors("Asia/Tokyo")

    assert "timezone: Asia/Tokyo" in anchors
    assert "current_time_iso:" in anchors
    assert "Singapore" not in anchors
    assert "+09:00" in anchors, "the ISO anchor must carry Tokyo's real offset"


def test_a_corrupt_stored_timezone_falls_back_instead_of_breaking_the_turn():
    anchors = _runtime_anchors("Not/AReal_Zone")
    assert f"timezone: {DEFAULT_TIMEZONE}" in anchors
    assert "current_time_iso:" in anchors


@pytest.mark.asyncio
async def test_the_system_prompt_carries_the_users_timezone_end_to_end(monkeypatch):
    import orchestrator.agent_loop as al

    captured = []

    class _CapturingLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            captured.append(list(messages))
            return AIMessage(content="ok")

    monkeypatch.setattr(al, "get_agent_llm", lambda *a, **k: _CapturingLLM())
    monkeypatch.setattr(al.settings, "gemini_api_key", "fake-key-for-test")

    await al.agent_loop({
        "user_id": 4242,
        "current_timezone": "Asia/Tokyo",
        "messages": [HumanMessage(content="remind me at 6pm")],
    })

    system_text = str(captured[0][0].content)
    assert "timezone: Asia/Tokyo" in system_text
    assert "Current Singapore time" not in system_text
