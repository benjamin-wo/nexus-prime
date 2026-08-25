import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from sqlmodel import select

from core.db import async_session_factory
from core.models import ProductionBugLog, UserProfile
from core.audit import (
    redact_sensitive_info,
    report_production_bug,
    report_user_filed_bug,
    perform_conversation_audit,
    record_operation_event,
)
from core.github_sync import sync_production_bug_to_github_issue


def test_redact_sensitive_info():
    raw_text = (
        "Error using token 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 "
        "with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz.abc "
        "and sk-1234567890abcdef1234567890abcdef "
        "password='supersecretpass123' and key=abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG="
    )
    redacted = redact_sensitive_info(raw_text)
    assert "123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11" not in redacted
    assert "[REDACTED_TELEGRAM_TOKEN]" in redacted
    assert "[REDACTED_BEARER_TOKEN]" in redacted
    assert "[REDACTED_API_KEY]" in redacted
    assert "[REDACTED_ENCRYPTION_KEY]" in redacted
    assert "supersecretpass123" not in redacted


@pytest.mark.asyncio
async def test_report_production_bug_creates_db_record_and_syncs():
    mock_triage = {
        "title": "Bus stop lookup failed on 4-digit codes",
        "subsystem": "routes",
        "severity": "P1",
        "root_cause": "Regex in lta.py expected 5 digits instead of 4-5 digits",
        "reproduction_context": "User asked 'bus 27 at 1012'",
        "suggested_fix": "Change regex to ^\\d{4,5}$",
        "fingerprint": "routes_lta_4digit_stop_code_error",
    }

    mock_gh_result = {
        "url": "https://github.com/owner/repo/issues/101",
        "number": 101,
    }

    with patch(
        "core.audit.sync_production_bug_to_github_issue",
        new=AsyncMock(return_value=mock_gh_result),
    ) as mock_sync:
        log_entry = await report_production_bug(
            user_id=777,
            thread_id="t777",
            error_context="ValueError: Invalid bus stop code 1012",
            mock_triage=mock_triage,
            detection_source="runtime_exception",
        )

    assert log_entry.id is not None
    assert log_entry.fingerprint == "routes_lta_4digit_stop_code_error"
    assert log_entry.severity == "P1"
    assert log_entry.subsystem == "routes"
    assert log_entry.github_issue_url == "https://github.com/owner/repo/issues/101"
    assert log_entry.github_issue_number == 101
    assert log_entry.occurrence_count == 1
    mock_sync.assert_called_once()

    # Test deduplication / increment recurrence on subsequent trigger
    with patch(
        "core.audit.sync_production_bug_to_github_issue",
        new=AsyncMock(return_value=mock_gh_result),
    ) as mock_sync_2:
        log_entry_2 = await report_production_bug(
            user_id=777,
            thread_id="t777",
            error_context="ValueError: Invalid bus stop code 1012",
            mock_triage=mock_triage,
            detection_source="runtime_exception",
        )

    assert log_entry_2.id == log_entry.id
    assert log_entry_2.occurrence_count == 2
    mock_sync_2.assert_called_once()


@pytest.mark.asyncio
async def test_sync_production_bug_to_github_issue_no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = await sync_production_bug_to_github_issue(
        fingerprint="test_fp_1",
        title="Test Bug",
    )
    assert result is None


