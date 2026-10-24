from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url


def libpq_url(database_url: str) -> str:
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def postgres_checkpointer(
    database_url: str, *, app_role: str = ""
) -> AsyncIterator[AsyncPostgresSaver]:
    """The LangGraph checkpointer. Its tables come from migration 0003, never setup(), so
    the app never needs to change the schema. Like the app's engine, its connections switch
    to ``app_role``; the checkpoint tables have no row-level security (they are keyed by
    chat thread, not user) but the role is granted them."""

    async def use_app_role(connection: AsyncConnection[Any]) -> None:
        await connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(app_role)))

    async with AsyncConnectionPool(
        libpq_url(database_url),
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        configure=use_app_role if app_role else None,
    ) as pool:
        yield AsyncPostgresSaver(pool)
