"""Dated conversion rules and the Frankfurter client, against a fake HTTP transport."""

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from nexus.application import fx
from nexus.application.fx import Rate
from nexus.domain.money import Money
from nexus.infra.fx.frankfurter import FrankfurterRates
from tests.fakes import FakeRates

SAT = date(2026, 9, 26)
FRI = date(2026, 9, 25)
TODAY = date(2026, 9, 28)


def test_apply_rounds_to_the_home_currency_minor_unit() -> None:
    rate = Rate("USD", "SGD", Decimal("1.2905"), FRI)
    assert fx.apply(Money.of("33.80", "USD"), rate) == Money.of("43.62", "SGD")
    yen = Rate("SGD", "JPY", Decimal("112.345"), FRI)
    assert fx.apply(Money.of("10", "SGD"), yen) == Money.of("1123", "JPY")


async def test_rates_looked_up_once_per_currency_and_day() -> None:
    source = FakeRates({("USD", "SGD"): {FRI: "1.29"}})
    found = await fx.rates_for(source, "SGD", [("USD", SAT), ("USD", SAT), ("SGD", SAT)])
    assert source.asked == [("USD", "SGD", SAT)]
    conversion = fx.convert(Money.of("2", "USD"), SAT, "SGD", found)
    assert conversion.home == Money.of("2.58", "SGD")
    assert conversion.rate is not None and conversion.rate.effective == FRI
    same = fx.convert(Money.of("2", "SGD"), SAT, "SGD", found)
    assert same.home == Money.of("2", "SGD") and same.rate is None


async def test_a_later_rate_is_never_used() -> None:
    class Misbehaving:
        async def rate(self, base: str, quote: str, on: date) -> Rate | None:
            return Rate(base, quote, Decimal("1.3"), TODAY)

    found = await fx.rates_for(Misbehaving(), "SGD", [("USD", SAT)])
    assert fx.convert(Money.of("1", "USD"), SAT, "SGD", found).home is None


def frankfurter(handler: Any, today: date = TODAY) -> tuple[FrankfurterRates, list[str]]:
    seen: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        result: httpx.Response = handler(request)
        return result

    http = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return FrankfurterRates(http, base_url="https://fx.test/v1", today=lambda: today), seen


def ok(day: date, value: Any, base: str = "USD") -> httpx.Response:
    return httpx.Response(
        200, json={"amount": 1.0, "base": base, "date": day.isoformat(), "rates": {"SGD": value}}
    )


async def test_frankfurter_reads_and_caches_past_days() -> None:
    rates, seen = frankfurter(lambda r: ok(FRI, 1.2905))
    first = await rates.rate("USD", "SGD", SAT)
    assert first == Rate("USD", "SGD", Decimal("1.2905"), FRI)
    assert seen == ["https://fx.test/v1/2026-09-26?base=USD&symbols=SGD"]
    assert await rates.rate("USD", "SGD", SAT) == first
    assert len(seen) == 1  # past days are cached


async def test_frankfurter_does_not_cache_today() -> None:
    rates, seen = frankfurter(lambda r: ok(date(2026, 9, 25), "1.29"))
    await rates.rate("USD", "SGD", TODAY)
    await rates.rate("USD", "SGD", TODAY)
    assert len(seen) == 2  # today's rate may still be published


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={"message": "not found"}),
        httpx.Response(500),
        httpx.Response(200, json={"unexpected": True}),
        ok(TODAY, 1.3),  # later than the day asked for
        ok(FRI, 1.3, base="EUR"),
        ok(FRI, -1),
        ok(FRI, "NaN"),
    ],
)
async def test_frankfurter_unavailable(response: httpx.Response) -> None:
    rates, _ = frankfurter(lambda r: response)
    assert await rates.rate("USD", "SGD", SAT) is None


async def test_frankfurter_network_error_is_unavailable_and_not_cached() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("down")
        return ok(FRI, 1.29)

    rates, _ = frankfurter(handler)
    assert await rates.rate("USD", "SGD", SAT) is None
    assert await rates.rate("USD", "SGD", SAT) is not None
