import pytest


def _build_body(**kwargs):
    from core.github_sync import _build_capability_gap_body

    base = {
        "tag": "calendar",
        "prompt": "Set up a meeting with Alice on Friday 3pm",
        "intent_type": "unsupported_transaction",
        "expectation": "Schedule, view or manage calendar events",
        "block_reason": "GuardrailPolicy classified the request as an unsupported transactional capability",
        "agent_reply": "This transactional capability is not yet supported",
        "channel": "telegram",
        "occurred_count": 1,
    }
    base.update(kwargs)
    return _build_capability_gap_body(**base)


def test_gap_body_includes_details():
    body = _build_body()
    assert "## 🪄 Feature Request / Capability Gap" in body
    assert "#calendar" in body
    assert "Set up a meeting with Alice on Friday 3pm" in body  # verbatim request
    assert "calendar events" in body.lower()                  # what it enables
    assert "Areas currently missing" in body                 # missing areas
    assert "Calendar integration" in body
    assert "not yet supported" in body                       # refusal / error
    assert "What the assistant told the user" in body       # agent reply
    assert "Suggested next steps" in body
    assert "telegram" in body


def test_gap_body_reports_implementation_state():
    body = _build_body()
    # The state checklist must reflect real repo facts: whiteboard exists, calendar doesn't
    assert "- [ ]" in body  # at least one missing layer checkbox
    assert "Manifest (capabilities/manifests/calendar.yaml)" in body
    assert "Plugin registered" in body
    assert "Domain tools module" in body


def test_gap_body_unknown_tag_gets_generic_guidance():
    body = _build_body(tag="crypto_portfolio")
    assert "crypto_portfolio" in body
    assert "What it enables" in body
    assert "read-only slice" in body


def test_gap_body_omits_optional_fields_when_absent():
    body = _build_body(expectation=None, agent_reply=None, block_reason=None)
    assert "Expected behaviour" not in body
    assert "told the user" not in body
    assert "assistant" not in body.lower() or "telegram" not in body  # sanity: no reply block
    # No reply block header
    assert "What the assistant told the user" not in body


@pytest.mark.asyncio
async def test_gap_sync_posts_detailed_ticket(monkeypatch):
    """Creating a ticket sends the fully detailed body."""
    import os
    import core.github_sync as gs

    os.environ["GITHUB_TOKEN"] = "tok42"
    os.environ["GITHUB_REPO"] = "acme/repo"

    captured = {}

    class FakeResp:
        def __init__(self, data, status=200):
            self._data, self.status_code = data, status
        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def get(self, url, headers=None, **kw):
            if "issues?labels=capability-gap" in url:
                return FakeResp([])
            return FakeResp({})
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["payload"] = json
            return FakeResp({"number": 42, "html_url": "https://github.com/acme/repo/issues/42"}, status=201)

    monkeypatch.setattr(gs.httpx, "AsyncClient", FakeClient)

    url = await gs.sync_capability_gap_to_github_issue(
        tag="calendar",
        prompt="Set up a meeting Friday 3pm",
        intent_type="unsupported_transaction",
        expectation="Create a calendar event",
        block_reason="No calendar plugin",
        agent_reply="not supported yet",
        channel="web",
    )
    assert url == "https://github.com/acme/repo/issues/42"
    payload = captured["payload"]
    assert payload["title"] == "[Wishlist] Missing Capability: #calendar"
    body = payload["body"]
    assert "Create a calendar event" in body
    assert "No calendar plugin" in body
    assert "not supported yet" in body
    assert "web" in body
    assert payload["labels"] == ["capability-gap", "enhancement", "wishlist"]

    del os.environ["GITHUB_TOKEN"]
    del os.environ["GITHUB_REPO"]


@pytest.mark.asyncio
async def test_gap_logging_gated_to_real_gaps(monkeypatch):
    """Only genuine gaps reach GitHub; leaderboard-only calls stay local."""
    from core import audit as audit_mod
    from core.db import async_session_factory
    from core.models import CapabilityRequestLog
    from sqlmodel import select

    calls = []
    async def fake_sync(**kwargs):
        calls.append(kwargs)

    import core.github_sync as gs_mod
    monkeypatch.setattr(gs_mod, "sync_capability_gap_to_github_issue", fake_sync)

    # In-scope / informational_fallback => leaderboard only, no ticket
    await audit_mod.log_capability_request(
        user_id=9401,
        requested_task="spent 5 dollars",
        intent_type="in_scope",
        tags=["expenses"],
    )
    assert calls == []

    # Genuine gap => ticket with context
    await audit_mod.log_capability_request(
        user_id=9401,
        requested_task="transfer 50 to Alice",
        intent_type="unsupported_transaction",
        tags=["bank_transfer"],
        expectation="Send money via bank transfer",
        block_reason="Guardrail refusal",
        agent_reply="not supported yet",
        channel="telegram",
    )
    assert len(calls) == 1
    assert calls[0]["tag"] == "bank_transfer"
    assert calls[0]["expectation"] == "Send money via bank transfer"
    assert calls[0]["channel"] == "telegram"

    # New context columns persisted for the gap record
    async with async_session_factory() as session:
        from sqlmodel import select
        rows = (await session.execute(
            select(CapabilityRequestLog).where(CapabilityRequestLog.user_id == 9401)
        )).scalars().all()
        gap_row = next(r for r in rows if r.intent_type == "unsupported_transaction")
        assert gap_row.expectation == "Send money via bank transfer"
        assert gap_row.block_reason == "Guardrail refusal"
        assert gap_row.agent_reply == "not supported yet"
        assert gap_row.channel == "telegram"