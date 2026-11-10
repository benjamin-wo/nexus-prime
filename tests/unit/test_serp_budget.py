"""The SerpApi budget and the kept answers: a hard stop at the monthly cap, ten a day for each
user, nothing counted for an answer that was kept, nothing made once the budget is out. The
database is a small in-memory stand-in here; ``tests/integration/test_serp_budget.py`` runs
the same rules against Postgres, including searches made at the same moment."""

import copy
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import TracebackType
from typing import Any, Self, cast
from uuid import UUID, uuid4

import httpx
import pytest

from nexus.application.live_prices import KEEP_FOR, KEEP_STATUS_FOR, LivePrices
from nexus.application.ports import UnitOfWork
from nexus.application.serp_budget import (
    DEFAULT_MONTHLY,
    USER_DAILY,
    SearchesPaused,
    SerpBudget,
    Spend,
)
from nexus.application.web_search import WebSearchError
from nexus.domain.ledger import UserId
from nexus.domain.live_prices import FlightFares, ProductQuery, StatusQuery
from nexus.infra.search.serpapi import SerpApiClient, SerpApiPrices
from tests.unit.test_serp_prices import FLIGHT, KEY, shopping_response

START = datetime(2026, 11, 10, 8, 30, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Store:
    """What the database holds: committed counts and kept answers."""

    def __init__(self) -> None:
        self.months: dict[date, int] = {}
        self.days: dict[tuple[UUID, date], int] = {}
        self.kept: dict[str, tuple[dict[str, Any], datetime]] = {}
        self.down = False


class Web:
    def __init__(self, store: Store, work: Store) -> None:
        self._store, self._work = store, work

    async def cached(self, key: str, now: datetime) -> dict[str, Any] | None:
        found = self._work.kept.get(key)
        return found[0] if found and found[1] > now else None

    async def keep(
        self, key: str, body: dict[str, Any], expires_at: datetime, now: datetime
    ) -> None:
        self._work.kept[key] = (body, expires_at)

    async def reserve_serp(
        self, month: date, monthly_cap: int, user_id: UUID | None, day: date, daily_cap: int
    ) -> str:
        work = self._work
        if user_id is not None:
            if work.days.get((user_id, day), 0) >= daily_cap:
                return "day"
            work.days[(user_id, day)] = work.days.get((user_id, day), 0) + 1
        if work.months.get(month, 0) >= monthly_cap:
            return "month"
        work.months[month] = work.months.get(month, 0) + 1
        return "ok"


class Uow:
    """Changes are kept only when committed, as in the database."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._work = Store()

    async def __aenter__(self) -> Self:
        if self._store.down:
            raise ConnectionError("database is down")
        self._work = copy.deepcopy(self._store)
        self.web = Web(self._store, self._work)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        down = self._store.down
        self._store.__dict__.update(copy.deepcopy(self._work).__dict__)
        self._store.down = down


def database(store: Store, uow: type[Uow] = Uow) -> Callable[[], UnitOfWork]:
    return lambda: cast(UnitOfWork, uow(store))


def make(
    monthly: int = DEFAULT_MONTHLY, clock: Clock | None = None
) -> tuple[Store, SerpBudget, Clock]:
    store, clock = Store(), clock or Clock()
    return store, SerpBudget(database(store), monthly, clock), clock


def a_user() -> UserId:
    return UserId(uuid4())


async def test_the_default_is_a_few_under_the_free_plan() -> None:
    assert DEFAULT_MONTHLY == 240
    assert USER_DAILY == 10


async def test_the_monthly_cap_stops_at_240_and_names_the_first_of_next_month() -> None:
    store, budget, _ = make()
    users = [a_user() for _ in range(30)]  # 8 each: no one reaches their own day's limit
    for n in range(240):
        await budget.reserve(Spend(users[n % 30], date(2026, 11, 10)))
    assert store.months == {date(2026, 11, 1): 240}
    with pytest.raises(SearchesPaused) as stopped:
        await budget.reserve(Spend(users[0], date(2026, 11, 10)))
    assert stopped.value.scope == "month"
    assert stopped.value.until == date(2026, 12, 1)
    assert store.months == {date(2026, 11, 1): 240}  # the refused one was not counted
    # A search for no one in particular (the trip researcher) is stopped by the same count.
    with pytest.raises(SearchesPaused):
        await budget.reserve(Spend())


async def test_a_refused_month_does_not_use_up_the_users_day() -> None:
    store, budget, _ = make(monthly=1)
    first, second = a_user(), a_user()
    await budget.reserve(Spend(first, date(2026, 11, 10)))
    with pytest.raises(SearchesPaused):
        await budget.reserve(Spend(second, date(2026, 11, 10)))
    assert (second, date(2026, 11, 10)) not in store.days


async def test_a_new_month_starts_again() -> None:
    store, budget, clock = make(monthly=2)
    await budget.reserve(Spend())
    await budget.reserve(Spend())
    with pytest.raises(SearchesPaused):
        await budget.reserve(Spend())
    clock.now = datetime(2026, 12, 1, 0, 0, 1, tzinfo=UTC)
    await budget.reserve(Spend())
    assert store.months == {date(2026, 11, 1): 2, date(2026, 12, 1): 1}


async def test_each_user_has_ten_a_day_and_is_told_tomorrow() -> None:
    store, budget, _ = make()
    me, you = a_user(), a_user()
    today = date(2026, 11, 10)
    for _ in range(10):
        await budget.reserve(Spend(me, today))
    with pytest.raises(SearchesPaused) as stopped:
        await budget.reserve(Spend(me, today))
    assert stopped.value.scope == "day"
    assert stopped.value.until == date(2026, 11, 11)
    assert store.months == {date(2026, 11, 1): 10}  # the eleventh was not counted anywhere
    await budget.reserve(Spend(you, today))  # someone else is not held back
    await budget.reserve(Spend(me, date(2026, 11, 11)))  # nor is tomorrow
    assert store.days[(me, today)] == 10


async def test_the_researchers_searches_count_against_the_month_not_a_day() -> None:
    store, budget, _ = make()
    for _ in range(USER_DAILY + 5):
        await budget.reserve(Spend())
    assert store.months == {date(2026, 11, 1): USER_DAILY + 5}
    assert store.days == {}


async def test_a_database_that_cannot_be_reached_means_no_search_not_an_unchecked_one() -> None:
    store, budget, _ = make()
    store.down = True
    with pytest.raises(WebSearchError) as failed:
        await budget.reserve(Spend(a_user()))
    assert not isinstance(failed.value, SearchesPaused)


# --- kept answers: the same request within six hours costs nothing ------------------------------


class Searching:
    """SerpApi's searches with the real budget in front of them, counting what is made."""

    def __init__(self, budget: SerpBudget) -> None:
        self.budget = budget
        self.made = 0
        self._http = httpx.AsyncClient(transport=httpx.MockTransport(self._answer))
        self.prices = SerpApiPrices(
            SerpApiClient(self._http, KEY, budget),
            lambda: START,
        )

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.made += 1
        engine = request.url.params["engine"]
        if engine == "google_shopping":
            return httpx.Response(200, json=shopping_response())
        if engine == "google":
            return httpx.Response(200, json={"flight_result": {"dates": []}})
        return httpx.Response(200, json={"best_flights": [], "search_metadata": {}})

    async def flights(self, q: Any, spend: Spend) -> Any:
        return await self.prices.flights(q, spend)

    async def calendar(self, q: Any, spend: Spend) -> Any:
        return await self.prices.calendar(q, spend)

    async def products(self, q: Any, spend: Spend) -> Any:
        return await self.prices.products(q, spend)

    async def status(self, q: Any, spend: Spend) -> Any:
        return await self.prices.status(q, spend)


def live() -> tuple[Store, Searching, LivePrices, Clock]:
    store, budget, clock = make()
    source = Searching(budget)
    return store, source, LivePrices(source, database(store), clock), clock


TODAY = date(2026, 11, 10)


async def test_a_request_made_again_within_six_hours_is_answered_from_what_was_kept() -> None:
    store, source, prices, clock = live()
    me = a_user()
    first = await prices.products(me, ProductQuery("frobnicator 2"), TODAY)
    assert source.made == 1
    assert store.months == {date(2026, 11, 1): 1}
    clock.now += KEEP_FOR - timedelta(minutes=1)
    again = await prices.products(a_user(), ProductQuery("frobnicator 2"), TODAY)  # anyone's
    assert again == first
    assert source.made == 1  # no second search
    assert store.months == {date(2026, 11, 1): 1}  # and none counted
    assert store.days[(me, TODAY)] == 1


async def test_after_six_hours_or_with_any_difference_it_is_a_new_search() -> None:
    store, source, prices, clock = live()
    me = a_user()
    await prices.products(me, ProductQuery("frobnicator 2"), TODAY)
    await prices.products(me, ProductQuery("frobnicator 3"), TODAY)
    assert source.made == 2
    clock.now += KEEP_FOR + timedelta(seconds=1)
    await prices.products(me, ProductQuery("frobnicator 2"), TODAY)
    assert source.made == 3
    assert store.months == {date(2026, 11, 1): 3}


async def test_flights_differing_in_a_date_cabin_or_passenger_are_separate_requests() -> None:
    _, source, prices, _ = live()
    me = a_user()
    await prices.flights(me, FLIGHT, TODAY)
    await prices.flights(me, FLIGHT, TODAY)
    assert source.made == 1
    await prices.flights(me, replace(FLIGHT, adults=1), TODAY)
    await prices.flights(me, replace(FLIGHT, cabin="business"), TODAY)
    await prices.flights(me, replace(FLIGHT, back=None), TODAY)
    await prices.flights(me, replace(FLIGHT, outbound=date(2026, 12, 11)), TODAY)
    assert source.made == 5


async def test_a_flights_status_is_kept_only_a_quarter_of_an_hour() -> None:
    _, source, prices, clock = live()
    me = a_user()
    query = StatusQuery("SQ12", None)
    await prices.status(me, query, TODAY)
    clock.now += KEEP_STATUS_FOR - timedelta(seconds=1)
    await prices.status(me, query, TODAY)
    assert source.made == 1
    clock.now += timedelta(seconds=2)
    await prices.status(me, query, TODAY)
    assert source.made == 2


async def test_what_is_kept_holds_no_key_and_no_request() -> None:
    store, _, prices, _ = live()
    await prices.flights(a_user(), FLIGHT, TODAY)
    await prices.products(a_user(), ProductQuery("frobnicator 2"), TODAY)
    assert len(store.kept) == 2
    stored = json.dumps([body for body, _ in store.kept.values()])
    assert KEY not in stored
    assert "api_key" not in stored
    assert "serpapi.com" not in stored
    assert all(len(key) == 64 for key in store.kept)  # hashes, not what was asked


async def test_a_used_up_budget_still_answers_what_was_kept_and_otherwise_makes_no_search() -> None:
    store, source, prices, _ = live()
    me = a_user()
    await prices.products(me, ProductQuery("frobnicator 2"), TODAY)
    store.months[date(2026, 11, 1)] = DEFAULT_MONTHLY  # used up
    kept = await prices.products(me, ProductQuery("frobnicator 2"), TODAY)
    assert kept.offers
    with pytest.raises(SearchesPaused):
        await prices.products(me, ProductQuery("something else"), TODAY)
    assert source.made == 1


class _Down:
    """Kept answers that can neither be read nor written."""

    async def cached(self, *args: Any) -> Any:
        raise ConnectionError("cache is down")

    async def keep(self, *args: Any) -> Any:
        raise ConnectionError("cache is down")

    async def reserve_serp(self, *args: Any) -> str:
        return "ok"


async def test_the_database_failing_does_not_stop_a_lookup_that_can_be_counted() -> None:
    # Kept answers failing to read or write is no reason to refuse; only the count is.
    store, source, _, _ = live()

    class Broken(Uow):
        async def __aenter__(self) -> Self:
            await super().__aenter__()
            self.web = cast(Web, _Down())
            return self

    cached_only = LivePrices(source, database(store, Broken), Clock())
    found = await cached_only.flights(a_user(), FLIGHT, TODAY)
    assert isinstance(found, FlightFares)
    assert source.made == 1
