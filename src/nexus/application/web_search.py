"""Web search for every part of Nexus that asks the web: one question in, the pages
that answer it out.

Search runs through a provider with a free monthly allowance (Tavily), whose answers
come with each page's text. Answers are kept for a day (ten minutes for news from
today, an hour for news from this week), shared by everyone, since the pages are
public and the questions carry nothing of the user's. A search can be for recent news
and can ask the same question twice, once in the local language, at two credits. The allowance
is shared out between products (travel, investment, general) so one can't use up
another's, and a little is held back. When a product's share is used up, or the
provider fails, the search falls back to the older one (OpenRouter's web plugin,
which returns an answer and links but no page text) rather than failing.

Pages can also be read by address (``KeptReader``): the news articles behind an
investment plan's headlines. Each page is kept a day (as long as the answers for a
recent search, if it was read for one) and counted against its
product's share the same way; past it, nothing is read and the caller goes on with
what it had.

What comes back is someone else's text: callers treat it as data and check in code
whatever they keep (see ``domain.evidence``).
"""

import asyncio
import hashlib
import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from nexus.application.ports import UnitOfWork

log = logging.getLogger(__name__)

# How recent the news wanted is: the last day, or the last week. None is any time.
type Recency = Literal["today", "week"]

KEEP_FOR = timedelta(hours=24)
# News goes stale quickly: an answer about today is kept ten minutes, this week an hour.
KEEP_TODAY = timedelta(minutes=10)
KEEP_WEEK = timedelta(hours=1)
# Asking in two languages merges the results; this many pages are read in all.
MAX_MERGED = 8
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
    # When each source was published, in the order of ``sources``, where the provider says.
    published: list[datetime | None] = field(default_factory=list)


class WebSearch(Protocol):
    async def ask(self, question: str) -> WebAnswer: ...


class RecentSearch(Protocol):
    """A provider that can search for recent news; one that can't ignores ``recent``."""

    async def ask(self, question: str, recent: Recency | None = None) -> WebAnswer: ...


class LiveSearch(Protocol):
    """A search for what's happening now, perhaps asked in two languages."""

    async def ask(
        self, question: str, recent: Recency | None = None, local_query: str | None = None
    ) -> WebAnswer: ...


@dataclass(frozen=True, slots=True)
class ReadPages:
    pages: dict[str, str]  # each address read, with its text
    credits: int = 0


class Reader(Protocol):
    """Reads web pages by address; a page it couldn't read is left out."""

    async def read(self, urls: Sequence[str]) -> ReadPages: ...


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


def keep_for(recent: Recency | None) -> timedelta:
    """How long an answer (or page) found for a search of this kind is kept."""
    if recent == "today":
        return KEEP_TODAY
    return KEEP_WEEK if recent == "week" else KEEP_FOR


def _key(question: str, recent: Recency | None = None, local_query: str | None = None) -> str:
    asked = " ".join(question.split())
    if recent is None and not local_query:
        return hashlib.sha256(f"web-v1|{asked}".encode()).hexdigest()
    local = " ".join((local_query or "").split())
    return hashlib.sha256(f"web-v2|{recent or ''}|{local}|{asked}".encode()).hexdigest()


def _page_key(url: str, recent: Recency | None = None) -> str:
    # A page read for a news search is kept under its own key, for as short a time.
    return hashlib.sha256(f"page-v1|{f'{recent}|' if recent else ''}{url}".encode()).hexdigest()


def _to_json(answer: WebAnswer) -> dict[str, Any]:
    return {
        "text": answer.text,
        "sources": [list(s) for s in answer.sources],
        "pages": answer.pages,
        "provider": answer.provider,
        "published": [p.isoformat() if p is not None else None for p in answer.published],
    }


def _moment(raw: object) -> datetime | None:
    try:
        found = datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return found if found is not None and found.tzinfo is not None else None


