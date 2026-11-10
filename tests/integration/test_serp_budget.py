"""The SerpApi budget in the database: one monthly count for the whole app (the chat's live
prices and the trip researcher together), ten a day for each user, a hard stop that searches
made at the same moment can't pass, and kept answers that cost nothing. Also migration 0070.
Everything here is made up."""

import asyncio
from contextlib import AsyncExitStack
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.acting import acting_as
from nexus.application.live_prices import LivePrices
from nexus.application.serp_budget import (
    DEFAULT_MONTHLY,
    USER_DAILY,
    SearchesPaused,
    SerpBudget,
    Spend,
)
from nexus.application.web_search import WebSearchError
from nexus.domain.ledger import UserId
from nexus.domain.live_prices import ProductQuery
from nexus.evals.prices import CannedPrices
from nexus.infra.db.engine import make_engine
from nexus.infra.search.serpapi import SerpApiClient, SerpApiPrices, SerpApiTravel
from nexus.main import Overrides, _serp
from nexus.settings import Settings
from tests.integration.conftest import UowFactory, make_user, upgrade
from tests.integration.test_wallets import downgrade
from tests.unit.test_serp_prices import KEY, flights_response, shopping_response

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 10, 8, 30, tzinfo=UTC)
TODAY = date(2026, 11, 10)
MONTH = date(2026, 11, 1)


def budget(uow: UowFactory, monthly: int = DEFAULT_MONTHLY) -> SerpBudget:
    return SerpBudget(uow, monthly, lambda: NOW)


async def credits(engine: AsyncEngine) -> int | None:
    async with engine.connect() as db:
        return (
            await db.execute(
                text("SELECT credits FROM web_credits WHERE product = 'serpapi' AND month = :m"),
                {"m": MONTH},
            )
        ).scalar_one_or_none()


async def days(engine: AsyncEngine) -> dict[UUID, int]:
    async with engine.connect() as db:
        rows = await db.execute(
            text(
                "SELECT user_id, sum(searches)::int AS searches FROM serp_searches GROUP BY user_id"
            )
        )
        return {r.user_id: r.searches for r in rows}


async def users(uow: UowFactory, n: int) -> list[UserId]:
    return [await make_user(uow, 7000 + i) for i in range(n)]


async def reserve(b: SerpBudget, user: UserId | None) -> bool:
    """One search as the user (named, as in a chat turn); whether it was let through."""
    with acting_as(user):
        try:
            await b.reserve(Spend(user, TODAY))
        except SearchesPaused:
            return False
        return True


# --- the caps ----------------------------------------------------------------------------------


