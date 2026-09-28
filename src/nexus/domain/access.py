"""Web access: invites and sessions. Tokens are only ever stored hashed."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nexus.domain.ledger import UserId


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Invite:
    id: UUID
    token_hash: str
    created_by: UserId
    created_at: datetime
    expires_at: datetime
    redeemed_at: datetime | None = None
    redeemed_by: UserId | None = None

    def usable(self, now: datetime) -> bool:
        return self.redeemed_at is None and now < self.expires_at


@dataclass(frozen=True, slots=True)
class Session:
    token_hash: str
    user_id: UserId
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at
