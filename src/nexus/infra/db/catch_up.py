"""python -m nexus.infra.db.catch_up --since <ISO timestamp> [--apply]

One-off catch-up after moving Nexus's database from Railway to its own server. The new
server's database was restored from a dump taken at a cutoff; Railway kept serving users for a
while afterwards, so rows written there since the cutoff exist only on Railway. This copies
them across without overwriting anything that changed on the new server in the meantime.

It reads Railway through a read-only, repeatable-read transaction and writes the target (the
app's own DATABASE_URL) in ONE transaction. Both connections must be the database owner or a
superuser (``postgres``): that role bypasses row-level security, which the app's own role does
not, and without it the comparison would only see one user's rows. It refuses to run as
anything else.

The Railway URL is never an argument (arguments show up in ``ps``): put it in the
CATCH_UP_SOURCE_URL environment variable, or pass ``--source-url-stdin`` and type it on stdin.

For each table in the public schema (minus EXCLUDED_TABLES) with a primary key, on the columns
both sides have, every Railway row is classified by its "change timestamp" (the newest of the
table's CHANGE_COLUMNS) against the cutoff:

* missing on the target and changed after the cutoff -> INSERT;
* present and identical -> nothing;
* present and different, changed on Railway after the cutoff:
    - the target row has not changed since the cutoff -> UPDATE to Railway's version;
    - the target row changed after the cutoff too -> CONFLICT, nothing written;
* present and different, but not changed on Railway after the cutoff: the target's version
  is left alone (it changed on the new server), unless neither side's timestamps explain the
  difference (an untimestamped column was edited), which is reported as a CONFLICT.

Rows that exist on the target, were created before the cutoff, and are missing on Railway are
only COUNTED as "possibly deleted on Railway"; nothing is ever deleted.

Writes go in foreign-key order (parents first) with constraints left ON. Every write sits in
a savepoint: a unique-key collision or any other constraint failure becomes a reported
conflict and the run carries on. A foreign-key failure is retried after the other tables have
been written (this resolves cycles such as users <-> wallets); rows still failing are conflicts.
Afterwards the identity/serial sequences of every table that got rows are moved up to the
table's maximum.

The default is a dry run: the same work, rolled back. ``--apply`` commits. Output is counts
and, for conflicts, the table, the primary key and a reason code. Never row contents.
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import asyncpg

SOURCE_URL_ENV = "CATCH_UP_SOURCE_URL"

# Tables this never touches, with the reason. Everything else in `public` is merged.
EXCLUDED_TABLES: dict[str, str] = {
    "alembic_version": "schema bookkeeping, owned by Alembic on each side",
    "checkpoints": "LangGraph checkpoint (migration 0003): chat-thread scratch state",
    "checkpoint_blobs": "LangGraph checkpoint (migration 0003): chat-thread scratch state",
    "checkpoint_writes": "LangGraph checkpoint (migration 0003): chat-thread scratch state",
    "checkpoint_migrations": "LangGraph checkpoint (migration 0003): the library's own version",
    "jobs": "background-job queue: leases and dedupe keys belong to the running worker",
    "web_cache": "expiring cache of web answers",
    "external_cache": "expiring cache of external API answers",
    "web_credits": "monthly search-credit counters, rebuilt by use",
    "serp_searches": "search log kept for rate accounting only",
    "ops_events": "operations telemetry, not user data",
    "model_costs": "LLM spend telemetry, not user data",
    "demo_costs": "demo spend telemetry, not user data",
    "demo_starts": "demo start counters, not user data",
    "fx_rates": "public exchange rates, refetched on demand",
    "market_bars": "public price history, refetched on demand",
    "market_quotes": "public quotes, refetched on demand",
    "market_news": "public news, refetched on demand",
    "market_earnings": "public earnings dates, refetched on demand",
    "market_symbols": "public symbol lookups, refetched on demand",
    "news_fetches": "news fetch bookkeeping, refetched on demand",
    "destination_photos": "photo cache refetched on demand (large binary rows)",
    "web_sessions": "login sessions: the new server issues its own, never revive old ones",
    "login_links": "one-time login links: never revive old ones",
}

# The timestamp columns that say "this row was written or changed", per merged table. A row's
# change timestamp is the newest non-null one. Columns that only schedule (expires_at,
# run_at, valid_until) or that the user types (occurred_at) are deliberately not here.
# A table missing from this map is still merged, by full comparison: rows absent on the
# target are inserted and any difference is reported as a conflict.
CHANGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "bill_occurrences": ("paid_at", "skipped_at"),
    "bills": ("created_at", "archived_at"),
    "budget_alerts": ("reached_at",),
    "budgets": ("created_at", "updated_at"),
    "capability_gaps": ("created_at",),
    "categories": ("created_at",),
    "category_rules": ("created_at", "updated_at", "archived_at"),
    "chat_log": ("created_at",),
    "department_runs": ("created_at", "updated_at", "finished_at"),
    "dividends": ("created_at",),
    "duplicate_dismissals": ("created_at",),
    "email_connections": ("created_at", "updated_at", "last_received_at", "nudged_at"),
    "email_links": ("created_at", "used_at"),
    "holding_drafts": ("created_at",),
    "holdings": ("created_at", "updated_at"),
    "inbound_emails": ("created_at", "received_at"),
    "inbound_events": ("received_at",),
    "invites": ("created_at", "redeemed_at"),
    "market_alerts": ("created_at", "sent_at"),
    "memories": ("created_at", "updated_at"),
    "notification_settings": ("updated_at",),
    "notifications": ("created_at", "sent_at"),
    "plans": ("created_at", "closed_at", "price_at", "last_refresh_check"),
    "receipts": ("created_at",),
    "salary_schedules": ("created_at", "updated_at"),
    "settlements": ("created_at",),
    "split_habits": ("created_at",),
    "splits": ("created_at",),
    "statement_imports": ("created_at", "undone_at"),
    "statement_mappings": ("created_at", "updated_at"),
    "subscriptions": ("created_at", "updated_at"),
    "trades": ("created_at",),
    "transaction_revisions": ("created_at", "undone_at"),
    "transaction_sources": ("created_at",),
    "transactions": ("created_at", "updated_at", "deleted_at"),
    "trip_activity": ("at",),
    "trip_bookings": ("created_at",),
    "trip_changes": ("created_at", "undone_at"),
    "trip_covers": ("created_at", "updated_at"),
    "trip_invites": ("created_at", "redeemed_at", "revoked_at"),
    "trip_links": ("created_at",),
    "trip_members": ("added_at",),
    "trip_paid_by_others": ("created_at", "settled_at"),
    "trip_reminders": ("sent_at",),
    "trip_shares": ("created_at",),
    "trips": ("created_at", "updated_at", "photo_tried_at", "activity_digest_at"),
    "users": ("created_at", "web_access_granted_at", "setup_dismissed_at", "timezone_set_at"),
    "voice_settings": ("updated_at",),
    "wallets": ("created_at",),
    "watchlist": ("created_at",),
}

# When a table has one, this column says when the row first existed (for "possibly deleted").
CREATED_COLUMNS = ("created_at", "added_at", "received_at", "at", "reached_at")

LOCK_TIMEOUT = "30s"


class CatchUpError(Exception):
    """A problem with the setup (bad URL, wrong role); the message is safe to print."""


@dataclass
class TableStats:
    changed: int = 0  # Railway rows changed after the cutoff (or with no timestamp at all)
    inserts: int = 0
    updates: int = 0
    same: int = 0  # changed-since-cutoff Railway rows that are already identical on the target
    conflicts: int = 0
    kept: int = 0  # differs, but the target's version is newer (or the row is old): left as is
    possibly_deleted: int = 0


@dataclass
class Conflict:
    table: str
    key: str  # primary key, e.g. "id=3f2a..."
    reason: str  # a code, never row content


@dataclass
class Report:
    stats: dict[str, TableStats] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sequences: list[str] = field(default_factory=list)
    applied: bool = False


@dataclass
class _Table:
    name: str
    columns: list[str]
    key: list[str]
    change: list[str]
    created: str | None
    loose: list[str]  # nullable foreign-key columns, set aside to break insert cycles

    def index(self, column: str) -> int:
        return self.columns.index(column)


@dataclass
class _Write:
    table: _Table
    key_text: str
    kind: str  # "insert" | "update" | "fixup" (restores columns set aside by a cycle break)
    sql: str
    args: list[Any]
    row: tuple[Any, ...] = ()


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def decide(
    *,
    target_has: bool,
    same: bool,
    railway_ts: datetime | None,
    target_ts: datetime | None,
    since: datetime,
) -> str:
    """What to do with one Railway row. Pure, so the rules are easy to test.

    A row with no timestamp (None) counts as "unknown age": absent -> insert, and it never
    proves a change on either side."""
    if not target_has:
        return "insert" if railway_ts is None or railway_ts > since else "skip_old"
    if same:
        return "same"
    if railway_ts is not None and railway_ts > since:
        return "update" if target_ts is None or target_ts <= since else "conflict"
    if target_ts is not None and target_ts > since:
        return "target_newer"
    return "unexplained"


def newest(values: list[Any]) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def asyncpg_dsn(url: str) -> str:
    """The URL without a SQLAlchemy driver suffix (asyncpg wants plain postgresql://)."""
    scheme, separator, rest = url.partition("://")
    if not separator:
        raise CatchUpError("not a database URL")
    return f"{scheme.split('+', 1)[0]}://{rest}"


def topological_order(tables: list[str], edges: set[tuple[str, str]]) -> list[str]:
    """Parents before children. ``edges`` holds (child, parent). Cycles are broken by taking
    the table with the fewest unwritten parents first; the retry pass covers what that leaves."""
    names = set(tables)
    parents: dict[str, set[str]] = {
        name: {p for c, p in edges if c == name and p in names and p != name} for name in tables
    }
    order: list[str] = []
    remaining = set(tables)
    while remaining:
        ready = sorted(name for name in remaining if not (parents[name] & remaining))
        if not ready:
            ready = [min(sorted(remaining), key=lambda name: len(parents[name] & remaining))]
        order.extend(ready)
        remaining -= set(ready)
    return order


async def _table_names(connection: asyncpg.Connection) -> set[str]:
    rows = await connection.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    return {row["table_name"] for row in rows}


async def _columns(connection: asyncpg.Connection, table: str) -> list[str]:
    rows = await connection.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 AND is_generated = 'NEVER' "
        "ORDER BY ordinal_position",
        table,
    )
    return [row["column_name"] for row in rows]


