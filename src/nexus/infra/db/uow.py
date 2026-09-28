from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction

from nexus.infra.db.ledger_repository import SqlLedgerRepository
from nexus.infra.db.planning_repository import SqlJobQueue, SqlPlanningRepository


class SqlUnitOfWork:
    """One connection and one transaction. Rolls back unless committed."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._connection: AsyncConnection | None = None
        self._transaction: AsyncTransaction | None = None
        self._used = False
        self._ledger: SqlLedgerRepository | None = None
        self._planning: SqlPlanningRepository | None = None
        self._jobs: SqlJobQueue | None = None

    @property
    def ledger(self) -> SqlLedgerRepository:
        if self._ledger is None:
            raise RuntimeError("unit of work is not active")
        return self._ledger

    @property
    def planning(self) -> SqlPlanningRepository:
        if self._planning is None:
            raise RuntimeError("unit of work is not active")
        return self._planning

    @property
    def jobs(self) -> SqlJobQueue:
        if self._jobs is None:
            raise RuntimeError("unit of work is not active")
        return self._jobs

    async def __aenter__(self) -> Self:
        if self._used:
            raise RuntimeError("a unit of work can only be used once")
        self._used = True
        self._connection = await self._engine.connect()
        self._transaction = await self._connection.begin()
        self._ledger = SqlLedgerRepository(self._connection)
        self._planning = SqlPlanningRepository(self._connection)
        self._jobs = SqlJobQueue(self._connection)
        return self

    async def commit(self) -> None:
        if self._transaction is None:
            raise RuntimeError("unit of work is not active")
        await self._transaction.commit()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self._transaction is not None and self._transaction.is_active:
                await self._transaction.rollback()
        finally:
            if self._connection is not None:
                await self._connection.close()
