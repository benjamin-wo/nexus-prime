"""Web search's parts that need no database: the Tavily client, the checks that a
claim is really on its page, and how the free credits are shared out. Every page,
place and price here is made up."""

import json
from decimal import Decimal

import httpx
import pytest

from nexus.application.web_search import Product, WebSearchError, allowance
from nexus.domain.evidence import figures, has_figure, mentions, normalise
from nexus.infra.search.tavily import MAX_PAGE, TavilySearch, page_text

PAGE = (
    "# Where to stay in Exampleton\n\n"
    "![a photo](https://img.example.com/x.jpg)\n"
    "Stay in [Ōld Harbour](https://guide.example.com/old-harbour) for late food.\n"
    "<div>Rooms run 1,200 to 1,850 JPY a night, and about 8 000 JPY a day covers meals.</div>"
)


def test_names_are_matched_ignoring_case_accents_and_punctuation() -> None:
    assert normalise("Ōmoide-Yokochō!") == "omoide yokocho"
    assert mentions("Try the Old-Harbour area", "old harbour")
    assert mentions("Try the Old Harbour area", "The Old Harbour")
    # Whole words only, and nothing from nothing.
    assert not mentions("Old Harbourside", "Old Harbour")
    assert not mentions("anything", "a")


def test_figures_are_read_however_they_are_written() -> None:
    found = figures("1,200 to 1,850; 8 000 a day; about 15k; 3.5 stars; in 2026 100 people")
    assert {Decimal(1200), Decimal(1850), Decimal(8000), Decimal(15000), Decimal("3.5")} <= found
    assert Decimal(2026) in found and Decimal(100) in found
    assert Decimal(2026100) not in found  # two numbers, not one
    assert has_figure("from ¥99,999", Decimal("99999.00"))
    assert not has_figure("from ¥9,999", Decimal(99999))


def test_the_free_credits_are_shared_out_with_some_held_back() -> None:
    assert allowance(1000, Product.TRAVEL) == 570
    assert allowance(1000, Product.INVESTMENT) == 237
    assert allowance(1000, Product.GENERAL) == 142
    assert sum(allowance(1000, p) for p in Product) < 1000
    assert allowance(0, Product.TRAVEL) == 0


def test_page_text_is_plain_reading_text_and_capped() -> None:
    text = page_text(PAGE)
    assert "Stay in Ōld Harbour for late food." in text
    assert "img.example.com" not in text and "<div>" not in text and "](" not in text
    assert len(page_text("x" * (MAX_PAGE + 50))) == MAX_PAGE
    assert page_text(None) == ""


async def test_tavily_sends_only_the_question_and_returns_each_pages_text() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://guide.example.com/a", "title": "A guide", "raw_content": PAGE},
                    {
                        "url": "https://blog.example.com/b",
                        "title": "B",
                        "content": "Only a snippet.",
                    },
                    {"title": "No link"},
                    "junk",
                ],
                "usage": {"credits": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        got = await TavilySearch(http, "tvly-test").ask("  Where to stay\nin Exampleton?  ")
    (request,) = seen
    assert request.headers["Authorization"] == "Bearer tvly-test"
    assert "tvly-test" not in str(request.url)
    assert json.loads(request.content) == {
        "query": "Where to stay in Exampleton?",
        "search_depth": "basic",
        "max_results": 5,
        "include_raw_content": "markdown",
        "include_answer": False,
        "include_usage": True,
    }
    assert got.sources == [
        ("https://guide.example.com/a", "A guide"),
        ("https://blog.example.com/b", "B"),
    ]
    assert "1,200 to 1,850 JPY" in got.pages[0] and got.pages[1] == "Only a snippet."
    assert (got.text, got.usd, got.credits, got.provider) == ("", Decimal(0), 1, "tavily")


@pytest.mark.parametrize(
    ("status", "message"),
    [(432, "out of search credits"), (433, "out of search credits"), (500, "HTTP 500")],
)
async def test_tavily_failures_are_reported_without_detail(status: int, message: str) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json={"detail": "key"}))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(WebSearchError, match=f"^{message}$"):
            await TavilySearch(http, "tvly-test").ask("anything")


async def test_tavily_garbage_is_an_error_not_a_guess() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>"))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(WebSearchError, match="unexpected response"):
            await TavilySearch(http, "tvly-test").ask("anything")