async def _primary_key(connection: asyncpg.Connection, table: str) -> list[str]:
    rows = await connection.fetch(
        "SELECT a.attname FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        "WHERE c.contype = 'p' AND c.conrelid = ('public.' || quote_ident($1))::regclass "
        "ORDER BY array_position(c.conkey, a.attnum)",
        table,
    )
    return [row["attname"] for row in rows]


async def _nullable_foreign_key_columns(connection: asyncpg.Connection, table: str) -> list[str]:
    rows = await connection.fetch(
        "SELECT DISTINCT a.attname FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        "WHERE c.contype = 'f' AND NOT a.attnotnull "
        "AND c.conrelid = ('public.' || quote_ident($1))::regclass",
        table,
    )
    return sorted(row["attname"] for row in rows)


async def _foreign_keys(connection: asyncpg.Connection) -> set[tuple[str, str]]:
    rows = await connection.fetch(
        "SELECT c.relname AS child, p.relname AS parent FROM pg_constraint k "
        "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_class p ON p.oid = k.confrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE k.contype = 'f' AND n.nspname = 'public'"
    )
    return {(row["child"], row["parent"]) for row in rows}


async def _require_owner(connection: asyncpg.Connection, label: str) -> None:
    bypasses = await connection.fetchval(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )
    if not bypasses:
        raise CatchUpError(
            f"the {label} connection is not a superuser (or BYPASSRLS role): "
            "row-level security would hide rows. Connect as postgres."
        )


