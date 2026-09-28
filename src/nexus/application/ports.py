"""What the use cases need from storage. Implemented in ``nexus.infra.db``.

Every method is scoped to one user. Implementations must filter on
``user_id`` in the query itself, never after loading.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

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

    # channel bookkeeping
    async def claim_inbound_event(self, channel: str, event_id: str) -> bool:
        """True the first time an event is seen; False for a redelivery."""
        ...

    async def insert_capability_gap(
        self, user_id: UserId, request: str, intent: str, channel: str
    ) -> None: ...


class UnitOfWork(Protocol):
    """One database transaction. Single use: enter it once per use case."""

    @property
    def ledger(self) -> LedgerRepository: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
