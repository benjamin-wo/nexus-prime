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


def test_access_logs_drop_secret_query_strings() -> None:
    import logging

    from nexus.infra.logs import RedactQueries

    def line(path: str) -> object:
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
            ("1.2.3.4:5", "GET", path, "1.1", 303), None,
        )  # fmt: skip
        RedactQueries().filter(record)
        return record.args[2]  # type: ignore[index]

    assert line("/api/email/gmail/callback?state=t&code=4/secret") == "/api/email/gmail/callback?…"
    assert line("/connect/gmail?t=token") == "/connect/gmail?…"
    assert line("/api/transactions?limit=5") == "/api/transactions?limit=5"


def test_app_logs_are_json_lines_with_a_level() -> None:
    import json
    import logging

    from nexus.infra.logs import JsonLines

    record = logging.LogRecord("nexus.x", logging.INFO, __file__, 1, "read %d", (3,), None)
    assert json.loads(JsonLines().format(record)) == {"level": "info", "message": "nexus.x: read 3"}


def test_uvicorn_lines_go_out_as_json_not_stderr() -> None:
    import logging
    import sys

    from nexus.infra.logs import JsonLines, configure_logging

    server = logging.getLogger("uvicorn.error")
    before = server.handlers
    try:
        server.handlers = [logging.StreamHandler(sys.stderr)]
        configure_logging()
        configure_logging()  # idempotent
        [handler] = server.handlers
        assert isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout
        assert isinstance(handler.formatter, JsonLines)
    finally:
        server.handlers = before


def test_a_turn_is_logged_with_what_it_did_never_what_was_said() -> None:
    import logging

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from nexus.agent.service import SLOW_TURN_SECONDS, _log_turn

    new = [
        HumanMessage(content="lunch at foodcourt abc 6.50"),
        AIMessage(content="", tool_calls=[{"name": "add_expense", "args": {}, "id": "c1"}]),
        ToolMessage(content="ok", tool_call_id="c1"),
        AIMessage(content="Logged."),
    ]
    seen: list[logging.LogRecord] = []
    logger = logging.getLogger("nexus.agent.service")
    handler = logging.Handler()
    handler.emit = seen.append  # type: ignore[method-assign,assignment]
    logger.addHandler(handler)
    level = logger.level
    logger.setLevel(logging.INFO)
    try:
        _log_turn(2.0, new)
        _log_turn(SLOW_TURN_SECONDS + 1, new)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
    quick, slow = seen
    assert quick.levelno == logging.INFO and slow.levelno == logging.WARNING
    assert quick.getMessage() == "turn took 2.0s: 2 model calls, tools: add_expense"
    assert all("foodcourt" not in r.getMessage() for r in seen)
