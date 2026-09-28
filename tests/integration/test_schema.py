import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.infra.db.tables import CHECKPOINT_TABLES, metadata

pytestmark = pytest.mark.integration


def _diff(connection: Connection) -> list[object]:
    def include(obj: object, name: str | None, type_: str, *_: object) -> bool:
        return not (type_ == "table" and name in CHECKPOINT_TABLES)

    context = MigrationContext.configure(
        connection, opts={"compare_server_default": True, "include_object": include}
    )
    return list(compare_metadata(context, metadata))


async def test_migrations_match_table_definitions(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        assert await connection.run_sync(_diff) == []
