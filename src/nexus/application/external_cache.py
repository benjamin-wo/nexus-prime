"""Answers from outside services (trip weather) kept in the database, so a deploy
doesn't empty the in-memory caches in front of them.

Each answer is kept for as long as its in-memory cache keeps it. It is shared by all users
and holds nothing of anyone's: the key is a hash of what was asked (a place name, or
coordinates and dates), and the value only the answer.

A lookup never depends on this. If the database can't be reached, is slow, or holds
something unreadable, it is logged and the outside service is asked as if nothing were kept.
"""

import asyncio
import hashlib
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from nexus.application.ports import UnitOfWork

log = logging.getLogger(__name__)

# A kept answer is only worth having if it comes faster than the outside service would.
TIMEOUT = 1.5


def _key(kind: str, ask: str) -> str:
    return hashlib.sha256(f"{kind}\0{ask}".encode()).hexdigest()


class KeptAnswers:
    def __init__(self, uow: Callable[[], UnitOfWork]) -> None:
        self._uow = uow

    async def get(self, kind: str, ask: str, now: datetime) -> tuple[Any, datetime] | None:
        """The answer kept for ``ask`` (a ``kind`` of question) and when it goes stale;
        None when there isn't one, or it can't be read. Never raises."""
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._uow() as db:
                    return await db.external_cache.cached(_key(kind, ask), now)
        except Exception:
            log.warning("couldn't read a kept %s answer", kind, exc_info=True)
            return None

    async def put(
        self, kind: str, ask: str, value: Any, expires_at: datetime, now: datetime
    ) -> None:
        """Keep ``value`` as the answer to ``ask`` until ``expires_at``. Never raises."""
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._uow() as db:
                    await db.external_cache.keep(_key(kind, ask), kind, value, expires_at, now)
                    await db.commit()
        except Exception:
            log.warning("couldn't keep a %s answer", kind, exc_info=True)
