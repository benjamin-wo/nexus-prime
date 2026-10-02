"""The daily summary at a time the user chooses.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL keeps the default, 21:00 local time.
    op.add_column("notification_settings", sa.Column("daily_at", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("notification_settings", "daily_at")
