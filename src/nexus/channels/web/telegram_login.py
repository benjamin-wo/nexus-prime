"""Verify Telegram sign-ins: the Login Widget payload and Mini App init data.

The Login Widget signs its fields with HMAC-SHA256 keyed by the SHA-256 of the
bot token (https://core.telegram.org/widgets/login#checking-authorization).
A Mini App's init data is signed with a key derived as HMAC-SHA256("WebAppData",
bot token) (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).
Either is accepted only if the signature matches and it is recent.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

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
    _check_age(signed_at, now)
    return TelegramIdentity(telegram_user_id, fields.get("first_name"), fields.get("username"))


def _check_age(signed_at: datetime, now: datetime) -> None:
    if signed_at > now + CLOCK_SKEW:
        raise LoginRejected("login is from the future")
    if now - signed_at > MAX_AGE:
        raise LoginRejected("login has expired")


def _webapp_hash(fields: dict[str, str], bot_token: str) -> str:
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def verify_webapp(init_data: str, bot_token: str, *, now: datetime) -> TelegramIdentity:
    """Check a Mini App's ``Telegram.WebApp.initData`` query string."""
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise LoginRejected("malformed init data") from exc
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise LoginRejected("malformed init data")
    given = fields.pop("hash", "")
    if not given or "user" not in fields or "auth_date" not in fields:
        raise LoginRejected("incomplete init data")
    if not hmac.compare_digest(_webapp_hash(fields, bot_token), given.lower()):
        raise LoginRejected("bad signature")
    try:
        signed_at = datetime.fromtimestamp(int(fields["auth_date"]), tz=now.tzinfo)
        user = json.loads(fields["user"])
        telegram_user_id = int(user["id"])
    except (ValueError, OverflowError, OSError, TypeError, KeyError) as exc:
        raise LoginRejected("malformed init data") from exc
    _check_age(signed_at, now)
    first_name, username = user.get("first_name"), user.get("username")
    return TelegramIdentity(
        telegram_user_id,
        first_name if isinstance(first_name, str) else None,
        username if isinstance(username, str) else None,
    )


def sign_for_tests(fields: dict[str, Any], bot_token: str) -> dict[str, Any]:
    """Build a correctly signed payload (tests and local development only)."""
    data = {k: str(v) for k, v in fields.items()}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(bot_token.encode()).digest()
    return {**data, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()}


def sign_webapp_for_tests(fields: dict[str, str], bot_token: str) -> str:
    """Build correctly signed Mini App init data (tests only)."""
    from urllib.parse import urlencode

    return urlencode({**fields, "hash": _webapp_hash(fields, bot_token)})
