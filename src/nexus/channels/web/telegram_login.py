"""Verify a Telegram Login Widget payload.

Telegram signs the fields it returns with HMAC-SHA256, keyed by the SHA-256 of
the bot token (https://core.telegram.org/widgets/login#checking-authorization).
A payload is accepted only if the signature matches and it is recent.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

MAX_AGE = timedelta(days=1)
CLOCK_SKEW = timedelta(minutes=5)
_FIELDS = {"id", "first_name", "last_name", "username", "photo_url", "auth_date", "hash"}


class LoginRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    telegram_user_id: int
    first_name: str | None
    username: str | None


def verify_login(payload: dict[str, Any], bot_token: str, *, now: datetime) -> TelegramIdentity:
    fields = {k: str(v) for k, v in payload.items() if k in _FIELDS and v is not None}
    given = fields.pop("hash", "")
    if not given or "id" not in fields or "auth_date" not in fields:
        raise LoginRejected("incomplete login data")
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, given.lower()):
        raise LoginRejected("bad signature")
    try:
        signed_at = datetime.fromtimestamp(int(fields["auth_date"]), tz=now.tzinfo)
        telegram_user_id = int(fields["id"])
    except (ValueError, OverflowError, OSError) as exc:
        raise LoginRejected("malformed login data") from exc
    if signed_at > now + CLOCK_SKEW:
        raise LoginRejected("login is from the future")
    if now - signed_at > MAX_AGE:
        raise LoginRejected("login has expired")
    return TelegramIdentity(telegram_user_id, fields.get("first_name"), fields.get("username"))


def sign_for_tests(fields: dict[str, Any], bot_token: str) -> dict[str, Any]:
    """Build a correctly signed payload (tests and local development only)."""
    data = {k: str(v) for k, v in fields.items()}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(bot_token.encode()).digest()
    return {**data, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()}