@pytest.mark.asyncio
async def test_sync_production_bug_creates_new_github_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "dummy_token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    # Mock empty open issues list
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = []

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 201
    mock_post_resp.json.return_value = {
        "number": 88,
        "html_url": "https://github.com/owner/repo/issues/88",
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_get_resp
    mock_client.post.return_value = mock_post_resp

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    with patch("core.github_sync.httpx.AsyncClient", mock_client_cls):
        result = await sync_production_bug_to_github_issue(
            fingerprint="expense_ocr_timeout",
            title="Receipt OCR timed out on large image",
            severity="P2",
            subsystem="expenses",
            detection_source="conversation_audit",
            root_cause="LLM vision call exceeded 15s limit",
            suggested_fix="Increase timeout to 30s",
        )

    assert result == {"url": "https://github.com/owner/repo/issues/88", "number": 88}
    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    payload = kwargs.get("json", {})
    assert "[P2][Expenses] Receipt OCR timed out" in payload.get("title", "")
    assert "<!-- fingerprint: expense_ocr_timeout -->" in payload.get("body", "")
    assert "severity:p2" in payload.get("labels", [])
    assert "area:expenses" in payload.get("labels", [])


@pytest.mark.asyncio
async def test_sync_production_bug_deduplicates_existing_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "dummy_token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    # Mock existing open issue matching fingerprint
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = [
        {
            "number": 55,
            "title": "[P1][Routes] Bus Stop parse error",
            "body": "<!-- fingerprint: routes_lta_parse_err -->\nSome issue details",
        }
    ]

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 201
    mock_post_resp.json.return_value = {"id": 999}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_get_resp
    mock_client.post.return_value = mock_post_resp

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    with patch("core.github_sync.httpx.AsyncClient", mock_client_cls):
        result = await sync_production_bug_to_github_issue(
            fingerprint="routes_lta_parse_err",
            title="Bus Stop parse error",
            severity="P1",
            subsystem="routes",
            occurrence_count=3,
        )

    assert result == {"url": "https://github.com/owner/repo/issues/55", "number": 55}
    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert "/issues/55/comments" in args[0]
    comment_body = kwargs.get("json", {}).get("body", "")
    assert "Occurrence #3" in comment_body


@pytest.mark.asyncio
async def test_conversation_audit_triggers_bug_report_on_critical():
    messages = [
        HumanMessage(content="what bus goes to airport?"),
        AIMessage(content="take bus 9999 from nonexistent stop"),
    ]
    payload = {
        "faithfulness_score": 1,
        "routing_score": 2,
        "tool_correctness_score": 1,
        "helpfulness_score": 1,
        "verdict": "critical",
        "evidence": "Fabricated bus 9999 and stop.",
    }

    with patch("core.audit._judge_conversation_with_gemini", new=AsyncMock(return_value=payload)):
        with patch("core.audit.send_admin_anomaly_alert", new=AsyncMock()):
            with patch("core.audit.report_production_bug", new=AsyncMock()) as mock_report_bug:
                await perform_conversation_audit(
                    user_id=12345,
                    thread_id="t12345",
                    messages=messages,
                )
                mock_report_bug.assert_called_once()
                kwargs = mock_report_bug.call_args.kwargs
                assert kwargs["user_id"] == 12345
                assert kwargs["detection_source"] == "conversation_audit"
                assert "Fabricated bus 9999" in kwargs["error_context"]


@pytest.mark.asyncio
async def test_record_operation_event_creates_deduped_issue():
    """record_operation_event persists a ProductionBugLog row and dedups on re-run."""
    mock_gh_result = {"url": "https://github.com/owner/repo/issues/77", "number": 77}

    with patch(
        "core.audit.sync_production_bug_to_github_issue",
        new=AsyncMock(return_value=mock_gh_result),
    ) as mock_sync:
        first = await record_operation_event(
            subsystem="scheduler",
            error_context="db unreachable during sweep",
            detection_source="operations_health",
            fingerprint="db_unreachable",
            severity="P1",
        )
        second = await record_operation_event(
            subsystem="scheduler",
            error_context="db unreachable during sweep",
            detection_source="operations_health",
            fingerprint="db_unreachable",
            severity="P1",
        )

    assert first.id == second.id
    assert first.fingerprint == "db_unreachable"
    assert first.subsystem == "scheduler"
    assert first.severity == "P1"
    assert first.occurrence_count == 1
    assert second.occurrence_count == 2
    assert mock_sync.call_count == 2


@pytest.mark.asyncio
async def test_record_operation_event_deterministic_fingerprint_when_unspecified():
    """Without a fingerprint, identical operation events still deduplicate."""
    mock_gh_result = {"url": "https://github.com/owner/repo/issues/78", "number": 78}
    with patch(
        "core.audit.sync_production_bug_to_github_issue",
        new=AsyncMock(return_value=mock_gh_result),
    ):
        a = await record_operation_event(
            subsystem="email",
            error_context="outlook token refresh failed: invalid_grant",
            detection_source="runtime_exception",
        )
        b = await record_operation_event(
            subsystem="email",
            error_context="outlook token refresh failed: invalid_grant",
            detection_source="runtime_exception",
        )
    assert a.id == b.id


def test_health_sweep_records_missing_credential_probes(monkeypatch):
    """The operations health sweep records an issue when missing provider credentials."""
    import core.scheduler as sched_mod
    from core.config import settings

    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    monkeypatch.setattr(settings, "microsoft_client_id", None)
    monkeypatch.setattr(settings, "microsoft_client_secret", None)
    monkeypatch.setattr(settings, "telegram_bot_token", None)

    with patch(
        "core.audit.record_operation_event",
        new=AsyncMock(side_effect=lambda **kw: None),
    ) as mock_record:
        import asyncio

        asyncio.run(sched_mod._run_operations_health_sweep())

    fingerprints = {call.kwargs["fingerprint"] for call in mock_record.call_args_list}
    assert "env_missing_gmail_credentials" in fingerprints
    assert "env_missing_outlook_credentials" in fingerprints


def test_unhandled_exception_middleware_records_runtime_bug(monkeypatch):
    """fastapi exception handler funnels unhandled errors into the operation pipeline."""
    from fastapi.testclient import TestClient
    from app.main import app

    recorded = {}

    async def _fake_record(**kwargs):
        recorded.update(kwargs)

    import core.audit as audit_mod

    monkeypatch.setattr(audit_mod, "record_operation_event", _fake_record)

    with TestClient(app) as client:
        resp = client.get("/api/this-route-does-not-exist")
    # Unknown routes 404 via normal handling; the middleware only intercepts 5xx routes.
    # Exercise the handler directly to prove the funnel fires.
    from app.main import unhandled_exception_handler
    from fastapi import Request

    raw_exc = ValueError("boom")
    from unittest.mock import MagicMock

    req = MagicMock(spec=Request)
    req.url.path = "/api/dashboard/explode"
    req.method = "GET"
    import asyncio

    resp = asyncio.run(unhandled_exception_handler(req, raw_exc))
    assert recorded["subsystem"] == "api"
    assert "ValueError" in recorded.get("error_context", "")
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_report_user_filed_bug_creates_db_record_and_syncs():
    """#14: /file-issue triages with an LLM (mocked here) and files through the
    same persistence/GitHub-sync plumbing as automated production bugs, but
    tagged detection_source='user_reported' and gated with human-review-required."""
    mock_triage = {
        "title": "Split icon missing on cockpit",
        "category": "ui",
        "subsystem": "showcase",
        "priority": "P2",
        "summary": "User reports no split icon next to edit on the transaction row.",
        "fingerprint": "cockpit_missing_split_icon",
    }
    mock_gh_result = {"url": "https://github.com/owner/repo/issues/201", "number": 201}

    with patch(
        "core.audit.sync_production_bug_to_github_issue",
        new=AsyncMock(return_value=mock_gh_result),
    ) as mock_sync:
        log_entry = await report_user_filed_bug(
            user_id=555,
            description="There is no icon for transaction splitting beside the edit icon.",
            thread_id="t555",
            mock_triage=mock_triage,
        )

    assert log_entry.id is not None
    assert log_entry.fingerprint == "cockpit_missing_split_icon"
    assert log_entry.severity == "P2"
    assert log_entry.subsystem == "showcase"
    assert log_entry.detection_source == "user_reported"
    assert log_entry.user_id == 555
    assert log_entry.github_issue_url == "https://github.com/owner/repo/issues/201"
    assert log_entry.github_issue_number == 201
    assert log_entry.occurrence_count == 1

    mock_sync.assert_called_once()
    _, kwargs = mock_sync.call_args
    assert kwargs["detection_source"] == "user_reported"
    assert kwargs["extra_labels"] == ["human-review-required"]

    # A repeat report of the same bug dedups into a recurrence, not a new issue.
    with patch(
        "core.audit.sync_production_bug_to_github_issue",
        new=AsyncMock(return_value=mock_gh_result),
    ):
        log_entry_2 = await report_user_filed_bug(
            user_id=555,
            description="Still no split icon next to edit.",
            thread_id="t555",
            mock_triage=mock_triage,
        )
    assert log_entry_2.id == log_entry.id
    assert log_entry_2.occurrence_count == 2


@pytest.mark.asyncio
async def test_report_user_filed_bug_falls_back_when_triage_llm_fails():
    """LLM triage failure must not block filing -- fall back to a heuristic
    classification instead of dropping the user's report."""
    with patch(
        "core.audit._triage_user_report_with_gemini",
        new=AsyncMock(side_effect=RuntimeError("quota exceeded")),
    ):
        with patch(
            "core.audit.sync_production_bug_to_github_issue",
            new=AsyncMock(return_value=None),
        ):
            log_entry = await report_user_filed_bug(
                user_id=556,
                description="The dashboard chart is blank on load.",
                thread_id="t556",
            )

    assert log_entry.id is not None
    assert log_entry.detection_source == "user_reported"
    assert log_entry.severity == "P2"
    assert log_entry.subsystem == "general"


@pytest.mark.asyncio
async def test_sync_production_bug_user_reported_gets_distinct_shape(monkeypatch):
    """#14: a /file-issue report must look different from an automated audit
    finding -- no fabricated 'Gemini Audit' framing or traceback, a
    `user-reported` label instead of `audit-detected`, plus the
    human-review-required gate label."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy_token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = []

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 201
    mock_post_resp.json.return_value = {
        "number": 202,
        "html_url": "https://github.com/owner/repo/issues/202",
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_get_resp
    mock_client.post.return_value = mock_post_resp

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    with patch("core.github_sync.httpx.AsyncClient", mock_client_cls):
        result = await sync_production_bug_to_github_issue(
            fingerprint="cockpit_missing_split_icon",
            title="Split icon missing on cockpit",
            severity="P2",
            subsystem="showcase",
            detection_source="user_reported",
            root_cause="User reports no split icon next to edit.",
            reproduction_context="There is no icon for transaction splitting beside the edit icon.",
            error_traceback="Traceback (most recent call last): boom",  # must never surface
            extra_labels=["human-review-required"],
        )

    assert result == {"url": "https://github.com/owner/repo/issues/202", "number": 202}
    args, kwargs = mock_client.post.call_args
    payload = kwargs.get("json", {})
    labels = payload.get("labels", [])
    assert "user-reported" in labels
    assert "human-review-required" in labels
    assert "audit-detected" not in labels

    body = payload.get("body", "")
    assert "User-Reported Bug" in body
    assert "filed via /file-issue" in body
    assert "Gemini 3.1 Pro Audit" not in body
    assert "Traceback (most recent call last)" not in body


@pytest.mark.asyncio
async def test_sync_production_bug_default_source_unaffected(monkeypatch):
    """Sanity guard: adding the user_reported shape must not change the
    default (automated audit) issue shape or labels."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy_token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = []

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 201
    mock_post_resp.json.return_value = {
        "number": 203,
        "html_url": "https://github.com/owner/repo/issues/203",
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_get_resp
    mock_client.post.return_value = mock_post_resp
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    with patch("core.github_sync.httpx.AsyncClient", mock_client_cls):
        await sync_production_bug_to_github_issue(
            fingerprint="routes_generic_error",
            title="Generic route error",
            severity="P2",
            subsystem="routes",
            detection_source="runtime_exception",
        )

    args, kwargs = mock_client.post.call_args
    payload = kwargs.get("json", {})
    labels = payload.get("labels", [])
    assert "audit-detected" in labels
    assert "user-reported" not in labels
    assert "human-review-required" not in labels
    assert "Gemini 3.1 Pro Audit" in payload.get("body", "")


@pytest.mark.asyncio
async def test_transcript_includes_tool_calls_for_judge_and_triage():
    from core.audit import _build_audit_transcript

    messages = [
        HumanMessage(content="next bus at stop 1012?"),
        ToolMessage(
            content="raw lta payload: {'service': '27', 'eta': '6 min'} token 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            tool_call_id="call_1",
            name="get_bus_arrival",
        ),
        AIMessage(content="Bus 27 arrives in 6 minutes."),
    ]

    transcript = _build_audit_transcript(messages)
    assert len(transcript) == 3
    tool_entry = transcript[1]
    assert tool_entry["role"] == "tool"
    assert tool_entry["tool_name"] == "get_bus_arrival"
    # Tool output is included for grounding, but secrets inside it are redacted
    assert "'27'" in tool_entry["content"]
    assert "123456789:ABC-DEF" not in tool_entry["content"]
    assert "[REDACTED_TELEGRAM_TOKEN]" in tool_entry["content"]

    # Triage path also receives the tool entry
    triage_payload_capture = {}

    async def _capture_triage(payload):
        triage_payload_capture.update(payload)
        return {
            "title": "Tool grounding failure",
            "subsystem": "routes",
            "severity": "P1",
            "root_cause": "Assistant ignored tool output",
            "reproduction_context": "bus query",
            "suggested_fix": "n/a",
            "fingerprint": "test_tool_grounding_fp",
        }

    with patch("core.audit.sync_production_bug_to_github_issue", new=AsyncMock(return_value=None)):
        with patch("core.audit._triage_bug_with_gemini", new=_capture_triage):
            await report_production_bug(
                user_id=1,
                thread_id="t1",
                error_context="audit failure",
                messages=messages,
                detection_source="conversation_audit",
            )
            roles = [entry["role"] for entry in triage_payload_capture["transcript"]]
            assert "tool" in roles
