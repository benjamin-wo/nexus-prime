"""fetch_url (#22): read a single user-supplied link via Tavily's /extract
endpoint, scoped exactly as agreed on the issue -- one URL, no crawling, no
following links, fetched content fenced as untrusted data. Tavily does the
actual fetch on its own infra, so we never resolve/connect to a user-pasted
URL ourselves (the SSRF concern raised on the issue)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from capabilities.general.tools import fetch_url
from core.config import settings


def _mock_client(payload):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    return mock_client_cls, mock_client


@pytest.mark.asyncio
async def test_fetch_url_rejects_non_http_scheme(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "test-tavily-key")
    result = await fetch_url.ainvoke({"url": "javascript:alert(1)"})
    assert "Only http:// or https://" in result


@pytest.mark.asyncio
async def test_fetch_url_reports_missing_api_key(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "")
    result = await fetch_url.ainvoke({"url": "https://example.com/page"})
    assert "TAVILY_API_KEY is not configured" in result


@pytest.mark.asyncio
async def test_fetch_url_returns_extracted_content_fenced_as_untrusted(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "test-tavily-key")
    payload = {
        "results": [
            {
                "url": "https://example.com/merchants",
                "raw_content": "Participating shops: Katong Bakery, Joo Chiat Cafe.",
            }
        ],
        "failed_results": [],
    }
    mock_client_cls, mock_client = _mock_client(payload)

    with patch("capabilities.general.tools.httpx.AsyncClient", mock_client_cls):
        result = await fetch_url.ainvoke({"url": "https://example.com/merchants"})

    assert "Katong Bakery" in result
    assert "untrusted external page text" in result
    posted_url, posted_kwargs = mock_client.post.call_args
    assert posted_url[0] == "https://api.tavily.com/extract"
    assert posted_kwargs["json"]["urls"] == ["https://example.com/merchants"]


@pytest.mark.asyncio
async def test_fetch_url_reports_extraction_failure(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "test-tavily-key")
    payload = {
        "results": [],
        "failed_results": [{"url": "https://example.com/dead", "error": "timeout"}],
    }
    mock_client_cls, _ = _mock_client(payload)

    with patch("capabilities.general.tools.httpx.AsyncClient", mock_client_cls):
        result = await fetch_url.ainvoke({"url": "https://example.com/dead"})

    assert "Could not read" in result
    assert "timeout" in result


@pytest.mark.asyncio
async def test_fetch_url_truncates_long_content(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "test-tavily-key")
    long_text = "x" * 5000
    payload = {"results": [{"raw_content": long_text}], "failed_results": []}
    mock_client_cls, _ = _mock_client(payload)

    with patch("capabilities.general.tools.httpx.AsyncClient", mock_client_cls):
        result = await fetch_url.ainvoke({"url": "https://example.com/long"})

    assert "[truncated]" in result
    assert len(result) < len(long_text) + 200


@pytest.mark.asyncio
async def test_general_plugin_binds_fetch_url_alongside_search_web():
    """The agent's tool roster must include fetch_url, not just search_web --
    otherwise a user-pasted link still has nowhere to go even though the
    tool exists."""
    from orchestrator.agent_loop import _build_tool_roster, _visible_skills

    tool_names = {t.name for t in _build_tool_roster(_visible_skills(True))}
    assert "fetch_url" in tool_names
    assert "search_web" in tool_names
