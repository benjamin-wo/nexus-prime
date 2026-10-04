"""Research plans: one stock's numbers and write-up, kept to be scored later.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(19, 4), nullable=False),
        sa.Column("entry_low", sa.Numeric(19, 4), nullable=True),
        sa.Column("entry_high", sa.Numeric(19, 4), nullable=True),
        sa.Column("stop", sa.Numeric(19, 4), nullable=True),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'target', 'stopped', 'expired')", name=op.f("ck_plans_status")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_plans_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
    )
    op.create_index("ix_plans_user_id_created_at", "plans", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_plans_user_id_created_at", table_name="plans")
    op.drop_table("plans")