async def _describe(
    source: asyncpg.Connection, target: asyncpg.Connection, report: Report
) -> list[_Table]:
    on_source = await _table_names(source)
    on_target = await _table_names(target)
    tables: list[_Table] = []
    for name in sorted((on_source | on_target) - set(EXCLUDED_TABLES)):
        if name not in on_source or name not in on_target:
            side = "Railway" if name not in on_source else "the new server"
            report.notes.append(f"skipped {name}: not on {side}")
            continue
        key = await _primary_key(target, name)
        if not key:
            report.notes.append(f"skipped {name}: no primary key")
            continue
        if key != await _primary_key(source, name):
            report.notes.append(f"skipped {name}: primary key differs between the two sides")
            continue
        source_columns = await _columns(source, name)
        columns = [c for c in await _columns(target, name) if c in set(source_columns)]
        if not set(key) <= set(columns):
            report.notes.append(f"skipped {name}: primary key column missing on one side")
            continue
        change = [c for c in CHANGE_COLUMNS.get(name, ()) if c in columns]
        created = next((c for c in CREATED_COLUMNS if c in change), None)
        if name not in CHANGE_COLUMNS:
            report.notes.append(f"{name}: no change timestamps known, compared in full")
        loose = [
            c
            for c in await _nullable_foreign_key_columns(target, name)
            if c in columns and c not in key
        ]
        tables.append(_Table(name, columns, key, change, created, loose))
    return tables


