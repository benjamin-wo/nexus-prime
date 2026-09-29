"""Recurring payments: proposed from the ledger, tracked once the user agrees.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cadence", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("last_charged_on", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("previous_amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("price_changed_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_subscriptions_amount_positive")),
        sa.CheckConstraint(
            "cadence IN ('weekly', 'monthly', 'yearly')", name=op.f("ck_subscriptions_cadence")
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'active', 'dismissed')", name=op.f("ck_subscriptions_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_subscriptions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint(
            "user_id", "key", "currency", name=op.f("uq_subscriptions_user_id_key_currency")
        ),
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
