"""The budget for SerpApi searches (Google Flights, Hotels, Shopping, flight status): a hard
stop, so the free plan (250 a month) is never overrun.

One count for the whole app, kept in the database: the searches made in a calendar month
(UTC), by the trip researcher and the chat's live prices together, stopping at
``SERPAPI_MONTHLY_SEARCHES`` (240 by default, a few under the plan's 250). Each chat user
also has 10 a day. A search is counted *before* it is made, in one atomic statement (see
``SqlWebRepository.reserve_serp``), so searches at the same moment can't pass the cap
together; one that fails after being counted stays counted, which errs on the side of the
cap. A search that is kept (see ``live_prices``) is never made again, so never counted
again. If the database can't be reached, no search is made: the cap is the point.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol

from nexus.application.ports import UnitOfWork
from nexus.application.web_search import WebSearchError
from nexus.domain.ledger import UserId

log = logging.getLogger(__name__)

DEFAULT_MONTHLY = 240
USER_DAILY = 10


@dataclass(frozen=True, slots=True)
class Spend:
    """Who a search is for. ``user_id`` None is work for no one in particular (the trip
    researcher): it counts against the month only. ``day`` is the user's own date, for
    the daily limit; the UTC date if left out."""

    user_id: UserId | None = None
    day: date | None = None


class SearchesPaused(WebSearchError):
    """No search was made: this month's (or today's) allowance is used up. A
    ``WebSearchError`` so that callers that fall back when a search fails (the trip
    researcher) do so; the chat tools tell the model when it ends."""

    def __init__(self, scope: Literal["month", "day"], until: date) -> None:
        super().__init__(f"search allowance used up for the {scope}")
        self.scope = scope
        self.until = until


class Budget(Protocol):
    async def reserve(self, spend: Spend) -> None:
        """Count a search about to be made; raises ``SearchesPaused`` when it may not be."""
        ...


def first_of_next_month(now: datetime) -> date:
    today = now.astimezone(UTC).date()
    return (today.replace(day=1) + timedelta(days=32)).replace(day=1)


class SerpBudget:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        monthly: int,
        clock: Callable[[], datetime],
        daily_per_user: int = USER_DAILY,
    ) -> None:
        self._uow = uow
        self._monthly = monthly
        self._daily = daily_per_user
        self._clock = clock

    async def reserve(self, spend: Spend) -> None:
        now = self._clock()
        month = now.astimezone(UTC).date().replace(day=1)
        day = spend.day or now.astimezone(UTC).date()
        try:
            async with self._uow() as db:
                got = await db.web.reserve_serp(
                    month, self._monthly, spend.user_id, day, self._daily
                )
                if got == "ok":
                    await db.commit()
        except Exception as exc:
            # Fail closed: without the count, a search could pass the cap.
            log.warning("couldn't count a SerpApi search: %s", type(exc).__name__)
            raise WebSearchError("the search allowance can't be checked") from exc
        if got == "day":
            log.info("SerpApi searches: a user's daily limit is reached")
            raise SearchesPaused("day", day + timedelta(days=1))
        if got == "month":
            log.info("SerpApi searches: this month's allowance is used up")
            raise SearchesPaused("month", first_of_next_month(now))
