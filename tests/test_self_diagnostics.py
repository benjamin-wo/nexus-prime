"""Self-diagnosis: "why is this happening"/"this is broken" style meta-
questions about the bot's own behavior get intercepted before normal
capability routing and answered from the bot's own last routing decision
plus live integration health, instead of being misrouted into a random
capability's own disambiguation flow (the exact failure class #48 fixed for
one specific capability)."""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from core.db import async_session_factory, init_db
from core.models import ProductionBugLog
from orchestrator.self_diagnostics import (
    check_integration_health,
    explain_last_turn,
    looks_like_self_diagnostic_question,
    recent_known_issues,
)


@pytest.fixture(autouse=True)
async def ensure_db():
    await init_db()


# --- looks_like_self_diagnostic_question ------------------------------------

@pytest.mark.parametrize("text", [
    "this is broken",
    "is it not working?",
    "why is this happening",
    "why did you do that",
    "why can't you do this",
    "what's wrong",
    "what went wrong",
    "can you troubleshoot this",
    "is something broken",
])
def test_matches_real_self_diagnostic_messages(text):
    assert looks_like_self_diagnostic_question(text) is True


@pytest.mark.parametrize("text", [
    "why is my flight not showing up",
    "what's happening this weekend in Bali",
    "add the hotel location to my board",
    "why did the bus arrive late",
    "spent $15 on lunch",
    "",
])
def test_does_not_misfire_on_domain_questions(text):
    assert looks_like_self_diagnostic_question(text) is False


# --- check_integration_health / recent_known_issues -------------------------

@pytest.mark.asyncio
async def test_check_integration_health_reports_configured_state(monkeypatch):
    from core.config import settings
    import capabilities.email.tools as email_tools

    monkeypatch.setattr(settings, "tavily_api_key", "real-tavily-key")
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    monkeypatch.setattr(settings, "lta_account_key", None)
    monkeypatch.setattr(email_tools, "get_user_gmail_token", lambda user_id: _async_return("gmail-token"))
    monkeypatch.setattr(email_tools, "get_user_outlook_token", lambda user_id: _async_return(None))

    health = await check_integration_health(user_id=8801)

    assert health["web_search_configured"] is True
    assert health["maps_configured"] is False
    assert health["transit_live_data_configured"] is False
    assert health["gmail_connected"] is True
    assert health["outlook_connected"] is False


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_recent_known_issues_returns_only_open_bugs_for_this_user():
    async with async_session_factory() as session:
        session.add(ProductionBugLog(
            fingerprint="fp_open_8802",
            title="Email search silently drops Outlook results",
            subsystem="email",
            user_id=8802,
            status="open",
            github_issue_url="https://github.com/benjamin-wo/nexus-prime/issues/999",
        ))
        session.add(ProductionBugLog(
            fingerprint="fp_resolved_8802",
            title="Resolved bug, should not show up",
            subsystem="email",
            user_id=8802,
            status="resolved",
        ))
        session.add(ProductionBugLog(
            fingerprint="fp_other_user",
            title="Someone else's bug",
            subsystem="routes",
            user_id=9999,
            status="open",
        ))
        await session.commit()

    issues = await recent_known_issues(user_id=8802)

    assert len(issues) == 1
    assert issues[0]["title"] == "Email search silently drops Outlook results"
    assert issues[0]["github_issue_url"] == "https://github.com/benjamin-wo/nexus-prime/issues/999"


# --- explain_last_turn -------------------------------------------------------

@pytest.mark.asyncio
async def test_explain_last_turn_returns_none_with_no_history():
    state = {"user_id": 8803, "last_decision": None, "messages": []}
    assert await explain_last_turn(state) is None