async def test_the_month_stops_at_240_and_the_count_is_one_row_for_the_app(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    b = budget(uow)
    people = await users(uow, 30)  # eight each: none reaches their own day's limit
    for n in range(240):
        assert await reserve(b, people[n % 30])
    assert await credits(engine) == 240
    with pytest.raises(SearchesPaused) as stopped:
        await b.reserve(Spend(people[0], TODAY))
    assert stopped.value.scope == "month"
    assert stopped.value.until == date(2026, 12, 1)
    assert await credits(engine) == 240
    assert sum((await days(engine)).values()) == 240  # the refused one left no day behind


async def test_a_user_has_ten_a_day_and_the_eleventh_makes_no_count(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    b = budget(uow)
    me, you = await users(uow, 2)
    for _ in range(USER_DAILY):
        assert await reserve(b, me)
    with acting_as(me), pytest.raises(SearchesPaused) as stopped:
        await b.reserve(Spend(me, TODAY))
    assert (stopped.value.scope, stopped.value.until) == ("day", date(2026, 11, 11))
    assert await credits(engine) == USER_DAILY
    assert await reserve(b, you)
    with acting_as(me):
        await b.reserve(Spend(me, date(2026, 11, 11)))  # tomorrow is a new day
    assert await days(engine) == {me: USER_DAILY + 1, you: 1}
    assert (await credits(engine)) == USER_DAILY + 2


async def test_old_days_are_tidied_away(engine: AsyncEngine, uow: UowFactory) -> None:
    b = budget(uow)
    (me,) = await users(uow, 1)
    async with engine.begin() as db:
        await db.execute(
            text("INSERT INTO serp_searches (user_id, day, searches) VALUES (:u, :d, 4)"),
            {"u": me, "d": TODAY - timedelta(days=30)},
        )
    assert await reserve(b, me)
    assert await days(engine) == {me: 1}


async def test_a_cap_of_zero_makes_no_search(engine: AsyncEngine, uow: UowFactory) -> None:
    (me,) = await users(uow, 1)
    assert not await reserve(budget(uow, monthly=0), me)
    assert await credits(engine) is None
    assert await days(engine) == {}


# --- at the same moment ------------------------------------------------------------------------


async def test_searches_at_the_same_moment_never_pass_the_monthly_cap(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    b = budget(uow, monthly=20)
    people = await users(uow, 6)
    asking = [reserve(b, people[n % 6]) for n in range(60)]  # ten each, all at once
    allowed = await asyncio.gather(*asking)
    assert sum(allowed) == 20
    assert await credits(engine) == 20
    # Every refused search rolled its user's day back with it.
    assert sum((await days(engine)).values()) == 20


async def test_one_user_asking_at_the_same_moment_gets_ten(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    b = budget(uow)
    (me,) = await users(uow, 1)
    allowed = await asyncio.gather(*(reserve(b, me) for _ in range(40)))
    assert sum(allowed) == USER_DAILY
    assert await credits(engine) == USER_DAILY
    assert await days(engine) == {me: USER_DAILY}


async def test_the_researcher_and_the_chat_share_the_month_at_the_same_moment(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    b = budget(uow, monthly=15)
    people = await users(uow, 3)
    asking = [reserve(b, people[n % 3]) for n in range(30)] + [reserve(b, None) for _ in range(30)]
    allowed = await asyncio.gather(*asking)
    assert sum(allowed) == 15
    assert await credits(engine) == 15


# --- row-level security --------------------------------------------------------------------------


async def test_a_user_cannot_see_or_write_another_users_day(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    b = budget(uow)
    me, you = await users(uow, 2)
    assert await reserve(b, me)
    async with engine.connect() as db:
        async with db.begin() as tx:
            await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(you)})
            visible: int = (
                await db.execute(text("SELECT count(*) FROM serp_searches"))
            ).scalar_one()
            assert visible == 0
            with pytest.raises(DBAPIError):
                await db.execute(
                    text("INSERT INTO serp_searches (user_id, day, searches) VALUES (:u, :d, 1)"),
                    {"u": me, "d": TODAY},
                )
            await tx.rollback()


# --- the researcher and the chat count together ---------------------------------------------


def serpapi(uow: UowFactory, monthly: int) -> tuple[SerpApiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params["engine"] == "google_shopping":
            return httpx.Response(200, json=shopping_response())
        return httpx.Response(200, json=flights_response())

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SerpApiClient(http, KEY, budget(uow, monthly)), seen


async def test_the_travel_researcher_s_searches_count_against_the_same_month(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    client, seen = serpapi(uow, monthly=3)
    travel = SerpApiTravel(client)
    prices = LivePrices(SerpApiPrices(client, lambda: NOW), uow, lambda: NOW)
    (me,) = await users(uow, 1)
    quote = await travel.flights("SIN", "BKK", date(2026, 12, 10), date(2026, 12, 17), "SGD", 1)
    assert quote is not None
    with acting_as(me):
        await prices.products(me, ProductQuery("frobnicator 2"), TODAY)
        await prices.products(me, ProductQuery("frobnicator 2"), TODAY)  # kept: not counted
    assert await credits(engine) == 2
    assert len(seen) == 2
    # The third search is the last. The researcher, too, is stopped by the chat's use of it.
    with acting_as(me):
        await prices.products(me, ProductQuery("another thing"), TODAY)
    with pytest.raises(WebSearchError):  # SearchesPaused is a WebSearchError: it falls back
        await travel.hotels("Bangkok hotels", date(2026, 12, 10), date(2026, 12, 17), "SGD", 1)
    assert await credits(engine) == 3
    assert len(seen) == 3  # no fourth request was made
    for request in seen:
        assert request.url.params["api_key"] == KEY


async def test_a_kept_answer_is_in_web_cache_without_the_key_and_costs_nothing_again(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    client, seen = serpapi(uow, monthly=10)
    prices = LivePrices(SerpApiPrices(client, lambda: NOW), uow, lambda: NOW)
    (me,) = await users(uow, 1)
    with acting_as(me):
        first = await prices.products(me, ProductQuery("frobnicator 2"), TODAY)
        second = await prices.products(me, ProductQuery("frobnicator 2"), TODAY)
    assert first == second
    assert len(seen) == 1
    assert await credits(engine) == 1
    async with engine.connect() as db:
        rows = (await db.execute(text("SELECT key, body::text AS body FROM web_cache"))).all()
    assert len(rows) == 1
    assert len(rows[0].key) == 64
    assert KEY not in rows[0].body
    assert "api_key" not in rows[0].body


# --- migration 0070 ------------------------------------------------------------------------------


async def tables(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        async with engine.connect() as db:
            found = await db.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {r.tablename for r in found}
    finally:
        await engine.dispose()


async def test_the_migration_adds_and_removes_the_table_with_its_policy(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0069")
    assert "serp_searches" not in await tables(empty_database_url)
    await upgrade(empty_database_url, "0070")
    assert "serp_searches" in await tables(empty_database_url)
    engine = make_engine(empty_database_url)
    try:
        async with engine.connect() as db:
            policies: list[str] = list(
                (
                    await db.execute(
                        text("SELECT policyname FROM pg_policies WHERE tablename = 'serp_searches'")
                    )
                ).scalars()
            )
            secured: bool = (
                await db.execute(
                    text("SELECT relrowsecurity FROM pg_class WHERE relname = 'serp_searches'")
                )
            ).scalar_one()
        assert policies == ["nexus_user_rows"]
        assert secured is True
    finally:
        await engine.dispose()
    await downgrade(empty_database_url, "0069")
    assert "serp_searches" not in await tables(empty_database_url)
    await upgrade(empty_database_url, "head")  # and up again
    assert "serp_searches" in await tables(empty_database_url)


# --- wiring -----------------------------------------------------------------------------------


async def test_the_app_builds_the_searches_only_with_a_key_and_counts_them_from_its_setting(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"organic_results": []})

    # No request leaves the test: the client the app builds is given a made-up network.
    monkeypatch.setattr(
        "nexus.main.timed_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(no_network)),
    )
    async with AsyncExitStack() as stack:
        settings = Settings(database_url="postgresql://u:p@db/nexus", _env_file=None)
        assert await _serp(settings, Overrides(), engine, stack, lambda: NOW) is None
        keyed = settings.model_copy(
            update={"serpapi_api_key": SecretStr(KEY), "serpapi_monthly_searches": 1}
        )
        serp = await _serp(keyed, Overrides(), engine, stack, lambda: NOW)
        assert serp is not None
        assert isinstance(serp.prices, LivePrices)
        # The researcher's client and the chat's prices are held to the one monthly count.
        assert await serp.client.get({"engine": "google", "q": "x"}, Spend()) == {
            "organic_results": []
        }
        assert await credits(engine) == 1
        with pytest.raises(SearchesPaused):
            await serp.client.get({"engine": "google", "q": "x"}, Spend())
        assert await credits(engine) == 1
        given = Overrides(live_prices=CannedPrices(NOW))
        other = await _serp(keyed, given, engine, stack, lambda: NOW)
        assert other is not None
        assert other.prices is given.live_prices
