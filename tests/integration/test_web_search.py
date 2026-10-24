"""Web search kept and shared out: an answer is reused for a day, each product stays
within its share of the free credits, and past it (or when the provider fails) the
fallback answers instead. Pages read by address are kept and counted the same way.
Every page here is made up."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nexus.application.web_search import (
    KEEP_FOR,
    KEEP_TODAY,
    KEEP_WEEK,
    KeptReader,
    KeptSearch,
    Product,
    ReadPages,
    Recency,
    WebAnswer,
    WebSearchError,
    allowance,
)
from tests.fakes import NOW
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration


PUBLISHED = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)


@dataclass
class Provider:
    name: str
    credits: int = 1
    fail: bool = False
    # Give each question its own source (else every question finds the same one).
    own_sources: bool = False
    fail_on: str = ""  # fail only for this question
    asked: list[str] = field(default_factory=list)
    recents: list[Recency | None] = field(default_factory=list)

    async def ask(self, question: str, recent: Recency | None = None) -> WebAnswer:
        self.asked.append(question)
        self.recents.append(recent)
        if self.fail or (self.fail_on and question == self.fail_on):
            raise WebSearchError("HTTP 500")
        tavily = self.name == "tavily"
        slug = "-".join(question.split()).lower() if self.own_sources else "a"
        return WebAnswer(
            "",
            [(f"https://guide.example.com/{slug}", "A guide")],
            Decimal(0) if tavily else Decimal("0.01"),
            ["Exampleton's Old Harbour has late food."] if tavily else [],
            self.credits,
            self.name,
            [PUBLISHED if recent else None],
        )


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self):  # type: ignore[no-untyped-def]
        return self.now


def search(
    uow: UowFactory,
    product: Product,
    primary: Provider | None,
    fallback: Provider | None,
    clock: Clock,
    monthly: int = 1000,
) -> KeptSearch:
    return KeptSearch(
        uow, product, primary=primary, fallback=fallback, monthly_credits=monthly, clock=clock
    )


async def test_an_answer_is_kept_for_a_day_and_shared(uow: UowFactory) -> None:
    clock, tavily, backup = Clock(), Provider("tavily"), Provider("openrouter")
    travel = search(uow, Product.TRAVEL, tavily, backup, clock)
    first = await travel.ask("Where to stay in Exampleton?")
    assert first.provider == "tavily" and first.pages == ["Exampleton's Old Harbour has late food."]
    # The same question again (spacing aside), from any product: no new search.
    general = search(uow, Product.GENERAL, tavily, backup, clock)
    again = await general.ask("Where to stay   in Exampleton?")
    assert again.pages == first.pages and again.credits == 0 and len(tavily.asked) == 1
    async with uow() as db:
        assert await db.web.credits(NOW.date().replace(day=1)) == {"travel": 1}
    # A day later it's searched afresh.
    clock.now = NOW + KEEP_FOR + timedelta(seconds=1)
    await travel.ask("Where to stay in Exampleton?")
    assert len(tavily.asked) == 2


async def test_past_its_share_a_product_uses_the_fallback(uow: UowFactory) -> None:
    clock, tavily, backup = Clock(), Provider("tavily", credits=2), Provider("openrouter")
    monthly = 10  # travel's share: 5 credits
    assert allowance(monthly, Product.TRAVEL) == 5
    travel = search(uow, Product.TRAVEL, tavily, backup, clock, monthly)
    answers = [await travel.ask(f"question {n}") for n in range(4)]
    assert [a.provider for a in answers] == ["tavily", "tavily", "tavily", "openrouter"]
    # Investment's share is its own.
    investment = search(uow, Product.INVESTMENT, tavily, backup, clock, monthly)
    assert (await investment.ask("another question")).provider == "tavily"
    # Next month the share is back.
    clock.now = NOW + timedelta(days=40)
    assert (await travel.ask("a new question")).provider == "tavily"


async def test_a_failed_search_falls_back_and_spends_nothing(uow: UowFactory) -> None:
    clock, backup = Clock(), Provider("openrouter")
    travel = search(uow, Product.TRAVEL, Provider("tavily", fail=True), backup, clock)
    answer = await travel.ask("Where to stay in Exampleton?")
    assert answer.provider == "openrouter" and answer.pages == []
    async with uow() as db:
        assert await db.web.credits(NOW.date().replace(day=1)) == {}


async def test_without_any_search_it_says_so(uow: UowFactory) -> None:
    travel = search(uow, Product.TRAVEL, Provider("tavily", fail=True), None, Clock())
    with pytest.raises(WebSearchError, match="isn't available"):
        await travel.ask("anything")


async def test_without_tavily_the_fallback_answers(uow: UowFactory) -> None:
    clock, backup = Clock(), Provider("openrouter")
    travel = search(uow, Product.TRAVEL, None, backup, clock)
    assert (await travel.ask("anything")).provider == "openrouter"
    # Its answers are kept too, so asking twice costs once.
    await travel.ask("anything")
    assert len(backup.asked) == 1


@dataclass
class Pages:
    """Made-up news pages: any address under news.example.com reads, others don't."""

    fail: bool = False
    asked: list[list[str]] = field(default_factory=list)

    async def read(self, urls: Sequence[str]) -> ReadPages:
        self.asked.append(list(urls))
        if self.fail:
            raise WebSearchError("HTTP 500")
        pages = {u: f"The article at {u}." for u in urls if "news.example.com" in u}
        return ReadPages(pages, credits=1 if pages else 0)