async def _fetch(
    connection: asyncpg.Connection, table: _Table
) -> dict[tuple[Any, ...], tuple[Any, ...]]:
    column_list = ", ".join(quote(c) for c in table.columns)
    rows = await connection.fetch(f"SELECT {column_list} FROM {quote(table.name)}")  # noqa: S608
    positions = [table.index(c) for c in table.key]
    out: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for row in rows:
        values = tuple(row.values())
        out[tuple(values[i] for i in positions)] = values
    return out


def _key_text(table: _Table, key: tuple[Any, ...]) -> str:
    return ", ".join(f"{column}={value}" for column, value in zip(table.key, key, strict=True))


def _insert_sql(table: _Table) -> str:
    names = ", ".join(quote(c) for c in table.columns)
    marks = ", ".join(f"${i}" for i in range(1, len(table.columns) + 1))
    table_name = quote(table.name)
    return f"INSERT INTO {table_name} ({names}) OVERRIDING SYSTEM VALUE VALUES ({marks})"  # noqa: S608


def _update_sql(table: _Table) -> tuple[str, list[int]]:
    """The UPDATE statement and the column positions of its parameters (SET, then WHERE)."""
    others = [c for c in table.columns if c not in table.key]
    sets = ", ".join(f"{quote(c)} = ${i}" for i, c in enumerate(others, start=1))
    wheres = " AND ".join(
        f"{quote(c)} = ${i}" for i, c in enumerate(table.key, start=len(others) + 1)
    )
    sql = f"UPDATE {quote(table.name)} SET {sets} WHERE {wheres}"  # noqa: S608
    return sql, [table.index(c) for c in [*others, *table.key]]


async def _attempt(target: asyncpg.Connection, write: _Write) -> str | None:
    """Run one write in a savepoint. None on success, "fk" for a foreign-key failure (worth
    retrying later), else a reason code. Never the database's message: it quotes row values."""
    try:
        async with target.transaction():
            await target.execute(write.sql, *write.args)
    except asyncpg.ForeignKeyViolationError:
        return "fk"
    except asyncpg.PostgresError as error:
        constraint = getattr(error, "constraint_name", None)
        return f"sqlstate {error.sqlstate}" + (f" {constraint}" if constraint else "")
    return None


