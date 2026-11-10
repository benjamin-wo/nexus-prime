"""Live fares, product prices and flight status for the chat, from Google through SerpApi.

Each lookup is one SerpApi search, which costs part of a small allowance (see
``serp_budget``). So a request that was made in the last six hours, the same in every
detail, is answered from what was kept and costs nothing. What's kept is in ``web_cache``
(the table web search answers are kept in), not in memory: it survives a restart and is
shared by every user, and the prices are public. It is the parsed answer, never the request
(the key is in the request and goes nowhere near the database).

Where a lookup is made, the allowance is counted before the search (so the monthly cap and
the user's ten a day hold under any number of searches at once) and a used-up allowance
raises ``SearchesPaused``: no search is made, and the chat tool tells the model when
live prices are back.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from pydantic import TypeAdapter, ValidationError

from nexus.application.ports import UnitOfWork
from nexus.application.serp_budget import Spend
from nexus.domain.ledger import UserId
from nexus.domain.live_prices import (
    CalendarQuery,
    FareCalendar,
    FlightFares,
    FlightQuery,
    FlightStatus,
    ProductPrices,
    ProductQuery,
    StatusQuery,
)

log = logging.getLogger(__name__)

KEEP_FOR = timedelta(hours=6)
# A flight's status changes by the minute: kept only long enough that asking again at once
# (or twice in one conversation) costs nothing.
KEEP_STATUS_FOR = timedelta(minutes=15)
_VERSION = "serp-v1"


class PriceSource(Protocol):
    """Makes one search for each kind of lookup (SerpApi's, or the evals' canned one)."""

    async def flights(self, q: FlightQuery, spend: Spend) -> FlightFares: ...
    async def calendar(self, q: CalendarQuery, spend: Spend) -> FareCalendar: ...
    async def products(self, q: ProductQuery, spend: Spend) -> ProductPrices: ...
    async def status(self, q: StatusQuery, spend: Spend) -> FlightStatus: ...


class PriceLooker(Protocol):
    """What the chat tools need: the lookups, for a user on their own date."""

    async def flights(self, user: UserId, q: FlightQuery, today: date) -> FlightFares: ...
    async def calendar(self, user: UserId, q: CalendarQuery, today: date) -> FareCalendar: ...
    async def products(self, user: UserId, q: ProductQuery, today: date) -> ProductPrices: ...
    async def status(self, user: UserId, q: StatusQuery, today: date) -> FlightStatus: ...


def _key(kind: str, query: Any) -> str:
    """The same request in every detail has the same key: a hash of what was asked, which
    holds nothing of the user's and, being built here, never the API key."""
    body = json.dumps(asdict(query), sort_keys=True, default=str)
    return hashlib.sha256(f"{_VERSION}|{kind}|{body}".encode()).hexdigest()


class LivePrices:
    def __init__(
        self,
        source: PriceSource,
        uow: Callable[[], UnitOfWork],
        clock: Callable[[], datetime],
    ) -> None:
        self._source = source
        self._uow = uow
        self._clock = clock

    async def _kept[T](self, kind: str, query: Any, shape: type[T]) -> T | None:
        try:
            async with self._uow() as db:
                body = await db.web.cached(_key(kind, query), self._clock())
        except Exception:
            log.warning("couldn't read kept live prices", exc_info=True)
            return None
        if body is None or body.get("v") != _VERSION:
            return None
        try:
            return TypeAdapter(shape).validate_python(body.get("result"))
        except ValidationError:
            return None

    async def _keep[T](
        self, kind: str, query: Any, result: T, shape: type[T], ttl: timedelta = KEEP_FOR
    ) -> None:
        now = self._clock()
        body: dict[str, Any] = {
            "v": _VERSION,
            "result": TypeAdapter(shape).dump_python(result, mode="json"),
        }
        try:
            async with self._uow() as db:
                await db.web.keep(_key(kind, query), body, now + ttl, now)
                await db.commit()
        except Exception:
            log.warning("couldn't keep live prices", exc_info=True)

    async def flights(self, user: UserId, q: FlightQuery, today: date) -> FlightFares:
        kept = await self._kept("flights", q, FlightFares)
        if kept is not None:
            return kept
        found = await self._source.flights(q, Spend(user, today))
        await self._keep("flights", q, found, FlightFares)
        return found

    async def calendar(self, user: UserId, q: CalendarQuery, today: date) -> FareCalendar:
        kept = await self._kept("calendar", q, FareCalendar)
        if kept is not None:
            return kept
        found = await self._source.calendar(q, Spend(user, today))
        await self._keep("calendar", q, found, FareCalendar)
        return found

    async def products(self, user: UserId, q: ProductQuery, today: date) -> ProductPrices:
        kept = await self._kept("products", q, ProductPrices)
        if kept is not None:
            return kept
        found = await self._source.products(q, Spend(user, today))
        await self._keep("products", q, found, ProductPrices)
        return found

    async def status(self, user: UserId, q: StatusQuery, today: date) -> FlightStatus:
        kept = await self._kept("status", q, FlightStatus)
        if kept is not None:
            return kept
        found = await self._source.status(q, Spend(user, today))
        await self._keep("status", q, found, FlightStatus, KEEP_STATUS_FOR)
        return found
