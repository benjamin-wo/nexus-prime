"""Remember that a user was asked about tracking which card paid.

``users.card_tracking_asked`` is set once a bank email showed a card to a user who does not
track cards and Nexus asked whether to turn it on (Telegram, once), or when the user sets
the preference themselves. Either way they are never asked again. A new column on ``users``
(no row-level security policy there, see 0056), false for everyone; no table is new, so
policies and grants are as they were.

Revision ID: 0067
Revises: 0066
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "card_tracking_asked", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "card_tracking_asked")