async def _merge_table(
    table: _Table,
    source: asyncpg.Connection,
    target: asyncpg.Connection,
    since: datetime,
    report: Report,
    retry: list[_Write],
) -> None:
    stats = report.stats.setdefault(table.name, TableStats())
    theirs = await _fetch(source, table)
    ours = await _fetch(target, table)
    change_at = [table.index(c) for c in table.change]
    created_at = table.index(table.created) if table.created else None
    update_sql, update_positions = (
        _update_sql(table) if len(table.columns) > len(table.key) else ("", [])
    )

    for key, row in theirs.items():
        mine = ours.get(key)
        theirs_ts = newest([row[i] for i in change_at])
        mine_ts = newest([mine[i] for i in change_at]) if mine is not None else None
        if theirs_ts is None or theirs_ts > since:
            stats.changed += 1
        verdict = decide(
            target_has=mine is not None,
            same=mine == row,
            railway_ts=theirs_ts,
            target_ts=mine_ts,
            since=since,
        )
        if verdict == "same":
            stats.same += 1 if (theirs_ts is None or theirs_ts > since) else 0
        elif verdict in ("skip_old", "target_newer"):
            stats.kept += 1
        elif verdict == "unexplained":
            stats.conflicts += 1
            report.conflicts.append(Conflict(table.name, _key_text(table, key), "differs-untimed"))
        elif verdict == "conflict":
            stats.conflicts += 1
            report.conflicts.append(Conflict(table.name, _key_text(table, key), "changed-on-both"))
        else:
            if verdict == "insert":
                write = _Write(
                    table, _key_text(table, key), "insert", _insert_sql(table), list(row), row
                )
            else:
                args = [row[i] for i in update_positions]
                write = _Write(table, _key_text(table, key), "update", update_sql, args, row)
            outcome = await _attempt(target, write)
            if outcome == "fk":
                retry.append(write)
            elif outcome is not None:
                stats.conflicts += 1
                report.conflicts.append(Conflict(table.name, write.key_text, outcome))
            elif write.kind == "insert":
                stats.inserts += 1
            else:
                stats.updates += 1

    for key, mine in ours.items():
        if key in theirs:
            continue
        born = mine[created_at] if created_at is not None else newest([mine[i] for i in change_at])
        if born is not None and born <= since:
            stats.possibly_deleted += 1


async def _retry_foreign_keys(
    target: asyncpg.Connection, pending: list[_Write], report: Report
) -> None:
    """Parents may have arrived after their children (other tables, cycles): go again until a
    pass makes no progress. Then break a cycle by inserting the stuck rows with their nullable
    foreign-key columns empty and putting those back afterwards; whatever is still stuck is
    reported."""
    while pending:
        failed: list[_Write] = []
        for write in pending:
            outcome = await _attempt(target, write)
            stats = report.stats[write.table.name]
            if outcome == "fk":
                failed.append(write)
            elif outcome is not None:
                stats.conflicts += 1
                report.conflicts.append(Conflict(write.table.name, write.key_text, outcome))
            elif write.kind == "insert":
                stats.inserts += 1
            elif write.kind == "update":
                stats.updates += 1
        if len(failed) == len(pending):
            failed, split = await _break_cycles(target, failed, report)
            if not split:
                for write in failed:
                    report.stats[write.table.name].conflicts += 1
                    report.conflicts.append(
                        Conflict(write.table.name, write.key_text, "parent-row-missing")
                    )
                return
        pending = failed


