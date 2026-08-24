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
async def test_email_plugin_proceeds_when_any_provider_connected(monkeypatch):
    """A configured-but-unconnected Outlook must not block email search when Gmail is connected."""
    from unittest.mock import AsyncMock
    import orchestrator.router as router_module
    import capabilities.email.tools as email_tools

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_token"))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value=None))
    monkeypatch.setattr(router_module.settings, "microsoft_client_id", "mock-ms-client-id")
    monkeypatch.setattr(router_module.settings, "microsoft_client_secret", "mock-ms-secret")
    monkeypatch.setattr(
        email_tools.search_email_messages,
        "coroutine",
        AsyncMock(
            return_value=[
                {"sender": "Starbucks", "subject": "Receipt", "snippet": "$5.50"}
            ]
        ),
    )

    state = {
        "messages": [HumanMessage(content="Check my email for receipts")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    }
    out = await EmailPlugin().execute(state)
    assert out.state_update["active_domain"] == "email"
    assert "Starbucks" in str(out.message.content)


@pytest.mark.asyncio
async def test_email_plugin_offers_explicit_outlook_connection(monkeypatch):
    """An explicit Outlook onboarding request must return the Outlook OAuth link."""
    from unittest.mock import AsyncMock
    import orchestrator.router as router_module

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value=None))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value=None))
    monkeypatch.setattr(router_module.settings, "google_client_id", "google-id")
    monkeypatch.setattr(router_module.settings, "google_client_secret", "google-secret")
    monkeypatch.setattr(router_module.settings, "microsoft_client_id", "microsoft-id")
    monkeypatch.setattr(router_module.settings, "microsoft_client_secret", "microsoft-secret")

    out = await EmailPlugin().execute({
        "messages": [HumanMessage(content="Connect to my Outlook email")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    })
    reply = str(out.message.content)
    assert "/auth/outlook?user_id=4001" in reply
    assert "/auth/gmail" not in reply


def test_email_connection_intent_is_not_a_missing_capability():
    from orchestrator.planner import is_email_connection_request

    assert is_email_connection_request("Connect to my Outlook email") is True
    assert is_email_connection_request("link my Gmail") is True
    assert is_email_connection_request("Check my Outlook inbox") is False


def test_latest_email_intent_detection():
    from orchestrator.planner import is_latest_email_request, is_financial_email_request

    assert is_latest_email_request("check my latest email") is True
    assert is_latest_email_request("show me my newest emails") is True
    assert is_latest_email_request("what's the most recent mail I got?") is True
    assert is_latest_email_request("check my inbox for receipts") is False
    assert is_latest_email_request("check my email for transactions") is False
    assert is_latest_email_request("connect my outlook") is False

    # Financial-intent emails must keep using the keyword sweep.
    assert is_financial_email_request("check my inbox for receipts") is True
    assert is_financial_email_request("find my paypal statements") is True
    assert is_financial_email_request("did you see the DBS email today") is False
    assert is_financial_email_request("check my latest email") is False


@pytest.mark.asyncio
async def test_email_plugin_latest_request_skips_expense_logging(monkeypatch):
    """'check my latest email' must fetch newest messages and NOT auto-log expenses."""
    from unittest.mock import AsyncMock
    import orchestrator.router as router_module
    import capabilities.email.tools as email_tools

    captured: dict = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return [{
            "sender": "Alice <alice@example.com>",
            "subject": "Catchup",
            "date": "2026-08-24T09:00:00Z",
        }]

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_token"))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value=None))
    monkeypatch.setattr(email_tools.search_email_messages, "coroutine", fake_search)
    log_spy = AsyncMock(return_value={"logged": [], "skipped": [], "deduped": []})
    monkeypatch.setattr(router_module, "log_expenses_from_emails", log_spy)

    out = await EmailPlugin().execute({
        "messages": [HumanMessage(content="check my latest email")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    })
    assert captured.get("latest") is True
    assert log_spy.await_count == 0
    assert "Catchup" in str(out.message.content)


@pytest.mark.asyncio
async def test_email_plugin_generic_inbox_ask_uses_latest_mode(monkeypatch):
    """Conversational phrasing like 'did you see the DBS email today' must use latest mode."""
    from unittest.mock import AsyncMock
    import orchestrator.router as router_module
    import capabilities.email.tools as email_tools

    captured: dict = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return [{
            "sender": "DBS <alerts@dbs.com>",
            "subject": "Ibanking one-time password",
            "date": "2026-08-24T10:00:00Z",
        }]

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_token"))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value=None))
    monkeypatch.setattr(email_tools.search_email_messages, "coroutine", fake_search)

    out = await EmailPlugin().execute({
        "messages": [HumanMessage(content="did you see the DBS email today")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    })
    assert captured.get("latest") is True
    assert "DBS" in str(out.message.content)


@pytest.mark.asyncio
async def test_email_plugin_summary_prompt_carries_the_user_question(monkeypatch):
    """Regression (#26): the "latest" summarizer's LLM prompt was hardcoded to a
    generic "summarize conversationally" instruction and never received the
    user's actual message — so a specific question like "did I book a flight"
    got a generic inbox dump instead of an answer, even when the answer was
    present in the fetched emails."""
    from unittest.mock import AsyncMock
    from langchain_core.messages import AIMessage
    import orchestrator.router as router_module
    import capabilities.email.tools as email_tools

    async def fake_search(**kwargs):
        return [{
            "sender": "OCBC <alerts@ocbc.com>",
            "subject": "Funds transfer confirmation",
            "date": "2026-08-24T10:00:00Z",
        }]

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_token"))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value=None))
    monkeypatch.setattr(email_tools.search_email_messages, "coroutine", fake_search)
    monkeypatch.setattr(router_module.settings, "gemini_api_key", "fake-key-for-test")

    captured: dict = {}

    class _CapturingLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="No flight booking email found in your inbox.")

    monkeypatch.setattr(router_module, "get_agent_llm", lambda *a, **k: _CapturingLLM())

    question = "Did I book a flight on 24 Jul? Check my outlook"
    out = await EmailPlugin().execute({
        "messages": [HumanMessage(content=question)],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    })

    system_prompt = str(captured["messages"][0].content)
    assert question in system_prompt
    assert "answer THAT question directly" in system_prompt
    assert "No flight booking email found" in str(out.message.content)


@pytest.mark.asyncio
async def test_email_plugin_scopes_financial_sweep_to_named_provider(monkeypatch):
    """Regression: "look for transactions from my outlook ... log them as expenses"
    used to search ALL connected providers merged together, silently ignoring the
    explicit 'outlook' instruction — a user with Gmail also connected got Gmail's
    unrelated inbox summarized back with no indication Outlook was ever queried,
    and nothing got logged despite an explicit expense-logging request."""
    from unittest.mock import AsyncMock
    import orchestrator.router as router_module
    import capabilities.email.tools as email_tools

    captured: dict = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_gmail_token"))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value="mock_outlook_token"))
    monkeypatch.setattr(email_tools.search_email_messages, "coroutine", fake_search)

    await EmailPlugin().execute({
        "messages": [HumanMessage(
            content="Can you look for all transactions from my outlook for the past two days and log them as expenses"
        )],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    })
    assert captured.get("provider") == "outlook"


@pytest.mark.asyncio
async def test_email_plugin_scopes_latest_mode_to_named_gmail(monkeypatch):
    """Symmetric case on the latest-mode call site: naming Gmail explicitly
    must scope the search to Gmail, not merge in Outlook too."""
    from unittest.mock import AsyncMock
    import orchestrator.router as router_module
    import capabilities.email.tools as email_tools

    captured: dict = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_gmail_token"))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value="mock_outlook_token"))
    monkeypatch.setattr(email_tools.search_email_messages, "coroutine", fake_search)

    await EmailPlugin().execute({
        "messages": [HumanMessage(content="what's new in my gmail")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    })
    assert captured.get("provider") == "gmail"
    assert captured.get("latest") is True


@pytest.mark.asyncio
async def test_email_plugin_no_provider_scope_when_unnamed(monkeypatch):
    """When the user doesn't name a specific provider, keep searching every
    connected mailbox (existing behavior must not regress)."""
    from unittest.mock import AsyncMock
    import orchestrator.router as router_module
    import capabilities.email.tools as email_tools

    captured: dict = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_gmail_token"))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value="mock_outlook_token"))
    monkeypatch.setattr(email_tools.search_email_messages, "coroutine", fake_search)

    await EmailPlugin().execute({
        "messages": [HumanMessage(content="any new transactions I should know about?")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    })
    assert captured.get("provider") is None


@pytest.mark.asyncio
async def test_email_plugin_financial_ask_keeps_sweep_mode(monkeypatch):
    """Explicit financial intents ('receipts') must stay on the keyword sweep (latest=False)."""
    from unittest.mock import AsyncMock
    import orchestrator.router as router_module
    import capabilities.email.tools as email_tools

    captured: dict = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return [{
            "sender": "Amazon <auto-confirm@amazon.com>",
            "subject": "Payment receipt",
            "date": "2026-08-20T10:00:00Z",
        }]

    monkeypatch.setattr(router_module, "get_user_gmail_token", AsyncMock(return_value="mock_token"))
    monkeypatch.setattr(router_module, "get_user_outlook_token", AsyncMock(return_value=None))
    monkeypatch.setattr(email_tools.search_email_messages, "coroutine", fake_search)
    from capabilities.expenses.tools import log_expenses_from_emails
    monkeypatch.setattr(
        log_expenses_from_emails,
        "coroutine",
        AsyncMock(return_value={"logged": [], "skipped": [], "deduped": []}),
    )

    out = await EmailPlugin().execute({
        "messages": [HumanMessage(content="check my inbox for receipts")],
        "user_id": 4001,
        "current_timezone": "UTC",
        "active_domain": None,
    })
    assert captured.get("latest") is False
    assert "Amazon" in str(out.message.content)


@pytest.mark.asyncio
async def test_email_summary_prompt_guards_against_fabrication(monkeypatch):
    """The summary system prompt must forbid inventing emails not in the JSON."""
    import orchestrator.router as router_module

    captured: dict = {}

    class FakeSettings:
        has_llm_key = True

    class FakeLLM:
        async def ainvoke(self, messages):
            captured["system"] = str(messages[0].content or "")
            return type("Resp", (), {"content": "Two messages: Alice and Bob."})()

    monkeypatch.setattr(router_module, "settings", FakeSettings())
    monkeypatch.setattr(router_module, "get_agent_llm", lambda *a, **k: FakeLLM())

    summary = await EmailPlugin._summarize_email_results([
        {"sender": "Alice <alice@example.com>", "subject": "Catchup", "date": "2026-08-24T09:00:00Z"},
        {"sender": "Bob <bob@example.com>", "subject": "Lunch", "date": "2026-08-23T09:00:00Z"},
    ])
    assert "never invent" in captured["system"].lower()
    assert "Alice" in summary and "Bob" in summary


@pytest.mark.asyncio
async def test_capability_router_direct_route_intent():
    router = CapabilityRouter()
    assert router.route_intent("check gmail inbox") == "email"
    assert router.route_intent("what is the eta driving") == "routes"
    assert router.route_intent("parse this pasta recipe") == "recipes"
    assert router.route_intent("how much spent at starbucks") == "expenses"
    assert router.route_intent("who is Albert Einstein") == "general"
