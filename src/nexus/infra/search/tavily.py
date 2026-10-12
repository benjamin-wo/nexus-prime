"""Web search through Tavily: one question in, the top results with each page's text.
And reading pages by address (its extract endpoint), for news articles.

A basic search costs one credit and returns each page's main text in the same call,
so nothing is fetched from the pages by Nexus itself. A basic extract costs one
credit for every five pages it reads; a page it can't read costs nothing. Only the
question or the addresses are sent: never anything of the user's. What comes back
is someone else's text, which the caller treats as data and checks in code.
"""

import logging
import math
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import httpx

from nexus.application.web_search import ReadPages, WebAnswer, WebSearchError

log = logging.getLogger(__name__)

URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
MAX_RESULTS = 5
MAX_QUESTION = 400
# Tavily reads at most this many addresses a call.
MAX_URLS = 20
# A page's text is kept up to this long: enough for an article, not a whole site.
MAX_PAGE = 20_000

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TAG = re.compile(r"<[^>]{1,200}>")
_BLANK_LINES = re.compile(r"\n{3,}")


def page_text(raw: object) -> str:
    """A page's markdown as plain reading text: images and tags dropped, links kept as
    their words, capped."""
    if not isinstance(raw, str):
        return ""
    text = _TAG.sub(" ", _LINK.sub(r"\1", _IMAGE.sub(" ", raw)))
    text = _BLANK_LINES.sub("\n\n", "\n".join(line.strip() for line in text.splitlines()))
    return text.strip()[:MAX_PAGE]


async def _call(
    http: httpx.AsyncClient, key: str, url: str, body: dict[str, Any]
) -> tuple[dict[str, Any], list[Any]]:
    """Tavily's answer and its results, or a ``WebSearchError`` saying what went wrong."""
    try:
        response = await http.post(
            url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=30.0
        )
    except httpx.HTTPError as exc:
        raise WebSearchError(f"request failed: {type(exc).__name__}") from exc
    if response.status_code in (432, 433):
        raise WebSearchError("out of search credits")
    if response.status_code != 200:
        raise WebSearchError(f"HTTP {response.status_code}")
    try:
        data: dict[str, Any] = response.json()
        results = data["results"]
    except (ValueError, KeyError, TypeError) as exc:
        raise WebSearchError("unexpected response") from exc
    return data, results if isinstance(results, list) else []


def _credits(data: dict[str, Any], otherwise: int) -> int:
    usage = data.get("usage")
    credits = usage.get("credits") if isinstance(usage, dict) else None
    return credits if isinstance(credits, int) and credits >= 0 else otherwise


class TavilySearch:
    def __init__(
        self, http: httpx.AsyncClient, api_key: str, *, max_results: int = MAX_RESULTS
    ) -> None:
        self._http = http
        self._key = api_key
        self._max = max_results

    async def ask(self, question: str) -> WebAnswer:
        body = {
            "query": " ".join(question.split())[:MAX_QUESTION],
            "search_depth": "basic",  # one credit; "advanced" is two
            "max_results": self._max,
            "include_raw_content": "markdown",
            "include_answer": False,
            "include_usage": True,
        }
        data, results = await _call(self._http, self._key, URL, body)
        sources: list[tuple[str, str]] = []
        pages: list[str] = []
        for result in results:
            if not isinstance(result, dict) or not isinstance(result.get("url"), str):
                continue
            sources.append((result["url"], str(result.get("title") or "")))
            pages.append(page_text(result.get("raw_content")) or page_text(result.get("content")))
        return WebAnswer("", sources, Decimal(0), pages, _credits(data, 1), "tavily")


class TavilyReader:
    def __init__(self, http: httpx.AsyncClient, api_key: str) -> None:
        self._http = http
        self._key = api_key

    async def read(self, urls: Sequence[str]) -> ReadPages:
        wanted = list(dict.fromkeys(urls))[:MAX_URLS]
        if not wanted:
            return ReadPages({})
        body = {
            "urls": wanted,
            "extract_depth": "basic",  # one credit per five pages; "advanced" is two
            "format": "markdown",
            "include_images": False,
            "include_usage": True,
        }
        data, results = await _call(self._http, self._key, EXTRACT_URL, body)
        asked = set(wanted)
        pages: dict[str, str] = {}
        for result in results:
            if not isinstance(result, dict) or result.get("url") not in asked:
                continue  # only what was asked for
            text = page_text(result.get("raw_content"))
            if text:
                pages[result["url"]] = text
        return ReadPages(pages, _credits(data, math.ceil(len(pages) / 5)))