async def _break_cycles(
    target: asyncpg.Connection, stuck: list[_Write], report: Report
) -> tuple[list[_Write], int]:
    """Insert stuck rows without their nullable foreign keys. Returns the writes still to do
    (the rows that could not be split, and a fix-up for each row that was) and how many rows
    were split."""
    remaining: list[_Write] = []
    split = 0
    for write in stuck:
        table = write.table
        loose = [c for c in table.loose if write.row[table.index(c)] is not None]
        if write.kind != "insert" or not loose:
            remaining.append(write)
            continue
        row = [None if c in loose else v for c, v in zip(table.columns, write.row, strict=True)]
        outcome = await _attempt(target, _Write(table, write.key_text, "insert", write.sql, row))
        if outcome is not None:
            remaining.append(write)
            continue
        report.stats[table.name].inserts += 1
        split += 1
        sets = ", ".join(f"{quote(c)} = ${i}" for i, c in enumerate(loose, start=1))
        wheres = " AND ".join(
            f"{quote(c)} = ${i}" for i, c in enumerate(table.key, start=len(loose) + 1)
        )
        sql = f"UPDATE {quote(table.name)} SET {sets} WHERE {wheres}"  # noqa: S608
        args = [write.row[table.index(c)] for c in [*loose, *table.key]]
        remaining.append(_Write(table, write.key_text, "fixup", sql, args))
    return remaining, split


async def _bump_sequences(target: asyncpg.Connection, tables: list[_Table], report: Report) -> None:
    for table in tables:
        for column in table.columns:
            sequence = await target.fetchval(
                "SELECT pg_get_serial_sequence($1, $2)", f"public.{quote(table.name)}", column
            )
            if sequence is None:
                continue
            top = await target.fetchval(
                f"SELECT max({quote(column)}) FROM {quote(table.name)}"  # noqa: S608
            )
            if top is None:
                continue
            state = await target.fetchrow(f"SELECT last_value, is_called FROM {sequence}")  # noqa: S608
            if state is not None and state["is_called"] and top <= state["last_value"]:
                continue
            await target.execute("SELECT setval($1::regclass, $2, true)", sequence, top)
            report.sequences.append(f"{table.name}.{column} -> {top}")


async def catch_up(
    source_url: str, target_url: str, since: datetime, *, apply: bool = False
) -> Report:
    """Compare and (with apply) merge. The write transaction is rolled back unless ``apply``."""
    if since.tzinfo is None:
        raise CatchUpError("--since needs a time zone, e.g. 2026-11-10T12:30:00Z")
    if asyncpg_dsn(source_url) == asyncpg_dsn(target_url):
        raise CatchUpError("the source and the target are the same database")
    report = Report(applied=apply)
    try:
        source = await asyncpg.connect(asyncpg_dsn(source_url), command_timeout=300)
    except (OSError, asyncpg.PostgresError) as error:
        raise CatchUpError(f"cannot connect to Railway ({type(error).__name__})") from None
    try:
        target = await asyncpg.connect(asyncpg_dsn(target_url), command_timeout=300)
    except (OSError, asyncpg.PostgresError) as error:
        await source.close()
        raise CatchUpError(f"cannot connect to the new database ({type(error).__name__})") from None
    try:
        await _require_owner(source, "Railway")
        await _require_owner(target, "new-server")
        async with source.transaction(isolation="repeatable_read", readonly=True):
            await _run(source, target, since, report, apply)
    finally:
        await source.close()
        await target.close()
    return report


async def _run(
    source: asyncpg.Connection,
    target: asyncpg.Connection,
    since: datetime,
    report: Report,
    apply: bool,
) -> None:
    tables = await _describe(source, target, report)
    order = topological_order([t.name for t in tables], await _foreign_keys(target))
    by_name = {t.name: t for t in tables}
    transaction = target.transaction()
    await transaction.start()
    try:
        await target.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
        await target.execute("SET CONSTRAINTS ALL IMMEDIATE")
        # Hold off the running app's writes to these tables while we compare and merge.
        for name in sorted(by_name):
            await target.execute(f"LOCK TABLE {quote(name)} IN SHARE ROW EXCLUSIVE MODE")
        retry: list[_Write] = []
        for name in order:
            await _merge_table(by_name[name], source, target, since, report, retry)
        await _retry_foreign_keys(target, retry, report)
        if apply:
            touched = [by_name[n] for n in order if report.stats[n].inserts]
            await _bump_sequences(target, touched, report)
            await transaction.commit()
        else:
            await transaction.rollback()
    except BaseException:
        await transaction.rollback()
        raise


