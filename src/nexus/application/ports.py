"""What the use cases need from storage. Implemented in ``nexus.infra.db``.

Every method is scoped to one user. Implementations must filter on
``user_id`` in the query itself, never after loading.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from nexus.domain.access import Invite, Session
from nexus.domain.email import (
    EmailConnection,
    ExpenseDraft,
    FetchedEmail,
    InboundEmail,
    Screening,
)
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
from nexus.domain.notifications import NotificationSettings
from nexus.domain.planning import Bill, BillOccurrence, Budget, SalarySchedule
from nexus.domain.receipts import Receipt
from nexus.domain.recurring import Subscription
from nexus.domain.rules import CategoryRule


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
    async def merge_category(
        self, user_id: UserId, source_id: UUID, target_id: UUID, now: datetime
    ) -> int:
        """Move the source's transactions, rules and (if the target has none) budget to
        the target, and archive the source. Returns how many transactions moved."""
        ...

    # receipts
    async def insert_receipt(self, receipt: Receipt) -> None: ...
    async def attach_receipt(
        self, user_id: UserId, receipt_id: UUID, transaction_id: UUID, *, stashed_after: datetime
    ) -> bool: ...
    async def live_receipt(self, user_id: UserId, transaction_id: UUID) -> Receipt | None: ...
    async def transactions_with_receipts(
        self, user_id: UserId, transaction_ids: list[UUID]
    ) -> set[UUID]: ...
    async def receipts_to_purge(self, now: datetime, limit: int) -> list[Receipt]:
        """Across all users: for the purge job only."""
        ...

    async def delete_receipt(self, user_id: UserId, receipt_id: UUID) -> None: ...

    # category rules
    async def insert_category_rule(self, rule: CategoryRule) -> None:
        """Raises Conflict if an active rule already has this pattern."""
        ...

    async def update_category_rule(self, rule: CategoryRule) -> None: ...
    async def get_category_rule(self, user_id: UserId, rule_id: UUID) -> CategoryRule | None:
        """Archived rules too, so old transactions can still explain themselves."""
        ...

    async def list_category_rules(self, user_id: UserId) -> list[CategoryRule]:
        """Active rules only."""
        ...

    # transactions
    async def insert_transaction(self, tx: Transaction) -> None: ...
    async def get_transaction(
        self, user_id: UserId, transaction_id: UUID, *, for_update: bool = False
    ) -> Transaction | None: ...
    async def update_transaction(self, tx: Transaction) -> None: ...
    async def list_transactions(self, user_id: UserId, query: LedgerQuery) -> Page: ...
    async def outgoing_since(
        self, user_id: UserId, start: datetime, *, limit: int
    ) -> list[Transaction]:
        """Live expenses with a merchant, since ``start``, newest first."""
        ...

    async def logged_between(
        self, user_id: UserId, start: datetime, end: datetime, *, limit: int
    ) -> list[Transaction]:
        """Live transactions created (not occurred) in [start, end), oldest first."""
        ...

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
    async def list_subscriptions(self, user_id: UserId) -> list[Subscription]: ...
    async def get_subscription(
        self, user_id: UserId, subscription_id: UUID, *, for_update: bool = False
    ) -> Subscription | None: ...
    async def insert_subscription(self, subscription: Subscription) -> bool:
        """False if this merchant already has a row (proposed, tracked or dismissed)."""
        ...

    async def update_subscription(self, subscription: Subscription) -> None: ...
    async def get_notifications(
        self, user_id: UserId, *, for_update: bool = False
    ) -> NotificationSettings:
        """The user's settings, or the defaults if they never changed them."""
        ...

    async def save_notifications(self, settings: NotificationSettings, now: datetime) -> None: ...
    async def users_to_notify(self) -> list[UserId]:
        """Across all users: everyone reachable on Telegram."""
        ...


class JobQueue(Protocol):
    async def enqueue(
        self, kind: str, payload: dict[str, Any], *, dedupe_key: str, run_at: datetime
    ) -> bool:
        """Queue a job in this transaction. False if the dedupe key was already used."""
        ...


