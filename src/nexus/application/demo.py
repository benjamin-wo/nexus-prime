"""The public live demo: a visitor gets a private account of their own, filled with made-up
data and signed in at once, with no Telegram.

A demo account is an ordinary member (never the owner) with web access, a made-up negative
Telegram id (real ones are positive, so it can never be anyone's) and no chat, so nothing can
ever be sent to Telegram for it. It lasts 24 hours and is then erased by a job. It has small
allowances (``MESSAGES``, ``VOICE``, ``PHOTOS``, counted in the database) and, together with
every other demo, a daily spend cap (``DAILY_CAP``). Anything that would reach outside the app
for someone else (Telegram, email, invites, shared links) is refused (``forbid``).
"""

import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from nexus.application import demo_seed
from nexus.application.access import LoggedIn
from nexus.application.ports import UnitOfWork
from nexus.application.users import RegisterUser, ensure_user
from nexus.domain.access import Session, new_token, token_hash
from nexus.domain.demo import NEXT_STEP
from nexus.domain.ledger import Role, User, UserId

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

DEMO_TTL = timedelta(hours=24)
DISPLAY_NAME = "Demo"
HOME_CURRENCY = "SGD"
TIMEZONE = "Asia/Singapore"

# What one demo account may do.
MESSAGES = 50
VOICE = 5
PHOTOS = 5
# What all demos together may cost in model calls in one UTC day (US dollars).
DAILY_CAP = Decimal("2.00")
# Accounts erased per clean-up run: a backlog is cleared over a few runs.
PURGE_BATCH = 50


class Use(StrEnum):
    MESSAGE = "message"
    VOICE = "voice"
    PHOTO = "photo"


ALLOWANCE = {Use.MESSAGE: MESSAGES, Use.VOICE: VOICE, Use.PHOTO: PHOTOS}
LIMIT_REACHED = {
    Use.MESSAGE: f"The demo limit is reached: a demo includes {MESSAGES} chat messages. "
    f"{NEXT_STEP}",
    Use.VOICE: f"The demo limit is reached: a demo includes {VOICE} voice notes. {NEXT_STEP}",
    Use.PHOTO: f"The demo limit is reached: a demo includes {PHOTOS} photos or PDFs. {NEXT_STEP}",
}
CAP_REACHED = (
    "The demo limit is reached for today: demos share a small daily budget, and it is used up. "
    f"Please try again tomorrow. {NEXT_STEP}"
)
DEMO_OFF = "demo_off"
BUSY = "Too many demos were started from your network just now. Try again in an hour."


class DemoUnavailable(Exception):
    """A demo account could not be made (filling it failed); it has been erased."""


@dataclass(frozen=True, slots=True)
class DemoUsage:
    """How much of its allowances a demo account has used."""

    messages: int
    voice: int
    photos: int

    @property
    def messages_left(self) -> int:
        return max(0, MESSAGES - self.messages)


class DemoGate(Protocol):
    """Counts a demo account's use of what costs money, and says no past the allowance."""

    async def use(
        self, user_id: UserId, kind: Use | None, amount: int = 1, *, count: bool = True
    ) -> str | None:
        """None when the user is not a demo account, or may do this. Otherwise the plain
        sentence to tell them: their allowance for ``kind`` is used up, or the daily spend
        cap of all demos is reached (that one is checked for ``kind=None`` too). ``amount``
        uses are counted unless ``count`` is false (a check only)."""
        ...

    async def usage(self, user_id: UserId) -> DemoUsage | None:
        """A demo account's counts; None for anyone else."""
        ...


def made_up_telegram_id() -> int:
    """A negative 62-bit number: never a real Telegram id, which are positive."""
    return -(1 + secrets.randbelow(2**62))


async def _create(uow: UowFactory, *, now: datetime, expires_at: datetime) -> User:
    for _ in range(5):  # a collision of 62 random bits is not going to happen; but never loop
        async with uow() as tx:
            registration = await ensure_user(
                tx.ledger,
                RegisterUser(
                    telegram_user_id=made_up_telegram_id(),
                    home_currency=HOME_CURRENCY,
                    telegram_chat_id=None,
                    timezone=TIMEZONE,
                    role=Role.MEMBER,
                    demo_expires_at=expires_at,
                ),
            )
            if not registration.created:
                continue
            user = registration.user
            await tx.ledger.grant_web_access(user.id, now)
            await tx.ledger.set_display_name(user.id, DISPLAY_NAME)
            await tx.ledger.record_demo_start(now.astimezone(UTC).date())
            await tx.commit()
            made = await tx.ledger.get_user(user.id)
        if made is None:  # pragma: no cover - just made
            raise RuntimeError("demo user vanished")
        return made
    raise RuntimeError("could not find a free demo id")  # pragma: no cover


async def start_demo(
    uow: UowFactory, *, now: datetime, erase: Callable[[User], Awaitable[None]]
) -> LoggedIn:
    """Make a demo account, fill it with made-up data and open a session that ends with it.
    The session only exists once the data is in; if filling it fails, the account is erased
    (``erase``) and ``DemoUnavailable`` is raised."""
    expires_at = now + DEMO_TTL
    user = await _create(uow, now=now, expires_at=expires_at)
    try:
        await demo_seed.seed_demo(uow, user, now=now)
    except Exception as exc:
        log.exception("could not fill a new demo account")
        try:
            await erase(user)
        except Exception:
            log.exception("could not erase a demo account that failed to start")
        raise DemoUnavailable from exc
    token = new_token()
    session = Session(token_hash(token), user.id, new_token(), now, expires_at)
    async with uow() as tx:
        await tx.ledger.insert_session(session)
        await tx.commit()
    return LoggedIn(token, session, user)


async def purge_expired(
    uow: UowFactory, *, now: datetime, erase: Callable[[User], Awaitable[None]]
) -> int:
    """Erase the demo accounts whose time is up, everything of theirs. One failing never
    stops the others; the next run tries it again. Returns how many were erased."""
    async with uow() as tx:
        expired = await tx.ledger.expired_demo_users(now, limit=PURGE_BATCH)
    erased = 0
    for user in expired:
        try:
            await erase(user)
            erased += 1
        except Exception:
            log.exception("could not erase an expired demo account")
    return erased
