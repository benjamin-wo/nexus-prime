"""M3 import from the pre-rebuild schema into the new one."""

import json
from collections.abc import AsyncIterator
from decimal import Decimal

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from nexus.application.ports import LedgerQuery
from nexus.application.splits import list_open_ious
from nexus.application.transactions import NewTransaction, list_ledger, log_transaction
from nexus.application.users import find_telegram_user
from nexus.domain.errors import DuplicateSource
from nexus.domain.ledger import Direction, Source, TransactionStatus
from nexus.domain.money import Money
from nexus.legacy import __main__ as cli
from nexus.legacy.importer import import_legacy
from nexus.legacy.reader import LegacySchemaError, read_legacy
from tests.conftest import throwaway_database
from tests.fakes import NOW
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

OWNER, FRIEND = 111, 222

# The old SQLModel tables, as the live database had them (plus a drifted extra column).
LEGACY_DDL = """
CREATE TABLE userprofile (user_id BIGINT PRIMARY KEY, telegram_chat_id BIGINT,
  current_timezone VARCHAR, home_currency VARCHAR, whiteboard_seeded BOOLEAN);
CREATE TABLE expensetransaction (id SERIAL PRIMARY KEY, user_id BIGINT, amount FLOAT,
  currency VARCHAR, merchant VARCHAR, category VARCHAR, date TIMESTAMP,
  source_message_id VARCHAR, is_verified BOOLEAN, notes VARCHAR, split_data JSON);
CREATE TABLE incometransaction (id SERIAL PRIMARY KEY, user_id BIGINT, amount FLOAT,
  currency VARCHAR, source VARCHAR, category VARCHAR, date TIMESTAMP, notes VARCHAR,
  source_message_id VARCHAR, linked_expense_id INT);
CREATE TABLE deletedexpensemessage (id SERIAL PRIMARY KEY, user_id BIGINT,
  source_message_id VARCHAR);
CREATE TABLE taskitem (id SERIAL PRIMARY KEY, user_id BIGINT, title VARCHAR, status VARCHAR,
  linked_expense_id INT, iou_friend VARCHAR, iou_amount FLOAT);
"""


def dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture
async def legacy() -> AsyncIterator[asyncpg.Connection]:
    async with throwaway_database() as url:
        conn = await asyncpg.connect(dsn(url))
        try:
            await conn.execute(LEGACY_DDL)
            await conn.execute(
                "INSERT INTO userprofile VALUES ($1,$1,'Asia/Singapore','SGD',true),"
                "($2,$2,'Mars/Base','sgd',false)",
                OWNER,
                FRIEND,
            )
            split = {
                "friends": ["Me", "Ann", "Ben"],
                "share_amounts": {"Ann": 30.0, "Ben": 30.0},
                "paid_amounts": {"Ann": 30.0, "Ben": 10.0},
                "paid_status": {"Ann": True, "Ben": False},
            }
            rows = [
                # id 1: dinner split three ways; Ann repaid in full, Ben partly
                (OWNER, 90.0, "SGD", "Dinner", "Food", None, True, json.dumps(split)),
                # id 2: from email, unverified, float noise
                (OWNER, 5.123456, "sgd", "Kopi", "food", "gmail-abc", False, None),
                # id 3: a US purchase
                (OWNER, 20.0, "USD", "Amazon", "Shopping", "gmail-def", True, None),
                # id 4: bad data
                (OWNER, -3.0, "SGD", "Refund?", None, None, True, None),
                # id 5: IOU kept only as a task
                (OWNER, 40.0, "SGD", "Taxi", None, None, True, None),
                # id 6: the friend's own expense
                (FRIEND, 12.5, "S$", "Lunch", None, None, True, None),
            ]
            await conn.executemany(
                "INSERT INTO expensetransaction (user_id, amount, currency, merchant, category,"
                " date, source_message_id, is_verified, split_data)"
                " VALUES ($1,$2,$3,$4,$5,'2026-08-01 12:00',$6,$7,$8)",
                rows,
            )
            await conn.execute(
                "INSERT INTO incometransaction (user_id, amount, currency, source, category, date,"
                " notes, source_message_id, linked_expense_id) VALUES"
                " ($1, 30.0, 'SGD', 'Ann', 'Friend Repayment', '2026-08-02', NULL, 'iou:1:ann', 1),"
                " ($1, 4200.0, 'SGD', 'employer', 'salary', '2026-08-25', NULL, NULL, NULL)",
                OWNER,
            )
            await conn.execute(
                "INSERT INTO deletedexpensemessage (user_id, source_message_id)"
                " VALUES ($1, 'gmail-zzz')",
                OWNER,
            )
            await conn.execute(
                "INSERT INTO taskitem (user_id, title, status, linked_expense_id, iou_friend,"
                " iou_amount) VALUES ($1,'Collect',  'todo', 5, 'Cat', 15.0)",
                OWNER,
            )
            yield conn
        finally:
            await conn.close()