class EmailRepository(Protocol):
    """Connected mailboxes and the emails swept from them."""

    async def insert_link(
        self, user_id: UserId, token_hash: str, *, expires_at: datetime, now: datetime
    ) -> None: ...
    async def link_owner(self, token_hash: str, now: datetime) -> UserId | None: ...
    async def use_link(self, token_hash: str, now: datetime) -> UserId | None: ...
    async def save_connection(self, connection: EmailConnection) -> EmailConnection: ...
    async def get_connection(
        self, user_id: UserId, connection_id: UUID, *, for_update: bool = False
    ) -> EmailConnection | None: ...
    async def list_connections(self, user_id: UserId) -> list[EmailConnection]: ...
    async def connections_to_sweep(self) -> list[EmailConnection]:
        """Across all users: for the sweep job only."""
        ...

    async def update_connection(self, connection: EmailConnection) -> None: ...
    async def delete_connection(self, user_id: UserId, connection_id: UUID) -> None: ...
    async def seen_message_ids(self, connection_id: UUID, ids: list[str]) -> set[str]: ...
    async def insert_inbound(self, email: InboundEmail) -> bool: ...
    async def get_inbound(
        self, user_id: UserId, email_id: UUID, *, for_update: bool = False
    ) -> InboundEmail | None: ...
    async def update_inbound(self, email: InboundEmail) -> None: ...
    async def count_waiting(self, user_id: UserId, start: datetime, end: datetime) -> int:
        """Receipts found in [start, end) still waiting for the user."""
        ...

    async def list_inbound(
        self, user_id: UserId, *, since: datetime, limit: int
    ) -> list[InboundEmail]: ...


class MailboxRevoked(Exception):
    """The mailbox provider no longer accepts our access (revoked or expired)."""


@dataclass(frozen=True, slots=True)
class MailboxGrant:
    address: str
    refresh_token: str


class Mailbox(Protocol):
    """Reading a connected mailbox: Gmail, or a forwarding address. The stored
    "refresh token" is whatever unlocks it (for a forwarding address, its inbox id)."""

    async def access_token(self, refresh_token: str) -> str:
        """Raises MailboxRevoked if the grant is gone."""
        ...

    async def search(self, access_token: str, query: str, *, after: datetime) -> list[str]: ...
    async def fetch(self, access_token: str, message_id: str) -> FetchedEmail: ...
    async def revoke(self, refresh_token: str) -> None: ...


class SignInMailbox(Mailbox, Protocol):
    """A provider the user signs in to (Gmail). Only receipt-like emails are fetched."""

    def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...
    async def exchange(self, code: str, *, redirect_uri: str) -> MailboxGrant:
        """Raises InvalidInput if the user didn't grant read access."""
        ...


class ForwardingInboxes(Mailbox, Protocol):
    """Addresses users forward receipts to (AgentMail)."""

    async def create_inbox(self, owner: str) -> tuple[str, str]:
        """A new inbox for ``owner``: (inbox id, address)."""
        ...


class EmailReader(Protocol):
    """Screens an email cheaply, then reads a likely receipt into a draft expense."""

    async def triage(self, email: FetchedEmail) -> Screening: ...
    async def extract(
        self, email: FetchedEmail, *, categories: Sequence[str] = ()
    ) -> ExpenseDraft: ...


class Cipher(Protocol):
    """Encrypts secrets before they're stored."""

    def encrypt(self, plaintext: str) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> str: ...


class ReceiptStore(Protocol):
    """Private object storage for receipt files."""

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def delete(self, key: str) -> None: ...
    def download_url(self, key: str, *, filename: str, expires: timedelta) -> str:
        """A link that works for ``expires``, for someone already authorised."""
        ...


class UnitOfWork(Protocol):
    """One database transaction. Single use: enter it once per use case."""

    @property
    def ledger(self) -> LedgerRepository: ...
    @property
    def planning(self) -> PlanningRepository: ...
    @property
    def jobs(self) -> JobQueue: ...
    @property
    def email(self) -> EmailRepository: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
