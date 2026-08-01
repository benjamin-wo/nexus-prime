import pytest
from langchain_core.messages import HumanMessage
from orchestrator.graph import assistant_graph

@pytest.mark.asyncio
async def test_supervisor_routes_to_email_subagent():
    config = {"configurable": {"thread_id": "test_thread_1001"}}
    state = {
        "messages": [HumanMessage(content="Check my gmail inbox for receipts")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    }
    result = await assistant_graph.ainvoke(state, config=config)
    assert result.get("active_domain") == "email"
    assert len(result["messages"]) >= 2

@pytest.mark.asyncio
async def test_supervisor_routes_to_route_subagent():
    config = {"configurable": {"thread_id": "test_thread_1002"}}
    state = {
        "messages": [HumanMessage(content="What is the eta driving to office?")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    }
    result = await assistant_graph.ainvoke(state, config=config)
    assert result.get("active_domain") == "routes"
