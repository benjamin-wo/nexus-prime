"""Startup guard: refuse to serve on a database that is not at Alembic head.

The schema is only ever changed through Alembic; the app never calls
``create_all``. Migrations run as a separate deploy step.
"""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


class PendingMigrationsError(RuntimeError):
    pass


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


def head_revisions() -> set[str]:
    return set(ScriptDirectory.from_config(alembic_config()).get_heads())


def _current_revisions(connection: Connection) -> set[str]:
    return set(MigrationContext.configure(connection).get_current_heads())


async def assert_schema_at_head(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        current = await connection.run_sync(_current_revisions)
    expected = head_revisions()
    if current != expected:
        raise PendingMigrationsError(
            f"database is at {sorted(current) or 'no revision'}, expected {sorted(expected)}; "
            "run `alembic upgrade head` before starting the app"
        )
