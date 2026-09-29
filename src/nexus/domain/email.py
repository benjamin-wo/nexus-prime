"""Receipts from a connected mailbox. Pure rules, no I/O.

Only what the user asks for: a mailbox is connected when the user connects it,
and nothing found there is logged until the user confirms it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.ledger import UserId

# How far back the first sweep looks.
BACKFILL = timedelta(days=30)
# At most this many new emails are read per mailbox per sweep.
SWEEP_LIMIT = 25
# A connect link works this long, once.
LINK_TTL = timedelta(minutes=10)

# What Gmail is asked for: receipts, invoices, orders and card alerts. Anything
# else in the mailbox is never fetched.
RECEIPT_QUERY = (
    "-in:chats -in:spam -in:trash ("
    "subject:(receipt OR invoice OR order OR payment OR paid OR transaction OR purchase "
    'OR booking OR "e-receipt" OR "tax invoice" OR "you paid" OR "card alert") '
    'OR "total paid" OR "amount paid" OR "order total" OR "transaction alert")'
)


class Provider(StrEnum):
    GMAIL = "gmail"


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    BROKEN = "broken"  # the provider refused our access; the user must reconnect


class EmailStatus(StrEnum):
    PENDING = "pending"  # a receipt, waiting for the user to confirm
    LOGGED = "logged"
    SKIPPED = "skipped"  # the user said no
    NOT_RECEIPT = "not_receipt"
    NO_AMOUNT = "no_amount"
    DUPLICATE = "duplicate"
    FAILED = "failed"


# Statuses the user can still act on from the Email page.
ACTIONABLE = frozenset({EmailStatus.PENDING, EmailStatus.NOT_RECEIPT, EmailStatus.NO_AMOUNT})


@dataclass(frozen=True, slots=True)
class EmailConnection:
    id: UUID
    user_id: UserId
    provider: Provider
    address: str
    token: bytes  # the encrypted refresh token; never stored in the clear
    status: ConnectionStatus
    synced_until: datetime | None  # emails received before this were already swept
    created_at: datetime
    updated_at: datetime
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class InboundEmail:
    """One email the sweep looked at, and what became of it. Keeps the sender,
    subject and outcome, never the body."""

    id: UUID
    user_id: UserId
    connection_id: UUID
    provider_message_id: str
    received_at: datetime
    sender: str
    subject: str
    status: EmailStatus
    reason: str | None
    draft: dict[str, Any] | None  # the expense read from it, while it waits
    transaction_id: UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FetchedEmail:
    provider_message_id: str
    received_at: datetime
    sender: str
    subject: str
    text: str  # plain text, trimmed; HTML is reduced to its text
    pdf: bytes | None = None  # the first PDF attachment, if any (a receipt to keep)


@dataclass(frozen=True, slots=True)
class Screening:
    is_receipt: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ExpenseDraft:
    """What was read from a receipt email. Anything unclear is None, never a guess."""

    amount: str | None
    currency: str | None
    merchant: str | None
    date: str | None  # YYYY-MM-DD

    def as_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "currency": self.currency,
            "merchant": self.merchant,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExpenseDraft":
        return cls(data.get("amount"), data.get("currency"), data.get("merchant"), data.get("date"))


def external_id(provider: Provider, address: str, provider_message_id: str) -> str:
    """The ledger's dedupe key. It names the mailbox, not the connection, so an email
    whose expense was deleted is never imported again, even after reconnecting."""
    return f"{provider.value}:{address.casefold()}:{provider_message_id}"


def sweep_from(connection: EmailConnection, now: datetime) -> datetime:
    return connection.synced_until or now - BACKFILL


def short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
