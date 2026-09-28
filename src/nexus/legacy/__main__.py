"""python -m nexus.legacy [--apply]

Reads LEGACY_DATABASE_URL (the old database, read-only) and writes to
DATABASE_URL (the new one). Dry-run unless --apply. Exits 1 if any user's
counts or totals don't match, in which case that user was not written.
"""

import argparse
import asyncio
import os
import sys

import asyncpg
from sqlalchemy.engine import make_url

from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import assert_schema_at_head
from nexus.legacy.importer import import_legacy
from nexus.legacy.reader import read_legacy
from nexus.settings import Settings


def _same_database(a: str, b: str) -> bool:
    left, right = make_url(a), make_url(b)
    return (left.host, left.port or 5432, left.database) == (
        right.host,
        right.port or 5432,
        right.database,
    )


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m nexus.legacy", description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args(argv)

    legacy_url = os.environ.get("LEGACY_DATABASE_URL", "").strip()
    if not legacy_url:
        print("LEGACY_DATABASE_URL is not set", file=sys.stderr)
        return 2
    settings = Settings()
    if _same_database(legacy_url, settings.database_url_str):
        print(
            "LEGACY_DATABASE_URL and DATABASE_URL are the same database; refusing.", file=sys.stderr
        )
        return 2

    legacy_dsn = (
        make_url(legacy_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )
    conn = await asyncpg.connect(
        legacy_dsn, server_settings={"default_transaction_read_only": "on"}
    )
    try:
        snapshot = await read_legacy(conn)
    finally:
        await conn.close()

    engine = make_engine(settings.database_url_str)
    try:
        await assert_schema_at_head(engine)
        report = await import_legacy(
            engine,
            snapshot,
            apply=args.apply,
            owner_telegram_id=settings.admin_telegram_chat_id,
            default_currency=settings.default_home_currency,
            default_timezone=settings.default_timezone,
        )
    finally:
        await engine.dispose()
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
