from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def make_engine(database_url: str, *, app_role: str = "") -> AsyncEngine:
    """The engine. With ``app_role``, every new connection switches to that role (``SET
    ROLE``), the restricted one that row-level security applies to. Alembic passes none: its
    connection stays the owner, which makes the schema and is not held to the policies."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    if app_role:
        statement = f'SET ROLE "{app_role}"'  # the setting allows letters, digits, _ only

        @event.listens_for(engine.sync_engine, "connect")
        def _set_role(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(statement)
            finally:
                cursor.close()
            dbapi_connection.commit()  # the pool rolls back on return; keep the role

    return engine
