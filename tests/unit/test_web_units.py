from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from nexus.channels.web.csv_export import neutralise, to_csv
from nexus.channels.web.telegram_login import LoginRejected, sign_for_tests, verify_login
from nexus.domain.ledger import Direction, Source, Transaction, TransactionStatus, UserId
from nexus.domain.money import Money

TOKEN = "123:secret"
NOW = datetime(2026, 9, 28, 4, tzinfo=UTC)


def payload(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "id": 42,
        "first_name": "Ben",
        "username": "ben",
        "auth_date": int(NOW.timestamp()),
    }
    fields.update(overrides)
    return sign_for_tests(fields, TOKEN)


def test_accepts_a_signed_recent_login() -> None:
    identity = verify_login(payload(), TOKEN, now=NOW)
    assert identity.telegram_user_id == 42 and identity.username == "ben"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda p: {**p, "id": "43"}, "bad signature"),
        (lambda p: {**p, "hash": "0" * 64}, "bad signature"),
        (lambda p: {k: v for k, v in p.items() if k != "hash"}, "incomplete"),
        (lambda p: {k: v for k, v in p.items() if k != "id"}, "incomplete"),
    ],
)
def test_rejects_tampered_or_incomplete(mutate: object, reason: str) -> None:
    with pytest.raises(LoginRejected, match=reason):
        verify_login(mutate(payload()), TOKEN, now=NOW)  # type: ignore[operator]


def test_rejects_other_bots_expired_and_future_logins() -> None:
    with pytest.raises(LoginRejected, match="signature"):
        verify_login(payload(), "999:other", now=NOW)
    old = payload(auth_date=int((NOW - timedelta(days=1, minutes=1)).timestamp()))
    with pytest.raises(LoginRejected, match="expired"):
        verify_login(old, TOKEN, now=NOW)
    future = payload(auth_date=int((NOW + timedelta(minutes=10)).timestamp()))
    with pytest.raises(LoginRejected, match="future"):
        verify_login(future, TOKEN, now=NOW)


def test_ignores_unsigned_extra_fields() -> None:
    assert verify_login({**payload(), "role": "owner"}, TOKEN, now=NOW).telegram_user_id == 42


@pytest.mark.parametrize("value", ["=HYPERLINK(1)", "+1", "-2", "@SUM(A1)", "\tx", "\rx"])
def test_neutralises_formulas(value: str) -> None:
    assert neutralise(value) == "'" + value


def test_csv_rows() -> None:
    tx = Transaction(
        id=uuid4(),
        user_id=UserId(uuid4()),
        direction=Direction.OUT,
        amount=Money.of("5.5", "SGD"),
        occurred_at=NOW,
        counterparty="=cmd|' /C calc'!A0",
        category_id=None,
        notes='says "hi", ok',
        status=TransactionStatus.CONFIRMED,
        source=Source.TEXT,
        created_at=NOW,
        updated_at=NOW,
    )
    text = to_csv([tx], {}, ZoneInfo("Asia/Singapore"), "SGD", {})
    header, row, _ = text.split("\r\n")
    assert header == (
        "date,direction,amount,currency,home_amount,home_currency,fx_rate,fx_rate_date,"
        "counterparty,category,notes,status,source"
    )
    assert row == (
        "2026-09-28,out,5.5000,SGD,5.5000,SGD,,,"
        '\'=cmd|\' /C calc\'!A0,,"says ""hi"", ok",confirmed,text'
    )
