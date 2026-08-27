import pytest
from langchain_core.messages import HumanMessage
from unittest.mock import AsyncMock, patch

from capabilities.bug_logging.tools import (
    _extract_bug_description,
    _guess_subsystem,
    _stable_fingerprint,
    log_user_bug,
)


def test_extract_bug_description_strips_framing():
    assert _extract_bug_description(
        "Can you log it as a bug. There is no icon for transaction splitting beside the edit icon."
    ) == "There is no icon for transaction splitting beside the edit icon."
    assert _extract_bug_description(
        "please log this as a bug: the dashboard is slow"
    ) == "the dashboard is slow"
    assert _extract_bug_description("There seems to be an issue with the cockpit") == (
        "There seems to be an issue with the cockpit"
    )


def test_guess_subsystem():
    assert _guess_subsystem("no icon for transaction splitting beside the edit icon") == "dashboard"
    assert _guess_subsystem("the telegram bot didn't reply") == "telegram"
    assert _guess_subsystem("the bus timing was wrong") == "routes"
    assert _guess_subsystem("something weird happened") == "general"


def test_stable_fingerprint_dedups():
    a = _stable_fingerprint("There is no icon for splitting  beside the edit icon")
    b = _stable_fingerprint("There is no icon for splitting beside the edit icon")
    c = _stable_fingerprint("completely different bug")
    assert a == b
    assert a != c


@pytest.mark.asyncio
async def test_log_user_bug_returns_issue_url():
    mock_result = {
        "url": "https://github.com/owner/repo/issues/88",
        "number": 88,
    }
    with patch(
        "core.audit.sync_production_bug_to_github_issue",
        new=AsyncMock(return_value=mock_result),
    ):
        result = await log_user_bug(
            user_id=1,
            description="no split icon next to edit",
            subsystem="dashboard",
        )
    assert result["logged"] is True
    assert result["github_issue_url"] == "https://github.com/owner/repo/issues/88"


@pytest.mark.asyncio
async def test_log_bug_report_tool_replies_with_url(monkeypatch):
    from capabilities.bug_logging.tools import log_bug_report

    monkeypatch.setattr(
        "capabilities.bug_logging.tools.log_user_bug",
        AsyncMock(
            return_value={
                "logged": True,
                "bug_id": 1,
                "github_issue_url": "https://github.com/owner/repo/issues/88",
                "github_issue_number": 88,
                "occurrence_count": 1,
            }
        ),
    )
    reply = await log_bug_report.ainvoke({
        "user_id": 1,
        "text": (
            "There seems to be an issue with the cockpit. There is no icon "
            "for transaction splitting beside the edit icon. Can you log it as a bug."
        ),
    })
    assert "issues/88" in reply
    assert "Logged as a bug" in reply