"""Receipts: files kept privately with the expense they prove. Pure rules, no I/O.

A receipt follows its transaction. It is hidden while the transaction is
deleted, comes back if the transaction is restored, and is purged for good 30
days after the delete. A receipt never claimed by a transaction (a declined
photo) is purged after a day.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId

RETENTION_AFTER_DELETE = timedelta(days=30)
UNCLAIMED_TTL = timedelta(days=1)
MAX_BYTES = 10 * 1024 * 1024
CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "application/pdf": "pdf",
}
# How long a download link works.
LINK_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class Receipt:
    id: UUID
    user_id: UserId
    transaction_id: UUID | None  # None until its expense is saved
    object_key: str
    content_type: str
    size_bytes: int
    created_at: datetime

    @property
    def filename(self) -> str:
        return f"receipt-{self.id}.{CONTENT_TYPES.get(self.content_type, 'bin')}"


def object_key(user_id: UserId, receipt_id: UUID) -> str:
    """Keys carry the owner, so a stray key never looks like someone else's file."""
    return f"receipts/{user_id}/{receipt_id}"


def check_file(data: bytes, content_type: str) -> str:
    kind = content_type.split(";")[0].strip().lower()
    if kind == "image/jpg":
        kind = "image/jpeg"
    if kind not in CONTENT_TYPES:
        raise InvalidInput(f"receipts can't be {kind or 'that type'}")
    if not data:
        raise InvalidInput("the receipt file is empty")
    if len(data) > MAX_BYTES:
        raise InvalidInput("receipts can be at most 10 MB")
    return kind


def purge_due(receipt: Receipt, transaction_deleted_at: datetime | None, now: datetime) -> bool:
    """Whether a receipt should be erased now."""
    if receipt.transaction_id is None:
        return now - receipt.created_at >= UNCLAIMED_TTL
    return (
        transaction_deleted_at is not None
        and now - transaction_deleted_at >= RETENTION_AFTER_DELETE
    )
