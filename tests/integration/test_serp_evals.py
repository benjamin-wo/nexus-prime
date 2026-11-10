"""The ``serp`` evals: flight prices, product prices and flight status work in the evals with
canned, offline answers, and the cases grade which tool the model reaches for and that it
never claims to book anything."""

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.evals.cases import CASES, Case
from nexus.evals.runner import run_cases
from tests.fakes import call, say, scripted

pytestmark = pytest.mark.integration

NOTHING = (say("Nothing to remember."),) * 2  # the memory pass, and its one retry


def _only(*ids: str) -> list[Case]:
    return [c for c in CASES if c.id in ids]


def test_the_serp_area_covers_fares_the_cheapest_day_products_status_and_no_booking() -> None:
    serp = {c.id: c for c in CASES if c.area == "serp"}
    assert set(serp) == {
        "serp-flight-price",
        "serp-flight-cheapest-day",
        "serp-product-price",
        "serp-flight-status",
        "serp-no-booking",
    }
    tools = {case_id: [wanted.tool for wanted in c.calls] for case_id, c in serp.items()}
    assert tools == {
        "serp-flight-price": ["flight_prices"],
        "serp-flight-cheapest-day": ["flight_prices"],
        "serp-product-price": ["product_prices"],
        "serp-flight-status": ["flight_status"],
        "serp-no-booking": [],
    }
    # The shop-price cases in the web area want the new tool too, not a web search.
    web = {c.id: c for c in CASES if c.id in ("web-console-price", "web-phone-price")}
    assert all([w.tool for w in c.calls] == ["product_prices"] for c in web.values())
    assert all(c.unchanged for c in serp.values())


async def test_the_serp_cases_pass_with_the_canned_live_prices(engine: AsyncEngine) -> None:
    steps: dict[str, tuple[AIMessage, ...]] = {
        "serp-flight-price": (
            call(
                "flight_prices",
                origin="SIN",
                destination="BKK",
                outbound_date="2026-12-10",
                return_date="2026-12-17",
            ),
            say("From SGD 150 (one stop) or SGD 180 nonstop, as of 14:00; nothing is booked."),
        ),
        "serp-flight-cheapest-day": (
            call(
                "flight_prices",
                origin="SIN",
                destination="BKK",
                cheapest_from="2026-12-01",
                cheapest_to="2026-12-31",
            ),
            say("The cheapest days are early in December, as of 14:00."),
        ),
        "serp-product-price": (
            call("product_prices", query="Nintendo Switch 2"),
            say("Cheapest is S$499 at Example Mart, as of 14:00."),
        ),
        "serp-flight-status": (
            call("flight_status", flight="SQ12"),
            say("SQ12 is running about 15 minutes late, as of 14:00."),
        ),
        "serp-no-booking": (say("I can't book flights, but I can look up fares if you like."),),
        "web-console-price": (
            call("product_prices", query="Nintendo Switch 2 console"),
            say("Cheapest is S$499, per Example Mart."),
        ),
    }

    def script(case: Case) -> BaseChatModel:
        return scripted(*steps[case.id], *NOTHING)

    results = await run_cases(engine, script, _only(*steps), concurrency=3)
    assert len(results) == len(steps)
    for result in results:
        assert result.passed, (result.case.id, result.failures, result.error)
    links = {r.case.id: r.turns[0].source_links for r in results}
    assert links["serp-flight-price"] == ["https://flights.example.com/kaya-evals/search"]
    assert links["serp-product-price"]
    assert links["serp-no-booking"] == []


async def test_a_serp_case_fails_when_the_model_claims_a_booking_or_searches_the_web(
    engine: AsyncEngine,
) -> None:
    def script(case: Case) -> BaseChatModel:
        if case.id == "serp-no-booking":
            return scripted(say("Done, I've booked your flight to Bangkok."), *NOTHING)
        return scripted(
            call("web_search", question="cheapest switch 2 singapore"), say("S$499."), *NOTHING
        )

    results = await run_cases(
        engine,
        script,
        _only("serp-no-booking", "serp-product-price"),
        first_telegram_id=930_000,
    )
    failed = {r.case.id: r.failures for r in results}
    assert any("reply matches" in f for f in failed["serp-no-booking"])
    assert "called web_search" in failed["serp-product-price"]
    assert any(f.startswith("no product_prices call") for f in failed["serp-product-price"])
