"""Daily prices: when they're due, what a position is worth at them, and reading
Tiingo's answer. Every ticker and figure here is made up."""

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from nexus.application.market import PriceSourceError
from nexus.domain.investments import Position
from nexus.domain.market import Bar, due, last_publish, value
from nexus.domain.money import Money
from nexus.infra.market.tiingo import TiingoPrices, tiingo_symbol


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def test_prices_are_due_after_each_us_close() -> None:
    # Monday 2026-09-28, 17:00 in New York: Friday's second slot is the latest.
    assert last_publish(at("2026-09-28T17:00:00-04:00")) == at("2026-09-25T22:00:00-04:00")
    assert last_publish(at("2026-09-28T18:30:00-04:00")) == at("2026-09-28T18:00:00-04:00")
    # Over the weekend nothing new is due after Friday's late slot.
    assert last_publish(at("2026-09-27T12:00:00-04:00")) == at("2026-09-25T22:00:00-04:00")
    assert due(None, at("2026-09-27T12:00:00-04:00"))
    assert not due(at("2026-09-25T23:00:00-04:00"), at("2026-09-27T12:00:00-04:00"))
    assert due(at("2026-09-28T17:00:00-04:00"), at("2026-09-28T18:30:00-04:00"))


def bar(day: date, close: str) -> Bar:
    p = Decimal(close)
    return Bar("NVDA", day, p, p, p, p, p, 1)


def test_a_position_is_valued_at_the_last_close() -> None:
    position = Position("NVDA", Decimal("10"), Money(Decimal("118.40"), "USD"))
    v = value(position, bar(date(2026, 9, 25), "130.255"), bar(date(2026, 9, 24), "128.00"))
    assert v.price == Money(Decimal("130.255"), "USD")
    assert v.value == Money(Decimal("1302.55"), "USD")
    assert v.gain == Money(Decimal("118.55"), "USD")
    assert v.gain_percent == Decimal("10.01")
    assert v.day_change == Money(Decimal("22.55"), "USD")
    assert v.day_percent == Decimal("1.76")
    first = value(position, bar(date(2026, 9, 25), "100"), None)
    assert first.day_change is None and first.gain == Money(Decimal("-184.00"), "USD")


def tiingo(handler: httpx.MockTransport) -> TiingoPrices:
    return TiingoPrices(httpx.AsyncClient(transport=handler), "test-key", base_url="https://t.test")


async def test_tiingo_daily_prices() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "zzzz" in request.url.path:
            return httpx.Response(404, json={"detail": "not found"})
        if "down" in request.url.path:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json=[
                {"date": "2026-09-25T00:00:00.000Z", "close": 130.25, "high": 131, "low": 127.5,
                 "open": 128, "volume": 12345, "adjClose": 130.25},
                {"date": "2026-09-24T00:00:00.000Z", "close": 128.0, "adjClose": 128.0},
                {"date": "bad", "close": 1},
                {"date": "2026-09-23T00:00:00.000Z", "close": 0},
            ],
        )  # fmt: skip

    prices = tiingo(httpx.MockTransport(answer))
    bars = await prices.daily("BRK.B", date(2026, 9, 1), date(2026, 9, 28))
    assert bars is not None
    assert [(b.day, b.close) for b in bars] == [
        (date(2026, 9, 24), Decimal("128.000000")),
        (date(2026, 9, 25), Decimal("130.250000")),
    ]
    assert bars[1].high == Decimal("131.000000") and bars[1].volume == 12345
    assert bars[0].symbol == "BRK.B"
    request = seen[0]
    assert request.url.path == "/tiingo/daily/brk-b/prices"
    assert request.url.params["startDate"] == "2026-09-01"
    # The key travels in a header, never in the URL.
    assert request.headers["Authorization"] == "Token test-key"
    assert "test-key" not in str(request.url)
    assert await prices.daily("ZZZZ", date(2026, 9, 1), date(2026, 9, 28)) is None
    with pytest.raises(PriceSourceError):
        await prices.daily("DOWN", date(2026, 9, 1), date(2026, 9, 28))


def test_tiingo_share_classes() -> None:
    assert tiingo_symbol("BRK.B") == "brk-b"
    assert tiingo_symbol("NVDA") == "nvda"
