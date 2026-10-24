from types import TracebackType
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction

from nexus.application.acting import current_user_id
from nexus.infra.db.email_repository import SqlEmailRepository
from nexus.infra.db.investment_repository import SqlInvestmentRepository
from nexus.infra.db.ledger_repository import SqlLedgerRepository
from nexus.infra.db.memory_repository import SqlMemoryRepository
from nexus.infra.db.notification_repository import SqlNotificationRepository
from nexus.infra.db.planning_repository import SqlJobQueue, SqlPlanningRepository
from nexus.infra.db.rate_repository import SqlRateRepository
from nexus.infra.db.runs_repository import SqlRunRepository
from nexus.infra.db.statement_repository import SqlStatementRepository
from nexus.infra.db.trip_repository import SqlTripRepository
from nexus.infra.db.user_data import SqlUserData
from nexus.infra.db.web_repository import SqlWebRepository


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
        self._email: SqlEmailRepository | None = None
        self._notifications: SqlNotificationRepository | None = None
        self._memory: SqlMemoryRepository | None = None
        self._statements: SqlStatementRepository | None = None
        self._runs: SqlRunRepository | None = None
        self._investments: SqlInvestmentRepository | None = None
        self._trips: SqlTripRepository | None = None
        self._rates: SqlRateRepository | None = None
        self._web: SqlWebRepository | None = None
        self._user_data: SqlUserData | None = None

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

    @property
    def email(self) -> SqlEmailRepository:
        if self._email is None:
            raise RuntimeError("unit of work is not active")
        return self._email

    @property
    def notifications(self) -> SqlNotificationRepository:
        if self._notifications is None:
            raise RuntimeError("unit of work is not active")
        return self._notifications

    @property
    def memory(self) -> SqlMemoryRepository:
        if self._memory is None:
            raise RuntimeError("unit of work is not active")
        return self._memory

    @property
    def statements(self) -> SqlStatementRepository:
        if self._statements is None:
            raise RuntimeError("unit of work is not active")
        return self._statements

    @property
    def runs(self) -> SqlRunRepository:
        if self._runs is None:
            raise RuntimeError("unit of work is not active")
        return self._runs

    @property
    def investments(self) -> SqlInvestmentRepository:
        if self._investments is None:
            raise RuntimeError("unit of work is not active")
        return self._investments

    @property
    def trips(self) -> SqlTripRepository:
        if self._trips is None:
            raise RuntimeError("unit of work is not active")
        return self._trips

    @property
    def rates(self) -> SqlRateRepository:
        if self._rates is None:
            raise RuntimeError("unit of work is not active")
        return self._rates

    @property
    def web(self) -> SqlWebRepository:
        if self._web is None:
            raise RuntimeError("unit of work is not active")
        return self._web

    @property
    def user_data(self) -> SqlUserData:
        if self._user_data is None:
            raise RuntimeError("unit of work is not active")
        return self._user_data

    async def __aenter__(self) -> Self:
        if self._used:
            raise RuntimeError("a unit of work can only be used once")
        self._used = True
        self._connection = await self._engine.connect()
        self._transaction = await self._connection.begin()
        user_id = current_user_id()
        if user_id is not None:
            # Row-level security: this transaction sees and writes only this user's rows
            # (and a trip's, if they are on it). Transaction-local, so it never outlives it.
            try:
                await self._connection.execute(
                    text("SELECT set_config('app.user_id', :id, true)"), {"id": str(user_id)}
                )
            except BaseException:
                await self._connection.close()
                raise
        self._ledger = SqlLedgerRepository(self._connection)
        self._planning = SqlPlanningRepository(self._connection)
        self._jobs = SqlJobQueue(self._connection)
        self._email = SqlEmailRepository(self._connection)
        self._notifications = SqlNotificationRepository(self._connection)
        self._memory = SqlMemoryRepository(self._connection)
        self._statements = SqlStatementRepository(self._connection)
        self._runs = SqlRunRepository(self._connection)
        self._investments = SqlInvestmentRepository(self._connection)
        self._trips = SqlTripRepository(self._connection)
        self._rates = SqlRateRepository(self._connection)
        self._web = SqlWebRepository(self._connection)
        self._user_data = SqlUserData(self._connection)
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
