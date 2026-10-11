"""Web search kept and shared out: an answer is reused for a day, each product stays
within its share of the free credits, and past it (or when the provider fails) the
fallback answers instead. Every page here is made up."""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import pytest

from nexus.application.web_search import (
    KEEP_FOR,
    KeptSearch,
    Product,
    WebAnswer,
    WebSearchError,
    allowance,
)
from tests.fakes import NOW
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration


@dataclass
class Provider:
    name: str
    credits: int = 1
    fail: bool = False
    asked: list[str] = field(default_factory=list)

    async def ask(self, question: str) -> WebAnswer:
        self.asked.append(question)
        if self.fail:
            raise WebSearchError("HTTP 500")
        return WebAnswer(
            "",
            [("https://guide.example.com/a", "A guide")],
            Decimal(0) if self.name == "tavily" else Decimal("0.01"),
            ["Exampleton's Old Harbour has late food."] if self.name == "tavily" else [],
            self.credits,
            self.name,
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
