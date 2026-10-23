import asyncio
from datetime import date
from decimal import Decimal

import httpx
import pytest

from nexus.application.fx import Rate
from nexus.application.rate_store import StoredRates
from nexus.infra.db.engine import make_engine
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.infra.fx import frankfurter as frankfurter_module
from nexus.infra.fx.frankfurter import FrankfurterRates
from tests.integration.conftest import UowFactory

TODAY = date(2026, 10, 10)


class CountingRates:
    """A provider that answers every day with a made-up rate and counts the asks."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, date]] = []

    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        self.asked.append((base, quote, on))
        if base == "XXX":
            return None  # not a currency the provider covers
        # Saturday 3 Oct answers with Friday's rate, as reference rates do.
        effective = date(2026, 10, 2) if on == date(2026, 10, 3) else on
        return Rate(base, quote, Decimal("1.2875"), effective)


async def test_a_past_rate_is_fetched_once_and_kept_across_restarts(uow: UowFactory) -> None:
    provider = CountingRates()
    rates = StoredRates(provider, uow, today=lambda: TODAY)
    first = await rates.rate("USD", "SGD", date(2026, 10, 3))
    assert first == Rate("USD", "SGD", Decimal("1.2875"), date(2026, 10, 2))
    assert await rates.rate("USD", "SGD", date(2026, 10, 3)) == first

    restarted = StoredRates(provider, uow, today=lambda: TODAY)  # memory is gone
    assert await restarted.rate("USD", "SGD", date(2026, 10, 3)) == first
    assert provider.asked == [("USD", "SGD", date(2026, 10, 3))]


async def test_today_and_missing_rates_are_not_kept(uow: UowFactory) -> None:
    provider = CountingRates()
    rates = StoredRates(provider, uow, today=lambda: TODAY)
    await rates.rate("USD", "SGD", TODAY)
    await rates.rate("USD", "SGD", TODAY)
    assert await rates.rate("XXX", "SGD", date(2026, 10, 1)) is None
    assert await rates.rate("XXX", "SGD", date(2026, 10, 1)) is None
    assert len(provider.asked) == 4
    async with uow() as db:
        assert await db.rates.stored_rate("USD", "SGD", TODAY) is None
        assert await db.rates.stored_rate("XXX", "SGD", date(2026, 10, 1)) is None


async def test_a_kept_rate_is_never_overwritten(uow: UowFactory) -> None:
    kept = Rate("EUR", "SGD", Decimal("1.5"), date(2026, 10, 1))
    async with uow() as db:
        await db.rates.save_rate(date(2026, 10, 1), kept)
        await db.rates.save_rate(
            date(2026, 10, 1), Rate("EUR", "SGD", Decimal("9"), kept.effective)
        )
        await db.commit()
    async with uow() as db:
        assert await db.rates.stored_rate("EUR", "SGD", date(2026, 10, 1)) == kept


async def test_rates_still_work_when_the_database_is_down() -> None:
    broken = make_engine("postgresql://nobody:wrong@127.0.0.1:1/none")
    try:
        rates = StoredRates(CountingRates(), lambda: SqlUnitOfWork(broken), today=lambda: TODAY)
        found = await rates.rate("USD", "SGD", date(2026, 10, 5))
        assert found is not None and found.value == Decimal("1.2875")
    finally:
        await broken.dispose()


class DownRates:
    """A provider that has no answer, and counts the asks."""

    def __init__(self) -> None:
        self.asked = 0

    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        self.asked += 1
        return None


async def keep(uow: UowFactory, day: date, effective: date, value: str = "1.5") -> Rate:
    rate = Rate("EUR", "SGD", Decimal(value), effective)
    async with uow() as db:
        await db.rates.save_rate(day, rate)
        await db.commit()
    return rate


async def test_the_latest_kept_rate_answers_when_the_provider_has_none(uow: UowFactory) -> None:
    older = await keep(uow, date(2026, 10, 1), date(2026, 10, 1), "1.50")
    newest = await keep(uow, date(2026, 10, 3), date(2026, 10, 2), "1.55")  # a Saturday's
    await keep(uow, date(2026, 10, 9), date(2026, 10, 9), "1.60")  # later than asked
    rates = StoredRates(DownRates(), uow, today=lambda: TODAY)
    assert await rates.rate("EUR", "SGD", date(2026, 10, 6)) == newest  # shows its own day
    assert await rates.rate("EUR", "SGD", date(2026, 10, 2)) == newest
    assert await rates.rate("EUR", "SGD", date(2026, 10, 1)) == older
    # Today's, and a day with nothing kept on or before it.
    assert await rates.rate("EUR", "SGD", TODAY) == Rate(
        "EUR", "SGD", Decimal("1.60"), date(2026, 10, 9)
    )
    assert await rates.rate("EUR", "SGD", date(2026, 9, 30)) is None
    assert await rates.rate("EUR", "USD", TODAY) is None
    async with uow() as db:  # the fallback was not kept as those days' rates
        assert await db.rates.stored_rate("EUR", "SGD", date(2026, 10, 6)) is None
        assert await db.rates.stored_rate("EUR", "SGD", TODAY) is None


async def test_a_rate_after_the_day_asked_is_never_the_fallback(uow: UowFactory) -> None:
    await keep(uow, date(2026, 10, 8), date(2026, 10, 8))
    rates = StoredRates(DownRates(), uow, today=lambda: TODAY)
    assert await rates.rate("EUR", "SGD", date(2026, 10, 7)) is None
    async with uow() as db:
        assert await db.rates.latest_rate_on_or_before("EUR", "SGD", date(2026, 10, 7)) is None


async def test_a_slow_provider_gives_the_kept_rate_within_the_short_wait(
    uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(frankfurter_module, "LOOKUP_SECONDS", 0.1)
    kept = await keep(uow, date(2026, 10, 8), date(2026, 10, 8))
    asked = 0

    async def hang(request: httpx.Request) -> httpx.Response:
        nonlocal asked
        asked += 1
        await asyncio.sleep(30)
        return httpx.Response(200)

    http = httpx.AsyncClient(transport=httpx.MockTransport(hang))
    provider = FrankfurterRates(http, base_url="https://fx.test/v1", today=lambda: TODAY)
    rates = StoredRates(provider, uow, today=lambda: TODAY)
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await rates.rate("EUR", "SGD", date(2026, 10, 9)) == kept
    assert loop.time() - started < 2
    # The failure is remembered: the next turn doesn't wait again.
    started = loop.time()
    assert await rates.rate("EUR", "SGD", date(2026, 10, 9)) == kept
    assert loop.time() - started < 0.1 and asked == 1
    await http.aclose()
