"""Receipts from a connected mailbox. Pure rules, no I/O.

Only what the user asks for: a mailbox is connected when the user connects it,
and nothing found there is logged until the user confirms it.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.money import Money

# How far back the first sweep looks.
BACKFILL = timedelta(days=30)
# At most this many new emails are read per mailbox per sweep.
SWEEP_LIMIT = 25
# One email is given up on (marked unreadable) if reading it takes longer than this.
READ_TIMEOUT = timedelta(seconds=45)
# A sweep stops starting new emails after this long, and leaves the rest for the
# next one (a job's lease is 5 minutes).
SWEEP_BUDGET = timedelta(minutes=3)
# A connect link works this long, once.
LINK_TTL = timedelta(minutes=10)

# What Gmail is asked for: receipts, invoices, orders and card alerts. Anything
# else in the mailbox is never fetched.
RECEIPT_QUERY = (
    "-in:chats -in:spam -in:trash -category:promotions -category:social ("
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


# How amounts are written on receipts and bank alerts, and the currency each means.
# "$" alone is the user's home currency.
_SYMBOLS = {
    "S$": "SGD", "SG$": "SGD", "US$": "USD", "A$": "AUD", "AU$": "AUD", "HK$": "HKD",
    "NZ$": "NZD", "C$": "CAD", "CA$": "CAD", "RM": "MYR", "€": "EUR", "£": "GBP",
    "¥": "JPY", "₩": "KRW", "₹": "INR", "฿": "THB", "₱": "PHP", "RP": "IDR",
}  # fmt: skip
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_NEGATIVE = re.compile(r"-\s*\D{0,4}\d")
_CODE = re.compile(r"\b[A-Z]{3}\b")


def read_amount(amount: str | None, currency: str | None, home: str) -> Money | None:
    """The money in what was read from an email, however it was written: "12.40",
    "SGD 12.40", "S$12.40", "1,234.50". None if there's no clear positive amount."""
    if not amount:
        return None
    text = amount.strip().upper()
    if _NEGATIVE.search(text):
        return None  # a refund or credit, not money spent
    numbers = _NUMBER.findall(text)
    if len(numbers) != 1:
        return None  # nothing, or more than one figure: not clear enough to log
    code = _currency(text) or _currency((currency or "").strip().upper()) or home
    try:
        money = Money(Decimal(numbers[0].replace(",", "")), code)
    except (InvalidInput, InvalidOperation):
        return None
    return money if money.is_positive else None


def _currency(text: str) -> str | None:
    for symbol, code in sorted(_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        if symbol in text:
            return code
    found = _CODE.search(text)
    return found.group(0) if found else None
