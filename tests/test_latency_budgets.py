"""Latency-budget "chaos" tests: sweep every multi-call pipeline for the one
bug shape that unit tests with instant mocks can never see by construction --
several individually-bounded async calls whose SUM exceeds an even-more-outer
bound. This is exactly what took down whiteboard planning-intake (#45) and,
discovered while writing this file, GeneralPlugin's tool loop too (fixed in
the same change as this test).

Every test here mocks its dependencies to sleep close to their *configured
max*, not instantly -- the whole point is to exercise the ceiling case, not
the typical case. A pipeline with no outer bound will blow its wall-clock
budget in these tests; one with a correct bound will fail fast with a
graceful fallback instead.
"""
import asyncio
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage

# A test is "fast enough" if it returns comfortably under the real production
# ceiling scaled down by the same factor every mocked sleep is scaled down by
# in each test below (see individual SCALE comments).
WEBHOOK_CEILING_SECONDS = 45.0


@pytest.mark.asyncio
async def test_whiteboard_planning_intake_never_exceeds_webhook_budget(monkeypatch):
    """comprehend_request() and the research pass are each individually
    bounded (30s / 15s respectively) but nothing bounds their SUM without
    PLANNING_INTAKE_TIMEOUT_SECONDS wrapping the whole call (#45). Mock both
    to sleep right at their real ceiling, scaled down 100x so the test runs
    in under a second, and confirm the wrapped call still respects a
    proportionally-scaled webhook budget."""
    from capabilities.whiteboard import planner as wb_planner
    import orchestrator.router as router_module
    from orchestrator.router import WhiteboardPlugin
    from orchestrator.state import AssistantState

    SCALE = 100.0  # real: comprehend ~30s + research ~15s vs 45s webhook ceiling
    monkeypatch.setattr(router_module, "PLANNING_INTAKE_TIMEOUT_SECONDS", 35.0 / SCALE)

    async def slow_comprehend(text, board_context=None, recent_context=""):
        # Stands in for comprehend_request's own ~30s ceiling PLUS a
        # subsequent research pass's ~15s -- individually each fits its own
        # bound, but their sum (45s) exceeds PLANNING_INTAKE_TIMEOUT_SECONDS
        # (35s), which is exactly the bug: nothing bounded the sum before #45.
        await asyncio.sleep(45.0 / SCALE)
        return {"action": "none"}

    monkeypatch.setattr(wb_planner, "comprehend_request", slow_comprehend)

    plugin = WhiteboardPlugin()
    state = AssistantState(
        messages=[HumanMessage(content="bring up my upcoming trip so I can plan some stuff")],
        user_id=9201,
    )

    started = time.monotonic()
    result = await plugin.execute(state)
    elapsed = time.monotonic() - started

    assert elapsed < WEBHOOK_CEILING_SECONDS / SCALE, (
        f"planning-intake took {elapsed:.2f}s (scaled) -- must fail fast at its own "
        "bound rather than approach the webhook's own timeout"
    )
    assert "taking longer than expected" in result.message.content


@pytest.mark.asyncio
async def test_general_plugin_tool_loop_never_exceeds_webhook_budget(monkeypatch):
    """GeneralPlugin's tool loop chains up to MAX_TOOL_ROUNDS+1 LLM calls per
    pass (each individually bounded to LLM_REQUEST_TIMEOUT_SECONDS=30s) and
    can run two full passes (the #42/#43 URL-guard retry) -- discovered via
    this exact test to have no outer bound of its own, exactly the shape
    that took down whiteboard. Force the model to keep calling a tool every
    round (worst case: MAX_TOOL_ROUNDS rounds), each LLM call sleeping right
    at its real ceiling, scaled down 100x, and confirm the wrapped call
    still fails fast instead of approaching the webhook's own budget."""
    import orchestrator.router as router_module
    from orchestrator.router import GeneralPlugin

    SCALE = 100.0  # real: up to 4 LLM calls x 30s = 120s vs 45s webhook ceiling
    monkeypatch.setattr(router_module, "GENERAL_TOOL_LOOP_TIMEOUT_SECONDS", 35.0 / SCALE)
    monkeypatch.setattr(router_module.settings, "gemini_api_key", "fake-key-for-test")

    class _SlowAlwaysToolCallingLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            await asyncio.sleep(30.0 / SCALE)  # right at LLM_REQUEST_TIMEOUT_SECONDS
            # Always requests another tool call -- forces every round to run,
            # the true worst case rather than the typical 1-round happy path.
            return AIMessage(content="", tool_calls=[{
                "name": "search_web",
                "args": {"query": "test"},
                "id": "call_x",
                "type": "tool_call",
            }])

    async def fast_search_web(*a, **k):
        return "Summary: fine"

    import capabilities.general.tools as general_tools

    class _FastSearchTool:
        name = "search_web"

        async def ainvoke(self, args):
            return "Summary: fine"

    monkeypatch.setattr(general_tools, "search_web", _FastSearchTool())
    monkeypatch.setattr(router_module, "get_agent_llm", lambda *a, **k: _SlowAlwaysToolCallingLLM())

    plugin = GeneralPlugin()
    state = {
        "user_id": 9202,
        "messages": [HumanMessage(content="what's new in the news today")],
    }

    started = time.monotonic()
    result = await plugin.execute(state)
    elapsed = time.monotonic() - started

    assert elapsed < WEBHOOK_CEILING_SECONDS / SCALE, (
        f"GeneralPlugin's tool loop took {elapsed:.2f}s (scaled) -- must fail fast "
        "at its own bound rather than approach the webhook's own timeout"
    )
    # A timeout here falls into the existing broad except-clause, which uses
    # the same rule-based fallback as a missing API key -- still a real reply,
    # not a hang.
    assert result.message.content


