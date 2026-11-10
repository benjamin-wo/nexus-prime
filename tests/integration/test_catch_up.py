"""The Railway catch-up: two real databases, one cutoff, every kind of divergence."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from nexus.infra.db import catch_up
from nexus.infra.db.catch_up import CHANGE_COLUMNS, EXCLUDED_TABLES, Report, asyncpg_dsn
from tests.conftest import throwaway_database
from tests.integration.conftest import upgrade

pytestmark = pytest.mark.integration

SINCE = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
BEFORE = SINCE - timedelta(hours=1)
SOURCES_UNIQUE = "sqlstate 23505 uq_transaction_sources_user_id_source_external_id"


def at(minutes: int) -> datetime:
    return SINCE + timedelta(minutes=minutes)


def uid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


# Distinctive made-up text: none of it may ever appear in the output.
SECRET = "Zorblax Coffee Roasters"
SECRET_NOTE = "quarterly zorblax invoice"

U1, U3 = uid(1), uid(3)
C1, C2 = uid(11), uid(12)
W3 = uid(33)
T_SAME, T_RAILWAY_EDIT, T_BOTH, T_TARGET_EDIT, T_GONE = (uid(n) for n in (101, 102, 103, 104, 105))
T_NEW, T_CHILD, T_SRC = uid(201), uid(202), uid(203)


async def add_user(
    db: asyncpg.Connection, user: uuid.UUID, telegram: int, created: datetime
) -> None:
    await db.execute(
        "INSERT INTO users (id, telegram_user_id, timezone, home_currency, role, created_at, "
        "home_timezone) VALUES ($1, $2, 'UTC', 'SGD', 'member', $3, 'UTC')",
        user,
        telegram,
        created,
    )


async def add_category(
    db: asyncpg.Connection, cid: uuid.UUID, user: uuid.UUID, name: str, created: datetime
) -> None:
    await db.execute(
        "INSERT INTO categories (id, user_id, name, created_at) VALUES ($1, $2, $3, $4)",
        cid,
        user,
        name,
        created,
    )


async def add_transaction(
    db: asyncpg.Connection,
    tid: uuid.UUID,
    *,
    amount: int,
    notes: str,
    created: datetime,
    updated: datetime,
    category: uuid.UUID | None = None,
) -> None:
    await db.execute(
        "INSERT INTO transactions (id, user_id, direction, amount, currency, occurred_at, "
        "counterparty, category_id, notes, status, source, created_at, updated_at) "
        "VALUES ($1, $2, 'out', $3, 'SGD', $4, $5, $6, $7, 'confirmed', 'text', $4, $8)",
        tid,
        U1,
        amount,
        created,
        SECRET,
        category,
        notes,
        updated,
    )


async def add_source(
    db: asyncpg.Connection, row_id: int, tid: uuid.UUID, created: datetime
) -> None:
    await db.execute(
        "INSERT INTO transaction_sources (id, user_id, source, external_id, transaction_id, "
        "created_at) VALUES ($1, $2, 'telegram', 'msg-1', $3, $4)",
        row_id,
        U1,
        tid,
        created,
    )


async def add_gap(db: asyncpg.Connection, row_id: int, created: datetime) -> None:
    await db.execute(
        "INSERT INTO capability_gaps (id, user_id, request, intent, channel, created_at) "
        "VALUES ($1, $2, 'r', 'i', 'telegram', $3)",
        row_id,
        U1,
        created,
    )


async def add_rate(db: asyncpg.Connection, quote: str, created: datetime) -> None:
    await db.execute(
        "INSERT INTO fx_rates (base, quote, day, value, effective, created_at) "
        "VALUES ('USD', $1, '2026-11-09', 1.3, '2026-11-09', $2)",
        quote,
        created,
    )


async def baseline(db: asyncpg.Connection) -> None:
    """What both databases held at the moment of the copy."""
    await add_user(db, U1, 1001, BEFORE)
    await add_user(db, uid(2), 1002, BEFORE)
    await add_category(db, C1, U1, "Groceries", BEFORE)
    for tid, amount in ((T_SAME, 5), (T_RAILWAY_EDIT, 10), (T_BOTH, 20), (T_TARGET_EDIT, 30)):
        await add_transaction(
            db, tid, amount=amount, notes="original", created=BEFORE, updated=BEFORE, category=C1
        )
    await add_gap(db, 1, BEFORE)
    await add_rate(db, "SGD", BEFORE)


async def diverge_railway(db: asyncpg.Connection) -> None:
    await db.execute(  # (b) edited on Railway only
        "UPDATE transactions SET amount = 12, notes = $2, updated_at = $3 WHERE id = $1",
        T_RAILWAY_EDIT,
        SECRET_NOTE,
        at(10),
    )
    await db.execute(  # (c) edited on both
        "UPDATE transactions SET notes = 'railway side', updated_at = $2 WHERE id = $1",
        T_BOTH,
        at(20),
    )
    # (a) a new expense
    await add_transaction(db, T_NEW, amount=7, notes="new", created=at(30), updated=at(30))
    # (d) a new category and an expense that needs it
    await add_category(db, C2, U1, "Gadgets", at(35))
    await add_transaction(
        db, T_CHILD, amount=9, notes="child", created=at(36), updated=at(36), category=C2
    )
    # a new user whose usual card is a wallet of theirs: users <-> wallets is a cycle
    await add_user(db, U3, 1003, at(40))
    await db.execute(
        "INSERT INTO wallets (id, user_id, name, kind, created_at) "
        "VALUES ($1, $2, 'Card', 'card', $3)",
        W3,
        U3,
        at(40),
    )
    await db.execute("UPDATE users SET usual_card_wallet_id = $2 WHERE id = $1", U3, W3)
    # (e) an expense plus its dedupe row, which collides with one made on the new server
    await add_transaction(db, T_SRC, amount=3, notes="src", created=at(45), updated=at(45))
    await add_source(db, 50, T_SRC, at(45))
    # an id above anything the new server has handed out
    await add_gap(db, 5, at(50))
    # (f) an excluded table
    await add_rate(db, "EUR", at(55))


async def diverge_target(db: asyncpg.Connection) -> None:
    await db.execute(
        "UPDATE transactions SET notes = 'target side', updated_at = $2 WHERE id = $1",
        T_BOTH,
        at(40),
    )
    await db.execute(
        "UPDATE transactions SET notes = 'only on target', updated_at = $2 WHERE id = $1",
        T_TARGET_EDIT,
        at(41),
    )
    await add_transaction(
        db, uid(301), amount=1, notes="target new", created=at(60), updated=at(60)
    )
    await add_source(db, 7, uid(301), at(60))
    # made before the cutoff, absent on Railway: "possibly deleted"
    await add_transaction(db, T_GONE, amount=2, notes="gone", created=BEFORE, updated=BEFORE)
    # only the target has it, but it was made after the cutoff: not a deletion
    await add_category(db, uid(13), U1, "Newer here", at(61))


@pytest.fixture
async def pair() -> AsyncIterator[tuple[str, str]]:
    async with throwaway_database() as railway, throwaway_database() as server:
        await upgrade(railway)
        await upgrade(server)
        r = await asyncpg.connect(asyncpg_dsn(railway))
        s = await asyncpg.connect(asyncpg_dsn(server))
        try:
            await baseline(r)
            await baseline(s)
            await diverge_railway(r)
            await diverge_target(s)
        finally:
            await r.close()
            await s.close()
        yield railway, server


async def snapshot(url: str) -> dict[str, list[tuple[object, ...]]]:
    db = await asyncpg.connect(asyncpg_dsn(url))
    try:
        out: dict[str, list[tuple[object, ...]]] = {}
        for table in (
            "transactions",
            "categories",
            "users",
            "wallets",
            "transaction_sources",
            "capability_gaps",
            "fx_rates",
        ):
            rows = await db.fetch(f"SELECT * FROM {table} ORDER BY 1, 2")  # noqa: S608
            out[table] = [tuple(r.values()) for r in rows]
        return out
    finally:
        await db.close()


def conflict_keys(report: Report) -> set[tuple[str, str, str]]:
    return {(c.table, c.key, c.reason) for c in report.conflicts}


async def test_dry_run_counts_and_writes_nothing(pair: tuple[str, str]) -> None:
    railway, server = pair
    before = await snapshot(server)
    report = await catch_up.catch_up(railway, server, SINCE)

    assert not report.applied
    assert await snapshot(server) == before
    tx = report.stats["transactions"]
    assert (tx.inserts, tx.updates, tx.conflicts, tx.possibly_deleted) == (3, 1, 1, 1)
    assert report.stats["categories"].inserts == 1
    assert report.stats["categories"].possibly_deleted == 0
    assert report.stats["users"].inserts == 1
    assert report.stats["wallets"].inserts == 1
    assert report.stats["capability_gaps"].inserts == 1
    assert report.stats["transaction_sources"].inserts == 0
    assert report.stats["transaction_sources"].conflicts == 1
    assert conflict_keys(report) == {
        ("transactions", f"id={T_BOTH}", "changed-on-both"),
        ("transaction_sources", "id=50", SOURCES_UNIQUE),
    }
    assert "fx_rates" not in report.stats
    assert report.sequences == []


async def test_apply_merges_without_clobbering(pair: tuple[str, str]) -> None:
    railway, server = pair
    report = await catch_up.catch_up(railway, server, SINCE, apply=True)
    assert report.applied

    db = await asyncpg.connect(asyncpg_dsn(server))
    try:
        rows = await db.fetch("SELECT id, notes, amount FROM transactions")
        notes = {r["id"]: (r["notes"], r["amount"]) for r in rows}
        assert notes[T_RAILWAY_EDIT] == (SECRET_NOTE, 12)  # (b) taken from Railway
        assert notes[T_BOTH][0] == "target side"  # (c) the new server wins; reported
        assert notes[T_TARGET_EDIT][0] == "only on target"
        assert notes[T_SAME][0] == "original"
        assert {T_NEW, T_CHILD, T_SRC, T_GONE} <= set(notes)  # (a), (d); nothing deleted
        child = await db.fetchrow("SELECT category_id FROM transactions WHERE id = $1", T_CHILD)
        assert child is not None
        assert child["category_id"] == C2
        user = await db.fetchrow("SELECT usual_card_wallet_id FROM users WHERE id = $1", U3)
        assert user is not None
        assert user["usual_card_wallet_id"] == W3  # the users <-> wallets cycle
        sources = await db.fetch("SELECT id FROM transaction_sources")
        assert [r["id"] for r in sources] == [7]  # (e) Railway's colliding row was not written
        assert await db.fetchval("SELECT count(*) FROM fx_rates") == 1  # (f)
        assert any(s.startswith("capability_gaps.id") for s in report.sequences)
        new_id = await db.fetchval(
            "INSERT INTO capability_gaps (user_id, request, intent, channel) "
            "VALUES ($1, 'x', 'y', 'web') RETURNING id",
            U1,
        )
        assert new_id > 5
    finally:
        await db.close()

    again = await catch_up.catch_up(railway, server, SINCE, apply=True)
    assert sum(s.inserts + s.updates for s in again.stats.values()) == 0
    assert again.sequences == []
    assert len(again.conflicts) == 2


async def test_output_has_no_row_contents(
    pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    railway, server = pair
    monkeypatch.setenv("CATCH_UP_SOURCE_URL", railway)
    monkeypatch.setenv("DATABASE_URL", server)
    assert await catch_up.main(["--since", SINCE.isoformat(), "--apply"]) == 0
    shown = capsys.readouterr()
    text = shown.out + shown.err
    assert "Applied." in text
    assert "changed-on-both" in text
    for secret in (SECRET, SECRET_NOTE, "target side", "railway side", railway, server, "1003"):
        assert secret not in text


async def test_refuses_the_same_database_and_a_naive_cutoff(pair: tuple[str, str]) -> None:
    railway, server = pair
    with pytest.raises(catch_up.CatchUpError):
        await catch_up.catch_up(railway, railway, SINCE)
    with pytest.raises(catch_up.CatchUpError):
        await catch_up.catch_up(railway, server, SINCE.replace(tzinfo=None))


async def test_every_table_is_decided(empty_database_url: str) -> None:
    """A new migration's table must be added to EXCLUDED_TABLES or CHANGE_COLUMNS, and the
    names listed must exist."""
    await upgrade(empty_database_url)
    db = await asyncpg.connect(asyncpg_dsn(empty_database_url))
    try:
        tables = await catch_up._table_names(db)
        assert tables - set(EXCLUDED_TABLES) - set(CHANGE_COLUMNS) == set()
        assert set(CHANGE_COLUMNS) <= tables
        for table, columns in CHANGE_COLUMNS.items():
            assert set(columns) <= set(await catch_up._columns(db, table)), table
            assert await catch_up._primary_key(db, table), table
    finally:
        await db.close()
