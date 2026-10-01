"""Backup and restore drill (M10): dump a database, restore it into a new one,
and prove the copy is the same, table by table.

    TEST_DATABASE_URL=postgresql://user:pass@localhost/postgres \\
      python scripts/backup_drill.py --users 20

Without --source it makes a throwaway database, migrates it and seeds made-up
users (the eval seed), so the drill never needs real data. With --source it
dumps that database instead; it only ever reads from it. Either way it restores
into a new database on the TEST_DATABASE_URL server, compares every table's row
count and a checksum of its contents, checks the restored schema is at the
migrations' head, and drops what it created. pg_dump and pg_restore must be at
least the source server's major version.
"""

import argparse
import asyncio
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import asyncpg
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from nexus.evals.seed import seed_user
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.uow import SqlUnitOfWork

# Every table's contents, in a fixed order, as one checksum.
_TABLES = """
select tablename from pg_tables where schemaname = 'public' order by tablename
"""


async def fingerprint(dsn: str) -> dict[str, tuple[int, str]]:
    conn = await asyncpg.connect(dsn)
    try:
        found: dict[str, tuple[int, str]] = {}
        for row in await conn.fetch(_TABLES):
            name = row["tablename"]
            rows = "string_agg(t::text, E'\\n' order by t::text)"
            query = f"select count(*), coalesce(md5({rows}), '') from \"{name}\" t"  # noqa: S608 - names from pg_tables
            count, digest = await conn.fetchrow(query)
            found[name] = (count, digest)
        return found
    finally:
        await conn.close()


def run(*argv: str) -> None:
    subprocess.run(argv, check=True, capture_output=True, text=True)  # noqa: S603 - fixed programs


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="a database URL to dump (read only); default: seed one")
    parser.add_argument("--users", type=int, default=20, help="made-up users to seed")
    args = parser.parse_args()

    admin = make_url(os.environ["TEST_DATABASE_URL"]).set(drivername="postgresql")
    admin_dsn = admin.render_as_string(hide_password=False)
    tag = uuid.uuid4().hex[:8]
    made: list[str] = []

    async def create(name: str) -> str:
        conn = await asyncpg.connect(admin_dsn)
        await conn.execute(f'CREATE DATABASE "{name}"')
        await conn.close()
        made.append(name)
        return admin.set(database=name).render_as_string(hide_password=False)

    try:
        if args.source:
            source = (
                make_url(args.source)
                .set(drivername="postgresql")
                .render_as_string(hide_password=False)
            )
        else:
            source = await create(f"nexus_drill_src_{tag}")
            url = (
                make_url(source)
                .set(drivername="postgresql+asyncpg")
                .render_as_string(hide_password=False)
            )
            config = alembic_config(url)
            config.attributes["configure_logger"] = False
            await asyncio.to_thread(command.upgrade, config, "head")
            engine = make_engine(url)
            for n in range(args.users):
                await seed_user(lambda: SqlUnitOfWork(engine), 900_000 + n)
            await engine.dispose()

        target = await create(f"nexus_drill_dst_{tag}")
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "nexus.dump"
            began = time.perf_counter()
            # Custom format: compressed, and restorable table by table if need be.
            run("pg_dump", "--format=custom", "--no-owner", "--no-acl", "-f", str(dump), source)
            dumped = time.perf_counter() - began
            began = time.perf_counter()
            run("pg_restore", "--no-owner", "--no-acl", "--exit-on-error", "-d", target, str(dump))
            restored = time.perf_counter() - began
            size = dump.stat().st_size

        before, after = await fingerprint(source), await fingerprint(target)
        differ = sorted(n for n in before.keys() | after.keys() if before.get(n) != after.get(n))
        conn = await asyncpg.connect(target)
        version = await conn.fetchval("select version_num from alembic_version")
        await conn.close()
        head = ScriptDirectory.from_config(alembic_config(target)).get_current_head()
        rows = sum(count for count, _ in before.values())
        print(
            f"tables={len(before)} rows={rows} dump={size / 1024:.0f} KiB "
            f"in {dumped:.1f}s, restore {restored:.1f}s; "
            f"schema {version} (head {head}); tables that differ: {differ or 'none'}"
        )
        if differ or version != head:
            raise SystemExit(1)
    finally:
        conn = await asyncpg.connect(admin_dsn)
        for name in made:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