@pytest.mark.asyncio
async def test_explain_last_turn_grounds_reply_in_last_decision_and_health(monkeypatch):
    import orchestrator.self_diagnostics as sd

    monkeypatch.setattr(sd, "check_integration_health", lambda user_id: _async_return({
        "gmail_connected": False,
        "outlook_connected": False,
    }))
    monkeypatch.setattr(sd, "recent_known_issues", lambda user_id, limit=3: _async_return([]))

    captured = {}

    class _FakeLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="Your email isn't connected yet, that's why the search came up empty.")

    monkeypatch.setattr("core.llm.get_agent_llm", lambda *a, **k: _FakeLLM())

    state = {
        "user_id": 8804,
        "last_decision": {
            "capabilities": [{"id": "email", "reason": "user asked about their inbox", "confidence": 0.9}],
            "ordering": ["email"],
            "source": "llm",
        },
        "messages": [
            HumanMessage(content="check my email for flight bookings"),
            AIMessage(content="I couldn't find anything -- your mailbox isn't connected yet."),
            HumanMessage(content="why is this happening"),
        ],
    }
    result = await explain_last_turn(state)

    assert result == "Your email isn't connected yet, that's why the search came up empty."
    prompt_text = str(captured["messages"])
    assert "email" in prompt_text
    assert "gmail_connected" in prompt_text


@pytest.mark.asyncio
async def test_explain_last_turn_returns_none_when_llm_fails(monkeypatch):
    import orchestrator.self_diagnostics as sd

    monkeypatch.setattr(sd, "check_integration_health", lambda user_id: _async_return({}))
    monkeypatch.setattr(sd, "recent_known_issues", lambda user_id, limit=3: _async_return([]))

    class _BrokenLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("provider down")

    monkeypatch.setattr("core.llm.get_agent_llm", lambda *a, **k: _BrokenLLM())

    state = {
        "user_id": 8805,
        "last_decision": {"ordering": ["general"]},
        "messages": [HumanMessage(content="this is broken")],
    }
    assert await explain_last_turn(state) is None


# --- end-to-end via plan_dispatch --------------------------------------------

@pytest.mark.asyncio
async def test_plan_dispatch_intercepts_self_diagnostic_question(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from orchestrator.plan_router import plan_dispatch

    def _boom(*a, **k):
        raise AssertionError("normal capability planning must not run for a self-diagnostic question")

    monkeypatch.setattr(
        "orchestrator.self_diagnostics.explain_last_turn",
        AsyncMock(return_value="I misread your last message, sorry about that -- here's what actually happened."),
    )

    state = {
        "user_id": 8806,
        "active_domain": "email",
        "last_decision": {"ordering": ["email"]},
        "messages": [HumanMessage(content="why is this happening")],
    }
    with patch("orchestrator.planner.plan_with_llm", side_effect=_boom), \
            patch("orchestrator.planner.deterministic_plan", side_effect=_boom):
        command = await plan_dispatch(state)

    assert command.update["messages"][-1].content == (
        "I misread your last message, sorry about that -- here's what actually happened."
    )
    assert command.update["intent_type"] == "self_diagnostic"
    assert command.update["active_domain"] == "email"


@pytest.mark.asyncio
async def test_plan_dispatch_falls_through_to_normal_routing_when_nothing_to_explain(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from orchestrator.plan_router import plan_dispatch
    from orchestrator.planner import Decision, CapabilitySelection
    from orchestrator.router import PluginOutput

    monkeypatch.setattr(
        "orchestrator.self_diagnostics.explain_last_turn",
        AsyncMock(return_value=None),
    )

    fake_plugin = AsyncMock()
    fake_plugin.execute.return_value = PluginOutput(message=AIMessage(content="general reply"))
    decision = Decision(
        capabilities=[CapabilitySelection(id="general", reason="fallback", confidence=0.6)],
        ordering=["general"],
        confidence=0.6,
        source="test",
    )

    state = {
        "user_id": 8807,
        "active_domain": None,
        "last_decision": None,
        "messages": [HumanMessage(content="is something broken")],
    }
    with patch("orchestrator.router.CAPABILITY_REGISTRY", {"general": fake_plugin}), \
            patch("orchestrator.planner.plan_with_llm", new=AsyncMock(return_value=decision)):
        command = await plan_dispatch(state)

    fake_plugin.execute.assert_awaited_once()
    assert command.update["messages"][-1].content == "general reply"
