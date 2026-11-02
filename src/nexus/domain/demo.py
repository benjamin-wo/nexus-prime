"""What a public-demo account may not do: anything that reaches other people or outside
services for it. A demo account is one with ``User.demo_expires_at`` set; see
``nexus.application.demo``."""

from nexus.domain.errors import Forbidden
from nexus.domain.ledger import User

NEXT_STEP = "Sign in with Telegram for a full account."


def forbid(user: User, what: str) -> None:
    """Refuse ``what`` (a short phrase, "Inviting people") for a demo account."""
    if user.is_demo:
        raise Forbidden(f"{what} isn't part of the demo. {NEXT_STEP}")