def reader(uow: UowFactory, pages: Pages, clock: Clock, monthly: int = 1000) -> KeptReader:
    return KeptReader(uow, Product.INVESTMENT, reader=pages, monthly_credits=monthly, clock=clock)


A, B, BLOCKED = (
    "https://news.example.com/a",
    "https://news.example.com/b",
    "https://paywall.example.com/c",
)


async def test_pages_are_kept_a_day_including_ones_that_wouldnt_read(uow: UowFactory) -> None:
    clock, pages = Clock(), Pages()
    news = reader(uow, pages, clock)
    assert await news.read([A, BLOCKED, A]) == {A: f"The article at {A}."}
    # Read again: only the new page is fetched; the blocked one isn't tried again.
    assert set(await news.read([A, B, BLOCKED])) == {A, B}
    assert pages.asked == [[A, BLOCKED], [B]]
    async with uow() as db:
        assert await db.web.credits(NOW.date().replace(day=1)) == {"investment": 2}
    # A day later everything is read afresh.
    clock.now = NOW + KEEP_FOR + timedelta(seconds=1)
    await news.read([A])
    assert pages.asked[-1] == [A]


async def test_past_its_share_or_failing_nothing_new_is_read(uow: UowFactory) -> None:
    clock, pages = Clock(), Pages()
    news = reader(uow, pages, clock, monthly=4)  # investment's share: 0 credits
    assert allowance(4, Product.INVESTMENT) == 0
    assert await news.read([A]) == {} and pages.asked == []
    failing = reader(uow, Pages(fail=True), clock)
    assert await failing.read([A]) == {}
    # A failure isn't kept: next time it's tried again.
    working = Pages()
    assert await reader(uow, working, clock).read([A]) == {A: f"The article at {A}."}


async def test_news_is_kept_ten_minutes_today_an_hour_this_week_and_a_day_otherwise(
    uow: UowFactory,
) -> None:
    assert (KEEP_TODAY, KEEP_WEEK, KEEP_FOR) == (
        timedelta(minutes=10),
        timedelta(hours=1),
        timedelta(hours=24),
    )
    modes: list[tuple[Recency | None, timedelta]] = [
        ("today", KEEP_TODAY),
        ("week", KEEP_WEEK),
        (None, KEEP_FOR),
    ]
    for recent, ttl in modes:
        clock, tavily = Clock(), Provider("tavily")
        travel = search(uow, Product.GENERAL, tavily, None, clock)
        question = f"protest in Exampleton {recent}"
        await travel.ask(question, recent)
        clock.now = NOW + ttl - timedelta(seconds=1)
        await travel.ask(question, recent)
        assert len(tavily.asked) == 1, recent  # still kept just inside the time
        clock.now = NOW + ttl + timedelta(seconds=1)
        await travel.ask(question, recent)
        assert len(tavily.asked) == 2, recent  # searched afresh just past it
        assert tavily.recents == [recent, recent]


async def test_what_was_asked_and_how_is_part_of_the_key(uow: UowFactory) -> None:
    clock, tavily = Clock(), Provider("tavily", own_sources=True)
    travel = search(uow, Product.GENERAL, tavily, None, clock)
    q = "protest in Exampleton"
    await travel.ask(q)
    await travel.ask(q, "today")
    await travel.ask(q, "week")
    await travel.ask(q, "today", "protesta en Exampleton")
    await travel.ask(q, "today", "huelga en Exampleton")
    assert len(tavily.asked) == 7  # the two-language searches asked both ways
    # Each is kept under its own key: asking any of them again costs nothing.
    await travel.ask(q)
    await travel.ask(q, "today")
    await travel.ask(q, "today", "  protesta  en Exampleton ")
    assert len(tavily.asked) == 7
    # The news search found a date; it survives being kept.
    again = await travel.ask(q, "today")
    assert again.published == [PUBLISHED] and again.credits == 0
    assert (await travel.ask(q)).published == [None]


