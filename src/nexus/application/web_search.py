"""Web search for every part of Nexus that asks the web: one question in, the pages
that answer it out.

Search runs through a provider with a free monthly allowance (Tavily), whose answers
come with each page's text. Answers are kept for a day, shared by everyone, since
the pages are public and the questions carry nothing of the user's. The allowance
is shared out between products (travel, investment, general) so one can't use up
another's, and a little is held back. When a product's share is used up, or the
provider fails, the search falls back to the older one (OpenRouter's web plugin,
which returns an answer and links but no page text) rather than failing.

What comes back is someone else's text: callers treat it as data and check in code
whatever they keep (see ``domain.evidence``).
"""

import hashlib
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from nexus.application.ports import UnitOfWork

log = logging.getLogger(__name__)

KEEP_FOR = timedelta(hours=24)
# Of the monthly allowance, kept back so a busy day near the end never overruns it.
HEADROOM = Decimal("0.95")


class WebSearchError(Exception):
    """A search that failed: the caller says so rather than guessing."""


@dataclass(frozen=True, slots=True)
class WebAnswer:
    text: str  # an answer written from the results, or empty when only pages came back
    sources: list[tuple[str, str]]  # (url, title) of the pages it drew on
    usd: Decimal  # what the search cost in money
    pages: list[str] = field(default_factory=list)  # each source's text, in order, if read
    credits: int = 0  # provider credits it used
    provider: str = ""


class WebSearch(Protocol):
    async def ask(self, question: str) -> WebAnswer: ...


class Product(StrEnum):
    TRAVEL = "travel"
    INVESTMENT = "investment"
    GENERAL = "general"


SHARES: dict[Product, Decimal] = {
    Product.TRAVEL: Decimal("0.60"),
    Product.INVESTMENT: Decimal("0.25"),
    Product.GENERAL: Decimal("0.15"),
}


def allowance(monthly_credits: int, product: Product) -> int:
    """How many credits ``product`` may use a month."""
    return math.floor(Decimal(monthly_credits) * HEADROOM * SHARES[product])


def _month(now: datetime) -> date:
    return now.date().replace(day=1)


def _key(question: str) -> str:
    return hashlib.sha256(f"web-v1|{' '.join(question.split())}".encode()).hexdigest()


def _to_json(answer: WebAnswer) -> dict[str, Any]:
    return {
        "text": answer.text,
        "sources": [list(s) for s in answer.sources],
        "pages": answer.pages,
        "provider": answer.provider,
    }


def _from_json(body: dict[str, Any]) -> WebAnswer | None:
    try:
        sources = [(str(u), str(t)) for u, t in body["sources"]]
        pages = [str(p) for p in body.get("pages") or []]
        return WebAnswer(str(body["text"]), sources, Decimal(0), pages, 0, str(body["provider"]))
    except (KeyError, TypeError, ValueError):
        return None


class KeptSearch:
    """A ``WebSearch`` for one product: a kept answer if there is one, else the primary
    provider while the product's share of credits lasts, else the fallback.

    If the database can't be reached it still searches; the provider's own limit
    is the backstop (a free plan stops at its allowance rather than charging)."""

    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        product: Product,
        *,
        primary: WebSearch | None,
        fallback: WebSearch | None,
        monthly_credits: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._uow = uow
        self._product = product
        self._primary = primary
        self._fallback = fallback
        self._allowance = allowance(monthly_credits, product)
        self._clock = clock

    async def ask(self, question: str) -> WebAnswer:
        now = self._clock()
        key = _key(question)
        started = time.monotonic()
        kept = await self._cached(key, now)
        if kept is not None:
            self._log(kept, started, cached=True)
            return kept
        if self._primary is not None and await self._room(now):
            try:
                answer = await self._primary.ask(question)
            except WebSearchError as exc:
                log.warning("%s search failed, using the fallback: %s", self._product, exc)
            else:
                await self._spend(now, answer.credits)
                await self._keep(key, answer, now)
                self._log(answer, started, cached=False)
                return answer
        if self._fallback is None:
            raise WebSearchError("web search isn't available right now")
        answer = await self._fallback.ask(question)
        await self._keep(key, answer, now)
        self._log(answer, started, cached=False)
        return answer

    def _log(self, answer: WebAnswer, started: float, *, cached: bool) -> None:
        # What was searched for is left out: only how it went.
        log.info(
            "web search (%s): %s in %.1fs, %d sources, %d pages read, %d credits%s",
            self._product,
            answer.provider or "unknown",
            time.monotonic() - started,
            len(answer.sources),
            sum(1 for p in answer.pages if p),
            answer.credits,
            ", kept answer" if cached else "",
        )

    async def _cached(self, key: str, now: datetime) -> WebAnswer | None:
        try:
            async with self._uow() as db:
                body = await db.web.cached(key, now)
        except Exception:
            log.warning("couldn't read kept web answers", exc_info=True)
            return None
        return _from_json(body) if body is not None else None

    async def _keep(self, key: str, answer: WebAnswer, now: datetime) -> None:
        if not answer.sources:
            return  # nothing worth keeping
        try:
            async with self._uow() as db:
                await db.web.keep(key, _to_json(answer), now + KEEP_FOR, now)
                await db.commit()
        except Exception:
            log.warning("couldn't keep a web answer", exc_info=True)

    async def _room(self, now: datetime) -> bool:
        try:
            async with self._uow() as db:
                used = await db.web.credits(_month(now))
        except Exception:
            log.warning("couldn't read web search credits", exc_info=True)
            return True
        if used.get(self._product, 0) >= self._allowance:
            log.info("%s web search credits used up this month; using the fallback", self._product)
            return False
        return True

    async def _spend(self, now: datetime, credits: int) -> None:
        if credits <= 0:
            return
        try:
            async with self._uow() as db:
                await db.web.add_credits(_month(now), self._product, credits)
                await db.commit()
        except Exception:
            log.warning("couldn't count web search credits", exc_info=True)