async def test_reader_uses_a_read_only_transaction(legacy: asyncpg.Connection) -> None:
    snapshot = await read_legacy(legacy)
    assert {u.telegram_user_id for u in snapshot.users} == {OWNER, FRIEND}
    assert len(snapshot.expenses) == 6 and len(snapshot.incomes) == 2
    assert snapshot.tombstones == [(OWNER, "gmail-zzz")]
    async with legacy.transaction(readonly=True):
        with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
            await legacy.execute("DELETE FROM userprofile")


async def test_reader_rejects_a_schema_it_cannot_map(legacy: asyncpg.Connection) -> None:
    await legacy.execute("ALTER TABLE expensetransaction DROP COLUMN amount")
    with pytest.raises(LegacySchemaError, match="amount"):
        await read_legacy(legacy)


async def test_dry_run_writes_nothing(
    engine: object, uow: UowFactory, legacy: asyncpg.Connection
) -> None:
    report = await import_legacy(
        engine,  # type: ignore[arg-type]
        await read_legacy(legacy),
        apply=False,
        owner_telegram_id=OWNER,
    )
    assert report.ok, report.render()
    assert "DRY RUN" in report.render()
    assert await find_telegram_user(uow(), OWNER) is None


async def test_apply_imports_history_and_matches_totals(
    engine: object, uow: UowFactory, legacy: asyncpg.Connection
) -> None:
    snapshot = await read_legacy(legacy)
    report = await import_legacy(engine, snapshot, apply=True, owner_telegram_id=OWNER)  # type: ignore[arg-type]
    assert report.ok, report.render()
    owner_report = next(u for u in report.users if u.telegram_user_id == OWNER)
    assert (owner_report.expenses, owner_report.incomes) == (4, 2)
    assert owner_report.skipped == ["expense 4: amount -3.0 is not positive"]
    assert owner_report.expected[("out", "SGD")] == Decimal("135.1235")
    assert owner_report.expected[("in", "SGD")] == Decimal("4200") + Decimal("30")
    assert owner_report.rounded == 1
    assert owner_report.assumed_repayments == 1  # Ben's 10 had no repayment row

    owner = await find_telegram_user(uow(), OWNER)
    assert owner is not None and owner.role.value == "owner"
    assert owner.timezone == "Asia/Singapore"
    friend = await find_telegram_user(uow(), FRIEND)
    assert friend is not None and friend.timezone == "Asia/Singapore"  # bad tz replaced
    assert friend.role.value == "member"

    page = await list_ledger(uow(), owner.id, LedgerQuery(limit=50))
    kopi = next(t for t in page.items if t.counterparty == "Kopi")
    assert kopi.amount == Money.of("5.1235", "SGD")
    assert kopi.status is TransactionStatus.PENDING
    assert kopi.source is Source.IMPORT
    # Friend's "S$" isn't a currency code: their home currency is assumed and reported.
    friend_report = next(u for u in report.users if u.telegram_user_id == FRIEND)
    assert friend_report.currency_assumed == 1

    ious = {
        (i.split.participant_name, str(i.outstanding))
        for i in await list_open_ious(uow(), owner.id)
    }
    assert ious == {("Ben", "20.00 SGD"), ("Cat", "15.00 SGD")}

    # Imported email ids and tombstones block re-ingestion by the future email sweep.
    for message_id in ("gmail-abc", "gmail-zzz"):
        with pytest.raises(DuplicateSource):
            await log_transaction(
                uow(),
                owner.id,
                NewTransaction(
                    Direction.OUT,
                    Money.of("1", "SGD"),
                    NOW,
                    source=Source.EMAIL,
                    external_id=message_id,
                ),
            )


async def test_second_run_changes_nothing(
    engine: object, uow: UowFactory, legacy: asyncpg.Connection
) -> None:
    snapshot = await read_legacy(legacy)
    await import_legacy(engine, snapshot, apply=True, owner_telegram_id=OWNER)  # type: ignore[arg-type]
    again = await import_legacy(engine, snapshot, apply=True, owner_telegram_id=OWNER)  # type: ignore[arg-type]
    assert again.ok, again.render()
    owner_report = next(u for u in again.users if u.telegram_user_id == OWNER)
    assert (owner_report.expenses, owner_report.already_imported) == (0, 6)
    owner = await find_telegram_user(uow(), OWNER)
    assert owner is not None
    assert (await list_ledger(uow(), owner.id, LedgerQuery(limit=50))).total == 7


async def test_cli_refuses_the_same_database(
    monkeypatch: pytest.MonkeyPatch, empty_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", empty_database_url)
    monkeypatch.setenv("LEGACY_DATABASE_URL", dsn(empty_database_url))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert await cli.main([]) == 2


async def test_cli_dry_run_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    engine: object,
    empty_database_url: str,
    legacy: asyncpg.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_db = await legacy.fetchval("SELECT current_database()")
    new = make_url(empty_database_url)
    monkeypatch.setenv("DATABASE_URL", empty_database_url)
    monkeypatch.setenv(
        "LEGACY_DATABASE_URL",
        dsn(new.set(database=legacy_db).render_as_string(hide_password=False)),
    )
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert await cli.main([]) == 0
    assert "DRY RUN" in capsys.readouterr().out