async def test_a_local_query_is_a_second_search_at_two_credits_and_merged(
    uow: UowFactory,
) -> None:
    clock, tavily = Clock(), Provider("tavily", own_sources=True)
    travel = search(uow, Product.GENERAL, tavily, None, clock)
    found = await travel.ask("protest Exampleton today", "today", "protesta Exampleton hoy")
    assert sorted(tavily.asked) == ["protest Exampleton today", "protesta Exampleton hoy"]
    assert tavily.recents == ["today", "today"]
    assert [u for u, _ in found.sources] == [
        "https://guide.example.com/protest-exampleton-today",
        "https://guide.example.com/protesta-exampleton-hoy",
    ]
    assert found.published == [PUBLISHED, PUBLISHED] and found.credits == 2
    async with uow() as db:
        assert await db.web.credits(NOW.date().replace(day=1)) == {"general": 2}
    # Kept, so asking again spends nothing more.
    await travel.ask("protest Exampleton today", "today", "protesta Exampleton hoy")
    assert len(tavily.asked) == 2
    # The same words in both is one search.
    await travel.ask("Strike Exampleton", "week", " strike   exampleton ")
    assert len(tavily.asked) == 3
    async with uow() as db:
        assert await db.web.credits(NOW.date().replace(day=1)) == {"general": 3}


async def test_with_one_credit_left_only_the_main_question_is_asked(uow: UowFactory) -> None:
    clock, tavily, backup = Clock(), Provider("tavily", own_sources=True), Provider("openrouter")
    monthly = 10
    assert allowance(monthly, Product.TRAVEL) == 5
    travel = search(uow, Product.TRAVEL, tavily, backup, clock, monthly)
    for n in range(3):
        await travel.ask(f"question {n}")  # 3 of 5 credits
    both = await travel.ask("protest today", "today", "protesta hoy")  # 2 left: both asked
    assert both.credits == 2 and len(both.sources) == 2
    async with uow() as db:
        assert await db.web.credits(NOW.date().replace(day=1)) == {"travel": 5}
    # Nothing left: the fallback, with the main question alone.
    out = await travel.ask("strike today", "today", "huelga hoy")
    assert out.provider == "openrouter" and backup.asked == ["strike today"]
    assert backup.recents == ["today"]

    clock2, tavily2 = Clock(), Provider("tavily", own_sources=True)
    travel2 = search(uow, Product.INVESTMENT, tavily2, None, clock2, 20)
    assert allowance(20, Product.INVESTMENT) == 4
    for n in range(3):
        await travel2.ask(f"other question {n}")  # 3 of 4: one left
    one = await travel2.ask("flood today", "today", "inundación hoy")
    assert tavily2.asked[-1] == "flood today" and "inundación hoy" not in tavily2.asked
    assert one.credits == 1 and len(one.sources) == 1
    async with uow() as db:
        assert (await db.web.credits(NOW.date().replace(day=1)))["investment"] == 4


async def test_if_one_of_two_searches_fails_the_other_is_used(uow: UowFactory) -> None:
    clock = Clock()
    local_fails = Provider("tavily", own_sources=True, fail_on="protesta hoy")
    travel = search(uow, Product.GENERAL, local_fails, Provider("openrouter"), clock)
    found = await travel.ask("protest today", "today", "protesta hoy")
    assert found.provider == "tavily" and len(found.sources) == 1 and found.credits == 1
    async with uow() as db:
        assert await db.web.credits(NOW.date().replace(day=1)) == {"general": 1}
    # Both failing is a failed search: the fallback answers the main question.
    both = Provider("tavily", fail=True)
    backup = Provider("openrouter")
    out = await search(uow, Product.GENERAL, both, backup, clock).ask("x today", "today", "x hoy")
    assert out.provider == "openrouter" and backup.asked == ["x today"]


async def test_pages_read_for_news_are_kept_only_as_long_as_news_answers(
    uow: UowFactory,
) -> None:
    clock, pages = Clock(), Pages()
    news = reader(uow, pages, clock)
    await news.read([A], "today")
    await news.read([A], "today")
    assert pages.asked == [[A]]  # kept within the ten minutes
    clock.now = NOW + KEEP_TODAY + timedelta(seconds=1)
    await news.read([A], "today")
    assert pages.asked == [[A], [A]]  # not served stale
    # An ordinary read of the same page is kept separately, for the day.
    await news.read([A])
    await news.read([A])
    assert pages.asked == [[A], [A], [A]]
    clock.now = NOW + KEEP_TODAY + KEEP_WEEK
    await news.read([A])
    assert len(pages.asked) == 3