def render(report: Report, since: datetime) -> str:
    lines = [f"Catch-up since {since.isoformat()}", ""]
    header = (
        f"{'table':<24}{'changed':>8}{'insert':>8}{'update':>8}{'same':>6}"
        f"{'conflict':>9}{'kept':>6}{'maybe-deleted':>14}"
    )
    lines += [header, "-" * len(header)]
    totals = TableStats()
    for name in sorted(report.stats):
        stats = report.stats[name]
        for attribute in vars(totals):
            setattr(totals, attribute, getattr(totals, attribute) + getattr(stats, attribute))
        if not any(vars(stats).values()):
            continue
        lines.append(
            f"{name:<24}{stats.changed:>8}{stats.inserts:>8}{stats.updates:>8}{stats.same:>6}"
            f"{stats.conflicts:>9}{stats.kept:>6}{stats.possibly_deleted:>14}"
        )
    lines += [
        "-" * len(header),
        f"{'total':<24}{totals.changed:>8}{totals.inserts:>8}{totals.updates:>8}{totals.same:>6}"
        f"{totals.conflicts:>9}{totals.kept:>6}{totals.possibly_deleted:>14}",
        "",
        "changed = Railway rows changed after the cutoff; same = of those, already identical here;",
        "kept = differs, but the new server's version is newer (or the row is old): left as is;",
        "maybe-deleted = here, made before the cutoff, missing on Railway (only counted).",
    ]
    if report.notes:
        lines += ["", *[f"note: {note}" for note in report.notes]]
    if report.conflicts:
        by_table: dict[str, list[Conflict]] = defaultdict(list)
        for conflict in report.conflicts:
            by_table[conflict.table].append(conflict)
        lines += ["", "Conflicts (nothing written for these; table, primary key, reason):"]
        for name in sorted(by_table):
            lines += [f"  {name}: {c.key}  [{c.reason}]" for c in by_table[name]]
    if report.sequences:
        lines += ["", "Sequences moved up:", *[f"  {s}" for s in report.sequences]]
    lines += ["", "Applied." if report.applied else "Dry run: nothing was written."]
    return "\n".join(lines)


def parse_since(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise CatchUpError(f"--since is not an ISO timestamp: {text!r}") from None
    if value.tzinfo is None:
        raise CatchUpError("--since needs a time zone, e.g. 2026-11-10T12:30:00Z")
    return value.astimezone(UTC)


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m nexus.infra.db.catch_up", description=__doc__)
    parser.add_argument("--since", required=True, help="cutoff, ISO 8601 with a time zone")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument(
        "--source-url-stdin",
        action="store_true",
        help=f"read Railway's database URL from stdin (default: ${SOURCE_URL_ENV})",
    )
    parser.add_argument(
        "--target-url-env",
        default="DATABASE_URL",
        help="environment variable holding the new database's URL (default: DATABASE_URL)",
    )
    args = parser.parse_args(argv)
    try:
        since = parse_since(args.since)
        source_url = (
            sys.stdin.readline().strip()
            if args.source_url_stdin
            else os.environ.get(SOURCE_URL_ENV, "")
        )
        target_url = os.environ.get(args.target_url_env, "")
        if not source_url:
            raise CatchUpError(f"no Railway URL: set ${SOURCE_URL_ENV} or use --source-url-stdin")
        if not target_url:
            raise CatchUpError(f"${args.target_url_env} is not set")
        report = await catch_up(source_url, target_url, since, apply=args.apply)
    except CatchUpError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except asyncpg.PostgresError as error:
        # Not the message: Postgres quotes row values in some of them.
        print(
            f"error: the database refused ({type(error).__name__}, {error.sqlstate})",
            file=sys.stderr,
        )
        return 1
    print(render(report, since))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
