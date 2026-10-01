"""Ledger entities and the rules that don't need a database."""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, NewType
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.money import Money

UserId = NewType("UserId", UUID)

MAX_TEXT = 500
MAX_NAME = 100


class Role(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class Direction(StrEnum):
    IN = "in"
    OUT = "out"


class TransactionStatus(StrEnum):
    CONFIRMED = "confirmed"
    PENDING = "pending"


class Source(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    EMAIL = "email"
    IMPORT = "import"
    MANUAL = "manual"


class RevisionKind(StrEnum):
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    RESTORE = "restore"
    SPLIT = "split"


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    telegram_user_id: int
    telegram_chat_id: int | None
    timezone: str
    home_currency: str
    role: Role
    created_at: datetime
    web_access_granted_at: datetime | None = None

    @property
    def has_web_access(self) -> bool:
        return self.role is Role.OWNER or self.web_access_granted_at is not None


@dataclass(frozen=True, slots=True)
class Category:
    id: UUID
    user_id: UserId
    name: str
    active: bool


@dataclass(frozen=True, slots=True)
class Transaction:
    id: UUID
    user_id: UserId
    direction: Direction
    amount: Money
    occurred_at: datetime
    counterparty: str | None
    category_id: UUID | None
    notes: str | None
    status: TransactionStatus
    source: Source
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    # The category rule that chose the category, if one did. Cleared when the
    # user picks a category themselves.
    category_rule_id: UUID | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


@dataclass(frozen=True, slots=True)
class Split:
    id: UUID
    user_id: UserId
    transaction_id: UUID
    participant_name: str
    share: Money


@dataclass(frozen=True, slots=True)
class OpenIou:
    """A split with money still owed to the user."""

    split: Split
    outstanding: Money
    expense_occurred_at: datetime


@dataclass(frozen=True, slots=True)
class Link:
    """One repayment against one share of a bill, seen from either side: the bill
    it paid back, and the money in that paid it."""

    bill_id: UUID
    bill_counterparty: str | None
    bill_occurred_at: datetime
    income_id: UUID
    income_occurred_at: datetime
    participant_name: str
    amount: Money


@dataclass(frozen=True, slots=True)
class Lineage:
    """How money moved around one transaction. For a bill: who it was split with
    and what each has paid back. For money in: which bills it paid back."""

    shares: list[Split]
    links: list[Link]

    def repaid(self, transaction_id: UUID) -> Decimal:
        """The part of this transaction that's a friend's money, not the user's:
        what was paid back on a bill, or what money in paid back."""
        return sum(
            (
                link.amount.amount
                for link in self.links
                if transaction_id in (link.bill_id, link.income_id)
            ),
            Decimal(0),
        )


@dataclass(frozen=True, slots=True)
class Settlement:
    id: UUID
    user_id: UserId
    split_id: UUID
    income_transaction_id: UUID
    amount: Money


@dataclass(frozen=True, slots=True)
class Revision:
    id: int
    user_id: UserId
    transaction_id: UUID
    kind: RevisionKind
    before: dict[str, Any] | None
    created_at: datetime
    undone_at: datetime | None = None


# --- validation -------------------------------------------------------------


def clean_text(value: str | None, *, field_name: str, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise InvalidInput(f"{field_name} is longer than {limit} characters")
    return cleaned or None


def clean_name(value: str, *, field_name: str) -> str:
    cleaned = clean_text(value, field_name=field_name, limit=MAX_NAME)
    if cleaned is None:
        raise InvalidInput(f"{field_name} must not be empty")
    return cleaned


def _name_words(name: str) -> list[str]:
    return re.findall(r"[^\W_]+", name.casefold())


def same_person(known: str, given: str) -> bool:
    """Whether two ways of writing a name are the same person: any case or word
    order, and a name the user shortened ("Wei Ming") matches the full one a bank
    prints ("TAN WEI MING"), as long as every word of the shorter is in the
    longer."""
    a, b = _name_words(known), _name_words(given)
    if not a or not b:
        return False
    short, long = sorted((a, b), key=len)
    return set(short) <= set(long)


def require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidInput(f"{field_name} must include a timezone")
    return value


def require_positive(amount: Money) -> Money:
    if not amount.is_positive:
        raise InvalidInput("amount must be greater than zero")
    return amount


# --- snapshots (revision `before` payloads) -----------------------------------


def snapshot(tx: Transaction) -> dict[str, Any]:
    return {
        "direction": tx.direction.value,
        "amount": str(tx.amount.amount),
        "currency": tx.amount.currency,
        "occurred_at": tx.occurred_at.isoformat(),
        "counterparty": tx.counterparty,
        "category_id": str(tx.category_id) if tx.category_id else None,
        "category_rule_id": str(tx.category_rule_id) if tx.category_rule_id else None,
        "notes": tx.notes,
        "status": tx.status.value,
        "deleted_at": tx.deleted_at.isoformat() if tx.deleted_at else None,
    }


def apply_snapshot(tx: Transaction, data: dict[str, Any], *, now: datetime) -> Transaction:
    return replace(
        tx,
        direction=Direction(data["direction"]),
        amount=Money.of(data["amount"], data["currency"]),
        occurred_at=datetime.fromisoformat(data["occurred_at"]),
        counterparty=data["counterparty"],
        category_id=UUID(data["category_id"]) if data["category_id"] else None,
        category_rule_id=UUID(rule) if (rule := data.get("category_rule_id")) else None,
        notes=data["notes"],
        status=TransactionStatus(data["status"]),
        deleted_at=datetime.fromisoformat(data["deleted_at"]) if data["deleted_at"] else None,
        updated_at=now,
    )


def splits_snapshot(splits: list[Split]) -> dict[str, Any]:
    return {
        "splits": [
            {"participant_name": s.participant_name, "share": str(s.share.amount)} for s in splits
        ]
    }


# --- policies -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShareRequest:
    participant_name: str
    share: Money | None = None


@dataclass(frozen=True, slots=True)
class PlannedShare:
    participant_name: str
    share: Money


@dataclass(frozen=True, slots=True)
class SplitPlan:
    shares: list[PlannedShare]
    own_share: Money


def plan_split(
    total: Money, requests: list[ShareRequest], *, include_self: bool = True
) -> SplitPlan:
    """Work out who owes what for a bill the user paid.

    Either every participant gives an explicit share, or none does and the
    bill is split equally (the user included when ``include_self``). With an
    equal split the user's share comes first, so the user absorbs any
    leftover minor unit rather than a friend being over-charged.
    """
    if not requests:
        raise InvalidInput("a split needs at least one other participant")
    names = [clean_name(r.participant_name, field_name="participant name") for r in requests]
    if len({n.casefold() for n in names}) != len(names):
        raise InvalidInput("each participant may appear only once")
    explicit = [r.share for r in requests if r.share is not None]
    if explicit and len(explicit) != len(requests):
        raise InvalidInput("give a share for every participant, or for none")

    if explicit:
        shares = [require_positive(s) for s in explicit]
        owed = Money.zero(total.currency)
        for share in shares:
            owed = owed + share
        if owed > total:
            raise InvalidInput(f"shares add up to {owed}, more than the bill ({total})")
        own = total - owed
    else:
        parts = total.allocate(len(requests) + (1 if include_self else 0))
        own = parts.pop(0) if include_self else Money.zero(total.currency)
        shares = parts
    return SplitPlan([PlannedShare(n, s) for n, s in zip(names, shares, strict=True)], own)


@dataclass(frozen=True, slots=True)
class Allocation:
    split_id: UUID
    amount: Money


@dataclass(frozen=True, slots=True)
class RepaymentPlan:
    allocations: list[Allocation]
    unallocated: Money


def allocate_repayment(amount: Money, open_ious: list[OpenIou]) -> RepaymentPlan:
    """Pay off a participant's IOUs oldest first; report any excess."""
    remaining = require_positive(amount)
    allocations: list[Allocation] = []
    ordered = sorted(open_ious, key=lambda iou: (iou.expense_occurred_at, str(iou.split.id)))
    for iou in ordered:
        if remaining.is_zero:
            break
        if iou.outstanding.currency != amount.currency:
            continue
        paid = remaining.min(iou.outstanding)
        allocations.append(Allocation(iou.split.id, paid))
        remaining = remaining - paid
    return RepaymentPlan(allocations, remaining)
