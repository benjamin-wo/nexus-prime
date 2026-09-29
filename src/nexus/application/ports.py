"""What the use cases need from storage. Implemented in ``nexus.infra.db``.

Every method is scoped to one user. Implementations must filter on
``user_id`` in the query itself, never after loading.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from nexus.domain.access import Invite, Session
from nexus.domain.ledger import (
    Category,
    Direction,
    OpenIou,
    Revision,
    RevisionKind,
    Settlement,
    Source,
    Split,
    Transaction,
    TransactionStatus,
    User,
    UserId,
)
from nexus.domain.money import Money
from nexus.domain.planning import Bill, BillOccurrence, Budget, SalarySchedule


class SortField(StrEnum):
    OCCURRED_AT = "occurred_at"
    AMOUNT = "amount"


@dataclass(frozen=True, slots=True)
class LedgerQuery:
    direction: Direction | None = None
    start: datetime | None = None  # inclusive
    end: datetime | None = None  # exclusive
    category_id: UUID | None = None
    uncategorized: bool = False
    source: Source | None = None
    status: TransactionStatus | None = None
    search: str | None = None
    include_deleted: bool = False
    only_deleted: bool = False
    sort: SortField = SortField.OCCURRED_AT
    descending: bool = True
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class Page:
    items: list[Transaction]
    total: int


@dataclass(frozen=True, slots=True)
class DirectionTotal:
    direction: Direction
    total: Money
    count: int


@dataclass(frozen=True, slots=True)
class DayTotal:
    """Confirmed totals for one direction, category, currency and local day."""

    direction: Direction
    category_id: UUID | None
    category_name: str | None
    day: date
    total: Money
    count: int


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    category_id: UUID | None
    category_name: str | None
    total: Money
    count: int


class LedgerRepository(Protocol):
    # users
    async def insert_user_if_absent(self, user: User) -> bool: ...
    async def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None: ...
    async def get_user(self, user_id: UserId) -> User | None: ...

    # categories
    async def insert_category(self, category: Category) -> None: ...
    async def get_category(self, user_id: UserId, category_id: UUID) -> Category | None: ...
    async def list_categories(
        self, user_id: UserId, *, include_inactive: bool
    ) -> list[Category]: ...
    async def update_category(self, category: Category) -> None: ...

    # transactions
    async def insert_transaction(self, tx: Transaction) -> None: ...
    async def get_transaction(
        self, user_id: UserId, transaction_id: UUID, *, for_update: bool = False
    ) -> Transaction | None: ...
    async def update_transaction(self, tx: Transaction) -> None: ...
    async def list_transactions(self, user_id: UserId, query: LedgerQuery) -> Page: ...
    async def totals_by_direction(
        self, user_id: UserId, start: datetime, end: datetime
    ) -> list[DirectionTotal]: ...
    async def totals_by_day(
        self, user_id: UserId, start: datetime, end: datetime, timezone: str
    ) -> list[DayTotal]: ...
    async def spending_by_category(
        self, user_id: UserId, start: datetime, end: datetime
    ) -> list[CategoryTotal]: ...

    # external sources (also the "never re-import" tombstones)
    async def claim_source(
        self, user_id: UserId, source: Source, external_id: str, transaction_id: UUID | None
    ) -> None: ...
    async def source_claimed(self, user_id: UserId, source: Source, external_id: str) -> bool: ...

    # revisions
    async def insert_revision(
        self,
        user_id: UserId,
        transaction_id: UUID,
        kind: RevisionKind,
        before: dict[str, Any] | None,
        created_at: datetime,
    ) -> None: ...
    async def latest_open_revision(self, user_id: UserId) -> Revision | None: ...
    async def mark_undone(self, user_id: UserId, revision_id: int, at: datetime) -> None: ...

    # splits and settlements
    async def list_splits(self, user_id: UserId, transaction_id: UUID) -> list[Split]: ...
    async def has_settlements(self, user_id: UserId, transaction_id: UUID) -> bool: ...
    async def replace_splits(
        self, user_id: UserId, transaction_id: UUID, splits: list[Split]
    ) -> None: ...
    async def open_ious(
        self, user_id: UserId, *, participant_name: str | None = None, for_update: bool = False
    ) -> list[OpenIou]: ...
    async def insert_settlements(self, settlements: list[Settlement]) -> None: ...

    # web access
    async def grant_web_access(self, user_id: UserId, at: datetime) -> None: ...
    async def insert_invite(self, invite: Invite) -> None: ...
    async def get_invite(self, token_hash: str, *, for_update: bool = False) -> Invite | None: ...
    async def redeem_invite(self, invite_id: UUID, user_id: UserId, at: datetime) -> None: ...
    async def insert_session(self, session: Session) -> None: ...
    async def get_session(self, token_hash: str) -> Session | None: ...
    async def revoke_session(self, token_hash: str, at: datetime) -> None: ...

    # channel bookkeeping
    async def claim_inbound_event(self, channel: str, event_id: str) -> bool:
        """True the first time an event is seen; False for a redelivery."""
        ...

    async def insert_capability_gap(
        self, user_id: UserId, request: str, intent: str, channel: str
    ) -> None: ...


class PlanningRepository(Protocol):
    """Budgets and their alerts. Scoped to one user like the ledger."""

    async def upsert_budget(self, budget: Budget) -> Budget:
        """Insert, or replace the limit of the user's budget for the same category
        (or the overall one). Returns the stored budget."""
        ...

    async def list_budgets(self, user_id: UserId) -> list[Budget]: ...
    async def get_budget(self, user_id: UserId, budget_id: UUID) -> Budget | None: ...
    async def delete_budget(self, user_id: UserId, budget_id: UUID) -> bool: ...
    async def users_with_budgets(self) -> list[UserId]: ...
    async def record_alerts(
        self, user_id: UserId, budget_id: UUID, period: date, thresholds: list[int], at: datetime
    ) -> list[int]:
        """Record thresholds reached; returns only those not recorded before."""
        ...

    # bills
    async def insert_bill(self, bill: Bill) -> None: ...
    async def list_bills(self, user_id: UserId) -> list[Bill]:
        """Active (not archived) bills."""
        ...

    async def get_bill(self, user_id: UserId, bill_id: UUID) -> Bill | None: ...
    async def archive_bill(self, user_id: UserId, bill_id: UUID, at: datetime) -> bool: ...
    async def users_with_bills(self) -> list[UserId]: ...
    async def occurrences(
        self, user_id: UserId, bill_id: UUID, since: date
    ) -> list[BillOccurrence]:
        """Stored due dates on or after ``since``, earliest first."""
        ...

    async def get_occurrence(
        self, user_id: UserId, occurrence_id: UUID
    ) -> BillOccurrence | None: ...
    async def save_occurrence(self, occurrence: BillOccurrence) -> BillOccurrence:
        """Insert, or update the row for the same bill and due date. Returns the stored row."""
        ...

    # salary
    async def get_salary_schedule(self, user_id: UserId) -> SalarySchedule | None: ...
    async def save_salary_schedule(self, schedule: SalarySchedule) -> None:
        """Insert or replace the user's schedule."""
        ...

    async def delete_salary_schedule(self, user_id: UserId) -> bool: ...
    async def users_with_salary_schedules(self) -> list[UserId]: ...


class JobQueue(Protocol):
    async def enqueue(
        self, kind: str, payload: dict[str, Any], *, dedupe_key: str, run_at: datetime
    ) -> bool:
        """Queue a job in this transaction. False if the dedupe key was already used."""
        ...


class UnitOfWork(Protocol):
    """One database transaction. Single use: enter it once per use case."""

    @property
    def ledger(self) -> LedgerRepository: ...
    @property
    def planning(self) -> PlanningRepository: ...
    @property
    def jobs(self) -> JobQueue: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
