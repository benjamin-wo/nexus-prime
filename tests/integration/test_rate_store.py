from datetime import date
from decimal import Decimal

from nexus.application.fx import Rate
from nexus.application.rate_store import StoredRates
from nexus.infra.db.engine import make_engine
from nexus.infra.db.uow import SqlUnitOfWork
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
