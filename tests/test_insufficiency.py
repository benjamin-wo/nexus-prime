import pytest
from langchain_core.messages import HumanMessage
from unittest.mock import AsyncMock, patch

from orchestrator.insufficiency import classify_insufficiency, insufficiency_message
from orchestrator.planner import deterministic_plan


def _state(message: str):
    return {"user_id": 1, "active_domain": None, "last_decision": None, "messages": [HumanMessage(content=message)]}


def test_c5_probe1_insufficiency_reachable_without_tool_call():
    decision = deterministic_plan("book a table for two at 7", _state("book a table for two at 7"), None)
    assert decision.insufficient is not None
    assert "restaurant_booking" in decision.insufficient.missing_capabilities
    assert decision.capabilities == []


@pytest.mark.asyncio
async def test_c5_probe1_no_plugin_executes_on_pure_refusal():
    from orchestrator.plan_router import plan_dispatch

    with patch("orchestrator.router.CAPABILITY_REGISTRY") as registry:
        command = await plan_dispatch(_state("book a table for two at 7"))
    registry.__getitem__.assert_not_called()
    registry.__getitem__.side_effect = AssertionError("plugin accessed on pure refusal")
    reply = str(command.update["messages"][-1].content)
    assert reply.startswith("I can't")
    assert "Nothing was changed" in reply


def test_c5_probe2_messages_visibly_different():
    no_integration = insufficiency_message("no_integration", ["calendar"])
    needs_human = insufficiency_message("needs_human", ["bank_transfer"])
    assert no_integration != needs_human
    assert "no integration exists" in no_integration
    assert "without a human" in needs_human
    assert "Nothing was sent or changed" in needs_human
    assert classify_insufficiency(["calendar"]) == "no_integration"
    assert classify_insufficiency(["bank_transfer"]) == "needs_human"


@pytest.mark.asyncio
async def test_c5_probe3_gap_record_written_and_no_fake_confirmation():
    with patch("core.audit.log_capability_request", new=AsyncMock()) as mock_log:
        from orchestrator.plan_router import plan_dispatch

        command = await plan_dispatch(_state("transfer $100 to Alice"))
    mock_log.assert_awaited_once()
    args = mock_log.await_args
    assert args.kwargs["intent_type"] == "insufficient_capability"
    assert "bank_transfer" in args.kwargs["tags"]
    reply = str(command.update["messages"][-1].content)
    assert "done" not in reply.lower()
    assert "saved" not in reply.lower()