@pytest.mark.asyncio
async def test_route_plugin_journey_never_exceeds_webhook_budget(monkeypatch):
    """RoutePlugin.execute() chains extract_route_request (LLM, individually
    bounded) into plan_transit_journey, which itself makes a Google Maps
    Directions call PLUS one live LTA arrivals lookup per transit leg --
    each individually bounded, but nothing bounded their SUM before this fix
    (live incident: repeated webhook-level "Still working on that" replies).
    Mock plan_transit_journey to sleep right at the real aggregate ceiling
    (Maps ~30s + one LTA leg ~15s = 45s vs the 45s webhook ceiling), scaled
    down 100x, and confirm the wrapped call still fails fast instead of
    approaching the webhook's own timeout."""
    import orchestrator.router as router_module
    from orchestrator.router import RoutePlugin

    SCALE = 100.0  # real: Maps ~30s + one LTA leg ~15s = 45s vs 45s webhook ceiling
    monkeypatch.setattr(router_module, "ROUTE_RESOLUTION_TIMEOUT_SECONDS", 35.0 / SCALE)

    async def fake_extract(**kwargs):
        return {"origin": "Raffles Place", "destination": "Changi Airport", "mode": "transit"}

    async def slow_journey(origin, destination):
        # Stands in for _directions' own ~30s ceiling PLUS one transit leg's
        # _live_minutes_for_stop call (~15s) -- individually each fits its
        # own bound, but their sum (45s) exceeds ROUTE_RESOLUTION_TIMEOUT_SECONDS
        # (35s), exactly the bug: nothing bounded the sum before this fix.
        await asyncio.sleep(45.0 / SCALE)
        return {"error": "should never get here"}

    monkeypatch.setattr(router_module.extract_route_request, "coroutine", fake_extract)
    monkeypatch.setattr(router_module, "plan_transit_journey", slow_journey)

    plugin = RoutePlugin()
    state = {
        "user_id": 9204,
        "messages": [HumanMessage(content="route from Raffles Place to Changi Airport")],
    }

    started = time.monotonic()
    result = await plugin.execute(state)
    elapsed = time.monotonic() - started

    assert elapsed < WEBHOOK_CEILING_SECONDS / SCALE, (
        f"route resolution took {elapsed:.2f}s (scaled) -- must fail fast at its own "
        "bound rather than approach the webhook's own timeout"
    )
    assert "taking longer than expected" in result.message.content


@pytest.mark.asyncio
async def test_self_diagnostic_explanation_never_exceeds_webhook_budget(monkeypatch):
    """explain_last_turn() makes one LLM call; SELF_DIAGNOSTIC_TIMEOUT_SECONDS
    wraps it at the plan_dispatch() call site (not inside explain_last_turn
    itself). Confirm plan_dispatch's wrapper actually holds when the LLM call
    runs right at its real ceiling."""
    from unittest.mock import AsyncMock, patch

    import orchestrator.plan_router as plan_router_module
    from orchestrator.plan_router import plan_dispatch
    from orchestrator.planner import CapabilitySelection, Decision
    from orchestrator.router import PluginOutput

    SCALE = 100.0  # real: SELF_DIAGNOSTIC_TIMEOUT_SECONDS=20s vs 45s webhook ceiling
    monkeypatch.setattr(plan_router_module, "SELF_DIAGNOSTIC_TIMEOUT_SECONDS", 20.0 / SCALE)

    async def slow_explain(state):
        await asyncio.sleep(30.0 / SCALE)  # right at the LLM call's real ceiling
        return "should never get here"

    fake_plugin = AsyncMock()
    fake_plugin.execute.return_value = PluginOutput(message=AIMessage(content="normal fallback reply"))
    fallback_decision = Decision(
        capabilities=[CapabilitySelection(id="general", reason="fallback", confidence=0.6)],
        ordering=["general"],
        confidence=0.6,
        source="test",
    )

    state = {
        "user_id": 9203,
        "active_domain": None,
        "last_decision": {"ordering": ["general"]},
        "messages": [HumanMessage(content="why is this happening")],
    }

    started = time.monotonic()
    with patch("orchestrator.self_diagnostics.explain_last_turn", AsyncMock(side_effect=slow_explain)), \
            patch("orchestrator.planner.plan_with_llm", new=AsyncMock(return_value=fallback_decision)), \
            patch("orchestrator.router.CAPABILITY_REGISTRY", {"general": fake_plugin}):
        command = await plan_dispatch(state)
    elapsed = time.monotonic() - started

    assert elapsed < WEBHOOK_CEILING_SECONDS / SCALE, (
        f"self-diagnosis took {elapsed:.2f}s (scaled) -- must fall through to normal "
        "routing at its own bound rather than approach the webhook's own timeout"
    )
    # Falls through to normal routing (no capabilities registered here -> the
    # generic "couldn't work out what to do" reply), not a self-diagnostic answer.
    assert command.update["intent_type"] != "self_diagnostic"
