import pytest
from langchain_core.messages import HumanMessage
from orchestrator.graph import get_assistant_graph

assistant_graph = get_assistant_graph()
from orchestrator.router import (
    CapabilityRouter,
    EmailPlugin,
    ExpensePlugin,
    RoutePlugin,
    RecipePlugin,
    GeneralPlugin,
)


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


@pytest.mark.asyncio
async def test_capability_plugins_direct_execution(monkeypatch):
    """Verify CapabilityPlugin standalone execution without LangGraph dependencies."""
    from unittest.mock import AsyncMock
    import capabilities.email.tools as email_tools
    import orchestrator.router as router_module
    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_token"))
    monkeypatch.setattr(email_tools.search_email_messages, "coroutine", AsyncMock(return_value=[{"sender": "Starbucks", "subject": "Receipt", "snippet": "$5.50"}]))

    state = {
        "messages": [HumanMessage(content="Check gmail")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    }
    email_plugin = EmailPlugin()
    out = await email_plugin.execute(state)
    assert out.state_update["active_domain"] == "email"
    assert "Starbucks" in str(out.message.content)


@pytest.mark.asyncio
async def test_capability_router_direct_route_intent():
    router = CapabilityRouter()
    assert router.route_intent("check gmail inbox") == "email"
    assert router.route_intent("what is the eta driving") == "routes"
    assert router.route_intent("parse this pasta recipe") == "recipes"
    assert router.route_intent("how much spent at starbucks") == "expenses"
    assert router.route_intent("who is Albert Einstein") == "general"
