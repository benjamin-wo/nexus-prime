"""Why the judge and the operations sweep stayed silent through an outage.

On 2026-08-28 the bot suffered a total silent-reply outage: turns wedged,
twelve identity_bound tools rejected every call with invalid_args, and users
got nothing back. Throughout, `[OPS SWEEP] completed with 0 issue(s)
recorded.` printed every fifteen minutes and not one GitHub issue was filed.

That was structural, not bad luck. Four blind spots:

1. The operations sweep probed only static configuration -- credentials
   present, DB reachable, scheduler object running, token set. All four stay
   green while the service answers nobody. It asked "is this CONFIGURED?",
   never "is this WORKING?".
2. agent_loop catches every tool-loop exception and answers with
   _ERROR_REPLY_FALLBACK. app/ingress.py's report_production_bug sits outside
   that catch, so it never saw a failure the agent loop handled -- i.e. almost
   none of them.
3. A tool failing validation was pure log noise. Twelve tools returned
   invalid_args on every call for as long as they existed and nothing
   anywhere counted it.
4. A wedged turn was unobservable: it holds its per-chat lock, silently
   queueing every later message from that chat, and no probe could see it.

The judge (perform_conversation_audit) is a fifth, partly by design: it runs
at the END of a completed turn and only every 4th human message, so a turn
that never completes is invisible to it and 3 in 4 that do are skipped. These
tests cover the four fixed above; the judge's cadence is left alone.
"""
import asyncio
import time

import pytest


# --- 1 & 2: agent_loop reports what it used to swallow --------------------

@pytest.mark.asyncio
async def test_a_failed_turn_files_an_incident_instead_of_only_printing(monkeypatch):
    """The user got a non-answer -- that is a P1, and it used to be a print."""
    from langchain_core.messages import HumanMessage

    import orchestrator.agent_loop as al

    recorded = []

    async def _spy(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(al, "record_operation_event", _spy)
    monkeypatch.setattr(al.settings, "gemini_api_key", "fake-key-for-test")

    class _BrokenLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            raise RuntimeError("simulated provider failure")

    monkeypatch.setattr(al, "get_agent_llm", lambda *a, **k: _BrokenLLM())

    command = await al.agent_loop({
        "user_id": 149917165,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="what are my recent expenses")],
    })

    # The user still gets the honest fallback...
    assert str(command.update["messages"][-1].content) == al._ERROR_REPLY_FALLBACK
    # ...and now somebody is told about it.
    await asyncio.sleep(0.05)
    assert recorded, "a failed turn must file an incident"
    incident = recorded[0]
    assert incident["severity"] == "P1"
    assert incident["fingerprint"] == "agent_loop_failure_RuntimeError"
    assert "simulated provider failure" in incident["error_context"]
    assert incident["error_traceback"]


# --- 3: a tool the model cannot call is a defect, and gets reported -------

@pytest.mark.asyncio
async def test_a_tool_rejecting_its_arguments_files_an_incident(monkeypatch):
    """Reproduces the #76 shape: get_user_expenses returned invalid_args on
    every call and nothing noticed."""
    import orchestrator.agent_loop as al
    from core.tool_safety import FailureLedger

    recorded = []

    async def _spy(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(al, "record_operation_event", _spy)

    class _RejectsArgs:
        name = "get_user_expenses"

        async def ainvoke(self, args):
            raise ValueError("Field required: user_id")

    hist = []
    await al._execute_tool_calls(
        [{"name": "get_user_expenses", "args": {}, "id": "c1"}],
        [_RejectsArgs()], hist, [], FailureLedger(), set(), round_label="round 0",
    )

    await asyncio.sleep(0.05)
    assert recorded, "a tool failure must file an incident"
    assert recorded[0]["fingerprint"] == "agent_tool_get_user_expenses_error"
    assert recorded[0]["subsystem"] == "tool:get_user_expenses"


@pytest.mark.asyncio
async def test_a_successful_tool_call_files_nothing(monkeypatch):
    """Telemetry must be signal, not noise."""
    import orchestrator.agent_loop as al
    from core.tool_safety import FailureLedger

    recorded = []

    async def _spy(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(al, "record_operation_event", _spy)

    class _Works:
        name = "get_bus_timings"

        async def ainvoke(self, args):
            return "Bus 10: 3 min"

    await al._execute_tool_calls(
        [{"name": "get_bus_timings", "args": {}, "id": "c1"}],
        [_Works()], [], [], FailureLedger(), {"get_bus_timings"}, round_label="round 0",
    )

    await asyncio.sleep(0.05)
    assert recorded == []


def test_reportable_failures_exclude_success_and_unknown_tool():
    from orchestrator.agent_loop import _REPORTABLE_TOOL_FAILURES

    assert "success" not in _REPORTABLE_TOOL_FAILURES
    assert "unknown_tool" not in _REPORTABLE_TOOL_FAILURES
    assert _REPORTABLE_TOOL_FAILURES["gave_up"] == "P1"


# --- 4: a wedged chat is observable, and the sweep looks --------------------

@pytest.mark.asyncio
async def test_a_wedged_chat_is_visible_while_a_healthy_turn_is_not():
    from app.ingress import TelegramIngress

    TelegramIngress._chat_lock_held_since.clear()
    try:
        now = time.monotonic()
        TelegramIngress._chat_lock_held_since[111] = now - 600   # wedged 10 min
        TelegramIngress._chat_lock_held_since[222] = now - 3     # normal turn

        wedged = TelegramIngress.wedged_chats(threshold_seconds=300.0)

        assert [w["chat_id"] for w in wedged] == [111]
        assert wedged[0]["held_seconds"] > 300
    finally:
        TelegramIngress._chat_lock_held_since.clear()


@pytest.mark.asyncio
async def test_no_turn_in_flight_means_nothing_wedged():
    from app.ingress import TelegramIngress

    TelegramIngress._chat_lock_held_since.clear()
    assert TelegramIngress.wedged_chats(threshold_seconds=300.0) == []


@pytest.mark.asyncio
async def test_the_operations_sweep_now_raises_a_wedged_chat(monkeypatch):
    """The probe that would have caught the outage: every config check stayed
    green while the bot answered nobody."""
    import core.scheduler as sched
    from app.ingress import TelegramIngress

    recorded = []

    async def _spy(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr("core.audit.record_operation_event", _spy)

    TelegramIngress._chat_lock_held_since.clear()
    TelegramIngress._chat_lock_held_since[149917165] = time.monotonic() - 900
    try:
        await sched._run_operations_health_sweep()
    finally:
        TelegramIngress._chat_lock_held_since.clear()

    wedged = [r for r in recorded if r.get("fingerprint", "").startswith("wedged_chat_")]
    assert wedged, "the sweep must report a wedged chat"
    assert wedged[0]["severity"] == "P1"
    assert wedged[0]["subsystem"] == "agent_loop"
    assert "149917165" in wedged[0]["error_context"]


@pytest.mark.asyncio
async def test_the_sweep_stays_quiet_when_the_service_is_actually_healthy(monkeypatch):
    import core.scheduler as sched
    from app.ingress import TelegramIngress

    recorded = []

    async def _spy(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr("core.audit.record_operation_event", _spy)
    TelegramIngress._chat_lock_held_since.clear()

    await sched._run_operations_health_sweep()

    assert not [r for r in recorded if r.get("fingerprint", "").startswith("wedged_chat_")]