def _from_json(body: dict[str, Any]) -> WebAnswer | None:
    try:
        sources = [(str(u), str(t)) for u, t in body["sources"]]
        pages = [str(p) for p in body.get("pages") or []]
        published = [_moment(p) for p in body.get("published") or []]
        return WebAnswer(
            str(body["text"]), sources, Decimal(0), pages, 0, str(body["provider"]), published
        )
    except (KeyError, TypeError, ValueError):
        return None


def _at[T](items: Sequence[T], i: int, otherwise: T) -> T:
    return items[i] if i < len(items) else otherwise


def _same_page(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/")


def merge(answers: Sequence[WebAnswer], limit: int = MAX_MERGED) -> WebAnswer:
    """The answers of several searches as one: sources taken in turn from each (so each
    keeps its own order and none crowds out the others), a page found twice once, with
    whatever either knew of its text and date, and no more than ``limit`` in all."""
    if len(answers) == 1 and len(answers[0].sources) <= limit:
        return answers[0]
    order: list[str] = []
    found: dict[str, tuple[str, str, str, datetime | None]] = {}
    for rank in range(max((len(a.sources) for a in answers), default=0)):
        for a in answers:
            if rank >= len(a.sources):
                continue
            url, title = a.sources[rank]
            page, when = _at(a.pages, rank, ""), _at(a.published, rank, None)
            same = _same_page(url)
            if same in found:
                _, kept_title, kept_page, kept_when = found[same]
                found[same] = (found[same][0], kept_title, kept_page or page, kept_when or when)
            elif len(order) < limit:
                order.append(same)
                found[same] = (url, title, page, when)
    rows = [found[same] for same in order]
    return WebAnswer(
        next((a.text for a in answers if a.text), ""),
        [(url, title) for url, title, _, _ in rows],
        sum((a.usd for a in answers), Decimal(0)),
        [page for _, _, page, _ in rows],
        sum(a.credits for a in answers),
        answers[0].provider if answers else "",
        [when for _, _, _, when in rows],
    )


class _Kept:
    """What's kept for one product: answers and pages for a day, and the credits it
    has used this month. If the database can't be reached, nothing is kept and the
    provider's own limit is the backstop (a free plan stops at its allowance rather
    than charging)."""

    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        product: Product,
        monthly_credits: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._uow = uow
        self._product = product
        self._allowance = allowance(monthly_credits, product)
        self._clock = clock

    async def _cached_body(self, key: str, now: datetime) -> dict[str, Any] | None:
        try:
            async with self._uow() as db:
                return await db.web.cached(key, now)
        except Exception:
            log.warning("couldn't read kept web answers", exc_info=True)
            return None

    async def _keep_body(
        self, key: str, body: dict[str, Any], now: datetime, ttl: timedelta = KEEP_FOR
    ) -> None:
        try:
            async with self._uow() as db:
                await db.web.keep(key, body, now + ttl, now)
                await db.commit()
        except Exception:
            log.warning("couldn't keep a web answer", exc_info=True)

    async def _left(self, now: datetime) -> int | None:
        """Credits the product has left this month; None if that can't be read."""
        try:
            async with self._uow() as db:
                used = await db.web.credits(_month(now))
        except Exception:
            log.warning("couldn't read web search credits", exc_info=True)
            return None
        return self._allowance - used.get(self._product, 0)

    async def _room(self, now: datetime) -> bool:
        left = await self._left(now)
        if left is not None and left <= 0:
            log.info("%s web search credits used up this month", self._product)
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


class KeptSearch(_Kept):
    """A ``LiveSearch`` for one product: a kept answer if there is one, else the primary
    provider while the product's share of credits lasts, else the fallback.

    A search for ``recent`` news is kept ten minutes (today) or an hour (this week)
    instead of a day. With a ``local_query`` (the same question in the local language)
    both are asked at once and their results merged: two credits, so when the share has
    less than two left only the main question is asked. The fallback gets the main
    question alone and can't filter by date."""

    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        product: Product,
        *,
        primary: RecentSearch | None,
        fallback: RecentSearch | None,
        monthly_credits: int,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(uow, product, monthly_credits, clock)
        self._primary = primary
        self._fallback = fallback

    async def ask(
        self, question: str, recent: Recency | None = None, local_query: str | None = None
    ) -> WebAnswer:
        now = self._clock()
        local = " ".join((local_query or "").split())
        if local.casefold() == " ".join(question.split()).casefold():
            local = ""  # the same words twice would cost a credit for nothing
        key = _key(question, recent, local)
        ttl = keep_for(recent)
        started = time.monotonic()
        body = await self._cached_body(key, now)
        kept = _from_json(body) if body is not None else None
        if kept is not None:
            self._log(kept, started, cached=True)
            return kept
        if self._primary is not None:
            answer = await self._search(self._primary, question, recent, local, now)
            if answer is not None:
                await self._spend(now, answer.credits)
                await self._keep(key, answer, now, ttl)
                self._log(answer, started, cached=False)
                return answer
        if self._fallback is None:
            raise WebSearchError("web search isn't available right now")
        answer = await self._fallback.ask(question, recent)
        await self._keep(key, answer, now, ttl)
        self._log(answer, started, cached=False)
        return answer

    async def _search(
        self,
        primary: RecentSearch,
        question: str,
        recent: Recency | None,
        local: str,
        now: datetime,
    ) -> WebAnswer | None:
        """The primary provider's answer, or None to fall back: no credits left, or it
        failed. The local-language question is asked only if two credits are left."""
        left = await self._left(now)
        if left is not None and left <= 0:
            log.info("%s web search credits used up this month", self._product)
            return None
        asking = [question]
        if local:
            if left is None or left >= 2:
                asking.append(local)
            else:
                log.info("%s web search: one credit left, skipping the local query", self._product)
        results = await asyncio.gather(
            *(primary.ask(q, recent) for q in asking), return_exceptions=True
        )
        answers: list[WebAnswer] = []
        for result in results:
            if isinstance(result, WebSearchError):
                log.warning("%s search failed, using what else there is: %s", self._product, result)
            elif isinstance(result, BaseException):
                raise result
            else:
                answers.append(result)
        return merge(answers) if answers else None

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

    async def _keep(
        self, key: str, answer: WebAnswer, now: datetime, ttl: timedelta = KEEP_FOR
    ) -> None:
        if answer.sources:  # an answer with no sources isn't worth keeping
            await self._keep_body(key, _to_json(answer), now, ttl)


class KeptReader(_Kept):
    """Reads pages by address for one product: a page kept from the last day if there
    is one, else the reader while the product's share of credits lasts. A page that
    couldn't be read is kept as unreadable for the day, so it isn't tried again on
    every run. Never raises: what couldn't be read is left out."""

    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        product: Product,
        *,
        reader: Reader,
        monthly_credits: int,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(uow, product, monthly_credits, clock)
        self._reader = reader

    async def read(self, urls: Sequence[str], recent: Recency | None = None) -> dict[str, str]:
        """The pages' text. Read for a ``recent`` news search, a page is kept only as
        long as that search's answers are, so fresh news is never served stale."""
        now = self._clock()
        ttl = keep_for(recent)
        started = time.monotonic()
        wanted = list(dict.fromkeys(urls))
        pages: dict[str, str] = {}
        missing: list[str] = []
        for url in wanted:
            body = await self._cached_body(_page_key(url, recent), now)
            if body is None:
                missing.append(url)
            elif isinstance(body.get("text"), str) and body["text"]:
                pages[url] = body["text"]
        read = ReadPages({})
        if missing and await self._room(now):
            try:
                read = await self._reader.read(missing)
            except WebSearchError as exc:
                log.warning("%s page reading failed: %s", self._product, exc)
            else:
                await self._spend(now, read.credits)
                for url in missing:
                    text = read.pages.get(url, "")
                    await self._keep_body(_page_key(url, recent), {"text": text}, now, ttl)
                    if text:
                        pages[url] = text
        log.info(
            "pages read (%s): %d of %d in %.1fs, %d kept, %d credits",
            self._product,
            len(pages),
            len(wanted),
            time.monotonic() - started,
            len(wanted) - len(missing),
            read.credits,
        )
        return pages
