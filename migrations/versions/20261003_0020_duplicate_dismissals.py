"""Pairs of transactions the user said aren't one payment recorded twice.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "duplicate_dismissals",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("first_id", sa.UUID(), nullable=False),
        sa.Column("second_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("first_id < second_id", name=op.f("ck_duplicate_dismissals_ordered")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_duplicate_dismissals_user_id_users")
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "first_id", "second_id", name=op.f("pk_duplicate_dismissals")
        ),
    )


def downgrade() -> None:
    op.drop_table("duplicate_dismissals")
