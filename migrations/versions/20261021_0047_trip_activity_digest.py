"""A Telegram summary for the owner of a shared trip when someone else changes it: a
per-user switch (on by default) and when each trip's last summary covered up to.

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "trip_activity_alerts", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.add_column("trips", sa.Column("activity_digest_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("trips", "activity_digest_at")
    op.drop_column("users", "trip_activity_alerts")
