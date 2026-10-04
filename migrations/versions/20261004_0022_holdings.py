"""Holdings, and positions read from a broker screenshot waiting to be saved.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "holdings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("average_cost", sa.Numeric(19, 4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_holdings_quantity_positive")),
        sa.CheckConstraint("average_cost >= 0", name=op.f("ck_holdings_cost_not_negative")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_holdings_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holdings")),
        sa.UniqueConstraint("user_id", "symbol", name=op.f("uq_holdings_user_id_symbol")),
    )
    op.create_table(
        "holding_drafts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("positions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('waiting', 'saved', 'discarded')", name=op.f("ck_holding_drafts_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_holding_drafts_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holding_drafts")),
    )
    op.create_index(
        "ix_holding_drafts_user_id_created_at",
        "holding_drafts",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_holding_drafts_user_id_created_at", table_name="holding_drafts")
    op.drop_table("holding_drafts")
    op.drop_table("holdings")
