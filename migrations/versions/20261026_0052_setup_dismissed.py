"""Home's setup checklist can be put away: when the user dismissed it (null: still shown).

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("setup_dismissed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "setup_dismissed_at")
