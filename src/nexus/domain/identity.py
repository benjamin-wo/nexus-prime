"""A way a person signs in. One account can have several."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from nexus.domain.ledger import UserId


class Provider(StrEnum):
    TELEGRAM = "telegram"
    EMAIL = "email"
    APPLE = "apple"


@dataclass(frozen=True, slots=True)
class Identity:
    id: UUID
    user_id: UserId
    provider: Provider
    # The provider's own id for the person: the Telegram user id as text, Apple's ``sub``,
    # the lower-case address for email.
    subject: str
    # The lower-case address the provider vouched for, if any.
    email: str | None
    created_at: datetime
