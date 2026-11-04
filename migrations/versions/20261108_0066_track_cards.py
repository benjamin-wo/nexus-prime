"""A per-user "track which card paid" preference, off by default ("simple mode").

``users.track_cards`` says whether the user keeps track of which card or wallet paid for each
expense (0065). While it is false the app does not apply the usual card to new expenses, does
not match an email receipt's card or tag a statement import with one, and the assistant does
not ask which card paid. Nothing stored is touched: turning it on again brings the behaviour
back.

Everyone who already uses the feature keeps it: a user with a usual card, or with any
expense that names the wallet it was paid with, starts with the preference on. Everyone else
starts with it off. No table is new and the column sits on ``users`` (no row-level security
policy there, see 0056), so policies and grants are as they were.

Revision ID: 0066
Revises: 0065
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("track_cards", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # Nobody loses their setup. The migration user is not forced through row-level security
    # (0056), so it sees every user's transactions.
    op.execute(
        "UPDATE users u SET track_cards = true WHERE u.usual_card_wallet_id IS NOT NULL "
        "OR EXISTS (SELECT 1 FROM transactions t WHERE t.user_id = u.id "
        "AND t.paid_with_wallet_id IS NOT NULL)"
    )


def downgrade() -> None:
    op.drop_column("users", "track_cards")
