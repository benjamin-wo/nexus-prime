"""Web search's parts that need no database: the Tavily client, the checks that a
claim is really on its page, and how the free credits are shared out. Every page,
place and price here is made up."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest

from nexus.application.web_search import (
    KEEP_FOR,
    KEEP_TODAY,
    KEEP_WEEK,
    MAX_MERGED,
    Product,
    Recency,
    WebAnswer,
    WebSearchError,
    allowance,
    keep_for,
    merge,
)
from nexus.domain.evidence import figures, has_figure, mentions, normalise
from nexus.domain.travel_research import published_note, sources_from
from nexus.infra.search.tavily import (
    MAX_PAGE,
    TavilyReader,
    TavilySearch,
    page_text,
    published_at,
)

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


async def test_tavily_reads_only_the_pages_asked_for() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://news.example.com/a", "raw_content": PAGE},
                    {"url": "https://other.example.com/x", "raw_content": "Not asked for."},
                    {"url": "https://news.example.com/b", "raw_content": ""},
                    "junk",
                ],
                "failed_results": [{"url": "https://news.example.com/c", "error": "blocked"}],
            },
        )

    urls = [
        "https://news.example.com/a",
        "https://news.example.com/b",
        "https://news.example.com/c",
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        reader = TavilyReader(http, "tvly-test")
        got = await reader.read([*urls, urls[0]])
        assert (await reader.read([])).pages == {}
    (request,) = seen  # nothing asked for, nothing sent
    assert str(request.url) == "https://api.tavily.com/extract"
    assert request.headers["Authorization"] == "Bearer tvly-test"
    assert json.loads(request.content) == {
        "urls": urls,
        "extract_depth": "basic",
        "format": "markdown",
        "include_images": False,
        "include_usage": True,
    }
    assert list(got.pages) == ["https://news.example.com/a"]
    assert "1,200 to 1,850 JPY" in got.pages["https://news.example.com/a"]
    # Without a usage count: one credit for every five pages read.
    assert got.credits == 1


async def test_tavily_reading_failures_are_errors() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(432, json={"detail": "key"}))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(WebSearchError, match=r"^out of search credits$"):
            await TavilyReader(http, "tvly-test").read(["https://news.example.com/a"])


async def _tavily_body(recent: Recency | None) -> dict[str, object]:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        await TavilySearch(http, "tvly-test").ask("protest Exampleton today", recent)
    body: dict[str, object] = json.loads(seen[0].content)
    return body


async def test_a_general_search_has_no_topic_or_time_range() -> None:
    body = await _tavily_body(None)
    assert "topic" not in body and "time_range" not in body and "days" not in body
    assert body["search_depth"] == "basic"


@pytest.mark.parametrize(("recent", "time_range"), [("today", "day"), ("week", "week")])
async def test_recent_searches_ask_the_news_topic_over_the_last_day_or_week(
    recent: Recency, time_range: str
) -> None:
    body = await _tavily_body(recent)
    assert (body["topic"], body["time_range"]) == ("news", time_range)
    # Still one basic search with each page's text.
    assert body["search_depth"] == "basic" and body["include_raw_content"] == "markdown"
    assert body["query"] == "protest Exampleton today"


async def test_news_results_carry_when_they_were_published() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://news.example.com/a",
                        "title": "A",
                        "content": "x",
                        "published_date": "Sat, 24 Oct 2026 15:40:00 GMT",
                    },
                    {"url": "https://news.example.com/b", "title": "B", "content": "y"},
                    {
                        "url": "https://news.example.com/c",
                        "title": "C",
                        "content": "z",
                        "published_date": "not a date",
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        got = await TavilySearch(http, "tvly-test").ask("strike", "today")
    assert got.published == [datetime(2026, 10, 24, 15, 40, tzinfo=UTC), None, None]
    assert len(got.published) == len(got.sources) == 3


def test_published_dates_are_read_in_either_format() -> None:
    want = datetime(2026, 10, 24, 15, 40, tzinfo=UTC)
    assert published_at("Sat, 24 Oct 2026 15:40:00 GMT") == want
    assert published_at("2026-10-24T15:40:00Z") == want
    assert published_at("2026-10-24T17:40:00+02:00") == want
    assert published_at("2026-10-24 15:40:00") == want  # no zone: UTC
    assert published_at("2026-10-24") == datetime(2026, 10, 24, tzinfo=UTC)
    for junk in ("", "  ", "yesterday", None, 5):
        assert published_at(junk) is None


def answer(
    name: str, urls: list[str], when: list[datetime | None] | None = None, credits: int = 1
) -> WebAnswer:
    return WebAnswer(
        "",
        [(u, f"{name} {i}") for i, u in enumerate(urls)],
        Decimal(0),
        [f"{name} page {i}" for i in range(len(urls))],
        credits,
        "tavily",
        when if when is not None else [None] * len(urls),
    )


def test_two_searches_are_merged_in_turn_without_repeats_and_capped() -> None:
    at = datetime(2026, 10, 24, 15, 40, tzinfo=UTC)
    english = answer(
        "en", ["https://a.example.com/1", "https://a.example.com/2/", "https://x.example.com"]
    )
    local = answer(
        "es",
        ["https://b.example.com/1", "https://a.example.com/2#top", "https://b.example.com/3"],
        [None, at, None],
    )
    merged = merge([english, local])
    assert [u for u, _ in merged.sources] == [
        "https://a.example.com/1",
        "https://b.example.com/1",
        "https://a.example.com/2/",  # the repeat (spelled differently) is one source
        "https://x.example.com",
        "https://b.example.com/3",
    ]
    # The repeat keeps the first copy's title and page and gains the date only the second knew.
    assert merged.sources[2] == ("https://a.example.com/2/", "en 1")
    assert merged.pages[2] == "en page 1" and merged.published[2] == at
    assert merged.credits == 2 and merged.provider == "tavily"
    assert len(merged.pages) == len(merged.published) == len(merged.sources)
    # A single answer is left as it is; many sources are capped.
    assert merge([english]) is english
    many = merge(
        [
            answer("en", [f"https://a.example.com/{n}" for n in range(5)]),
            answer("es", [f"https://b.example.com/{n}" for n in range(5)]),
        ]
    )
    assert len(many.sources) == len(many.pages) == MAX_MERGED == 8
    assert [u for u, _ in many.sources][:4] == [
        "https://a.example.com/0",
        "https://b.example.com/0",
        "https://a.example.com/1",
        "https://b.example.com/1",
    ]


def test_a_provider_with_no_dates_or_pages_still_merges() -> None:
    plain = WebAnswer("An answer.", [("https://a.example.com", "A")], Decimal("0.01"))
    merged = merge([plain, answer("es", ["https://b.example.com"])])
    assert merged.text == "An answer." and merged.usd == Decimal("0.01")
    assert merged.pages == ["", "es page 0"] and merged.published == [None, None]


def test_sources_carry_the_date_of_the_page_they_came_from() -> None:
    at = datetime(2026, 10, 24, 15, 40, tzinfo=UTC)
    found = [
        ("https://a.example.com", "A"),
        ("https://10.0.0.1/x", "Internal"),
        ("https://c.example.com", "C"),
    ]
    sources = sources_from(found, at.date(), [None, at, at])
    assert [(s.id, s.published) for s in sources] == [(1, None), (2, at)]
    assert sources_from(found, at.date())[1].published is None


def test_how_long_ago_a_page_was_published() -> None:
    now = datetime(2026, 10, 24, 17, 40, tzinfo=UTC)
    madrid = ZoneInfo("Europe/Madrid")

    def note(ago: timedelta) -> str:
        return published_note(now - ago, now, madrid)

    assert note(timedelta(seconds=20)) == "just now / 2026-10-24 19:39"
    assert note(timedelta(minutes=-5)).startswith("just now")  # a clock a little ahead
    assert note(timedelta(minutes=12)) == "12 min ago / 2026-10-24 19:28"
    assert note(timedelta(hours=2)) == "2h ago / 2026-10-24 17:40"
    assert note(timedelta(hours=23, minutes=59)) == "23h ago / 2026-10-23 19:41"
    assert note(timedelta(days=1)) == "1 day ago / 2026-10-23 19:40"
    assert note(timedelta(days=3, hours=5)) == "3 days ago / 2026-10-21 14:40"
    assert published_note(now, now, UTC).endswith("2026-10-24 17:40")


def test_how_long_an_answer_is_kept_depends_on_how_recent_it_must_be() -> None:
    assert (KEEP_TODAY, KEEP_WEEK, KEEP_FOR) == (
        timedelta(minutes=10),
        timedelta(hours=1),
        timedelta(hours=24),
    )
    assert keep_for("today") == KEEP_TODAY
    assert keep_for("week") == KEEP_WEEK
    assert keep_for(None) == KEEP_FOR
