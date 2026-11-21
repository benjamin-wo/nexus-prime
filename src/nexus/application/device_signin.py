"""Signing in from the iOS app: a short code the person approves in Telegram.

The app's WebView can't use the Telegram login widget or the bot's /web link (both open outside
it), so the app asks for a code (``start``), shows it, and polls with a separate secret
(``poll_id``). In Telegram the person sends the code to the bot (``claim``), the bot asks "is this
you?", and only the same Telegram user's Yes (``approve``) lets the poll collect a sign-in.

Kept in memory, with an expiry: the app runs as ONE process (the Dockerfile starts a single
uvicorn worker), so the bot's webhook and the web API see the same store. With more than one
process this would have to move to the database. A restart forgets pending codes; the app asks
again. Only SHA-256 hashes of the code and the poll id are held, never the values themselves, and
the store is bounded (expired entries go first; when it is full, no new code is handed out).
"""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from nexus.domain.ledger import UserId

DEVICE_CODE_TTL = timedelta(minutes=5)
MAX_PENDING = 10_000
# No 0/O, 1/I/L: a code is read off a screen and typed.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalise_code(raw: str) -> str | None:
    """``abcd-efgh`` / ``ABCD EFGH`` -> ``ABCDEFGH``; None when it can't be a code."""
    code = "".join(ch for ch in raw.upper() if ch not in "- ")
    if len(code) != CODE_LENGTH or any(ch not in ALPHABET for ch in code):
        return None
    return code


def display_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


@dataclass(frozen=True, slots=True)
class Started:
    code: str  # normalised, 8 characters
    poll_id: str
    expires_in: int  # seconds


@dataclass(frozen=True, slots=True)
class Pending:
    pass


@dataclass(frozen=True, slots=True)
class Approved:
    user_id: UserId


@dataclass(slots=True)
class _Entry:
    poll_hash: str
    expires_at: datetime
    claimed_by: int | None = None  # the Telegram user who sent the code to the bot
    approved_for: UserId | None = None


class StoreFull(Exception):
    """Too many pending codes to hand out another."""


class DeviceSignin:
    def __init__(self, clock: Callable[[], datetime], capacity: int = MAX_PENDING) -> None:
        self._clock = clock
        self._capacity = capacity
        self._by_code: dict[str, _Entry] = {}
        self._code_of_poll: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._by_code)

    def _drop(self, code_hash: str) -> None:
        entry = self._by_code.pop(code_hash, None)
        if entry is not None:
            self._code_of_poll.pop(entry.poll_hash, None)

    def _sweep(self) -> None:
        now = self._clock()
        for key in [k for k, e in self._by_code.items() if e.expires_at <= now]:
            self._drop(key)

    def _live(self, code_hash: str) -> _Entry | None:
        entry = self._by_code.get(code_hash)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._drop(code_hash)
            return None
        return entry

    def start(self) -> Started:
        self._sweep()
        if len(self._by_code) >= self._capacity:
            raise StoreFull
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            if _hash(code) not in self._by_code:
                break
        poll_id = secrets.token_urlsafe(32)
        entry = _Entry(_hash(poll_id), self._clock() + DEVICE_CODE_TTL)
        self._by_code[_hash(code)] = entry
        self._code_of_poll[entry.poll_hash] = _hash(code)
        return Started(code, poll_id, int(DEVICE_CODE_TTL.total_seconds()))

    def knows_poll(self, poll_id: str) -> bool:
        code_hash = self._code_of_poll.get(_hash(poll_id))
        return code_hash is not None and self._live(code_hash) is not None

    def claim(self, raw_code: str, telegram_user_id: int) -> str | None:
        """The bot got this code from this Telegram user. Returns the normalised code if it is
        live and not already claimed by someone else; None otherwise (the caller must not say
        which)."""
        code = normalise_code(raw_code)
        entry = self._live(_hash(code)) if code else None
        if code is None or entry is None or entry.approved_for is not None:
            return None
        if entry.claimed_by not in (None, telegram_user_id):
            return None
        entry.claimed_by = telegram_user_id
        return code

    def approve(self, raw_code: str, telegram_user_id: int, user_id: UserId) -> bool:
        """The Yes press. Only the Telegram user who claimed the code may approve it."""
        code = normalise_code(raw_code)
        entry = self._live(_hash(code)) if code else None
        if entry is None or entry.claimed_by != telegram_user_id or entry.approved_for:
            return False
        entry.approved_for = user_id
        return True

    def deny(self, raw_code: str, telegram_user_id: int) -> bool:
        """The No press: the code is spent. Only the claimer can cancel it."""
        code = normalise_code(raw_code)
        entry = self._live(_hash(code)) if code else None
        if code is None or entry is None or entry.claimed_by != telegram_user_id:
            return False
        self._drop(_hash(code))
        return True

    def poll(self, poll_id: str) -> Pending | Approved | None:
        """None when unknown or expired. An approval is handed over once: the request is
        deleted as it is read."""
        code_hash = self._code_of_poll.get(_hash(poll_id))
        entry = self._live(code_hash) if code_hash else None
        if code_hash is None or entry is None:
            return None
        if entry.approved_for is None:
            return Pending()
        self._drop(code_hash)
        return Approved(entry.approved_for)
