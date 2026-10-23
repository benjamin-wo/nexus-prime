"""Dated conversion rules and the Frankfurter client, against a fake HTTP transport."""

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from nexus.application import fx
from nexus.application.fx import Rate
from nexus.domain.money import Money
from nexus.infra.fx import frankfurter as frankfurter_module
from nexus.infra.fx.frankfurter import (
    FAILURE_MEMORY_SECONDS,
    TODAY_MEMORY_SECONDS,
    FrankfurterRates,
)
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


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def frankfurter(
    handler: Any, today: date = TODAY, clock: Clock | None = None
) -> tuple[FrankfurterRates, list[str]]:
    seen: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        result: httpx.Response = handler(request)
        return result

    http = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    rates = FrankfurterRates(
        http, base_url="https://fx.test/v1", today=lambda: today, monotonic=clock or Clock()
    )
    return rates, seen


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


async def test_frankfurter_remembers_today_only_briefly() -> None:
    clock = Clock()
    rates, seen = frankfurter(lambda r: ok(date(2026, 9, 25), "1.29"), clock=clock)
    first = await rates.rate("USD", "SGD", TODAY)
    clock.now += TODAY_MEMORY_SECONDS - 1
    assert await rates.rate("USD", "SGD", TODAY) == first
    assert len(seen) == 1  # no fetch on every turn
    clock.now += 2
    assert await rates.rate("USD", "SGD", TODAY) == first
    assert len(seen) == 2  # today's rate may still be published, so it is asked again


async def test_frankfurter_caches_not_covered_for_past_days() -> None:
    rates, seen = frankfurter(lambda r: httpx.Response(404, json={"message": "not found"}))
    assert await rates.rate("XXX", "SGD", SAT) is None
    assert await rates.rate("XXX", "SGD", SAT) is None
    assert len(seen) == 1


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


@pytest.mark.parametrize("failure", ["connect", "http", "garbled"])
async def test_frankfurter_failures_are_remembered_for_ten_minutes(failure: str) -> None:
    clock = Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "connect":
                raise httpx.ConnectError("down")
            return httpx.Response(503) if failure == "http" else httpx.Response(200, json={})
        return ok(FRI, 1.29)

    rates, _ = frankfurter(handler, clock=clock)
    assert await rates.rate("USD", "SGD", SAT) is None
    clock.now += FAILURE_MEMORY_SECONDS - 1
    assert await rates.rate("USD", "SGD", SAT) is None
    assert calls == 1  # not retried within the ten minutes
    clock.now += 2
    assert await rates.rate("USD", "SGD", SAT) is not None
    assert calls == 2


async def test_a_slow_provider_is_given_up_on_quickly_and_remembered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(frankfurter_module, "LOOKUP_SECONDS", 0.05)
    calls = 0

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(5)
        return ok(FRI, 1.29)

    rates, _ = frankfurter(slow)
    started = asyncio.get_running_loop().time()
    assert await rates.rate("EUR", "SGD", SAT) is None
    assert asyncio.get_running_loop().time() - started < 1
    assert await rates.rate("EUR", "SGD", SAT) is None
    assert calls == 1


def test_lookups_wait_two_seconds_at_most() -> None:
    assert frankfurter_module.LOOKUP_SECONDS == 2.0
    assert FAILURE_MEMORY_SECONDS == 600.0 and TODAY_MEMORY_SECONDS == 600.0


async def test_distinct_rates_for_one_summary_are_fetched_together() -> None:
    inflight = peak = 0

    class Slow:
        async def rate(self, base: str, quote: str, on: date) -> Rate | None:
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.05)
            inflight -= 1
            return Rate(base, quote, Decimal("1.5"), on)

    wanted = [(c, d) for c in ("EUR", "USD", "GBP") for d in (SAT, FRI, date(2026, 9, 24))]
    found = await fx.rates_for(Slow(), "SGD", wanted)
    assert len(found) == 9 and all(r is not None for r in found.values())
    assert 2 <= peak <= 4  # together, but bounded
