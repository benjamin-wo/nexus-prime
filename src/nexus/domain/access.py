"""Web access: invites and sessions. Tokens are only ever stored hashed."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from nexus.domain.ledger import UserId

# A session is pushed out at most this often, so a busy one costs a write a day, not one a request.
RENEW_AFTER = timedelta(days=1)


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
    # Whether using the session pushes its expiry out again, and by how much: its own
    # ``lifetime`` (None: as long as it was made for). A session made short stays short.
    renewable: bool = False
    lifetime: timedelta | None = None

    @property
    def span(self) -> timedelta:
        """How long the session lasts from its start or last renewal."""
        return self.lifetime if self.lifetime is not None else self.expires_at - self.created_at

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at

    def due_for_renewal(self, now: datetime) -> bool:
        """Renewable, live, and at least ``RENEW_AFTER`` old since it was last pushed out."""
        return (
            self.renewable and self.active(now) and self.expires_at - now < self.span - RENEW_AFTER
        )
