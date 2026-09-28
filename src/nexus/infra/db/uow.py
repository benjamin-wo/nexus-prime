from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction

from nexus.infra.db.ledger_repository import SqlLedgerRepository


class SqlUnitOfWork:
    """One connection and one transaction. Rolls back unless committed."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._connection: AsyncConnection | None = None
        self._transaction: AsyncTransaction | None = None
        self._used = False
        self._ledger: SqlLedgerRepository | None = None

    @property
    def ledger(self) -> SqlLedgerRepository:
        if self._ledger is None:
            raise RuntimeError("unit of work is not active")
        return self._ledger

    async def __aenter__(self) -> Self:
        if self._used:
            raise RuntimeError("a unit of work can only be used once")
        self._used = True
        self._connection = await self._engine.connect()
        self._transaction = await self._connection.begin()
        self._ledger = SqlLedgerRepository(self._connection)
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
