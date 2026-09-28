"""Bills and their due dates.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bills",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("cadence", sa.Text(), nullable=False),
        sa.Column("anchor", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(amount IS NULL) = (currency IS NULL)", name=op.f("ck_bills_amount_with_currency")
        ),
        sa.CheckConstraint("amount IS NULL OR amount > 0", name=op.f("ck_bills_amount_positive")),
        sa.CheckConstraint(
            "cadence IN ('once', 'weekly', 'monthly', 'yearly')", name=op.f("ck_bills_cadence")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_bills_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bills")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_bills_id_user_id")),
    )
    op.create_index("ix_bills_user_id", "bills", ["user_id"], unique=False)
    op.create_table(
        "bill_occurrences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("bill_id", sa.UUID(), nullable=False),
        sa.Column("due", sa.Date(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminded_offset", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint(
            "reminded_offset IN (7, 3, 1)", name=op.f("ck_bill_occurrences_reminded_offset")
        ),
        sa.ForeignKeyConstraint(
            ["bill_id", "user_id"],
            ["bills.id", "bills.user_id"],
            name=op.f("fk_bill_occurrences_bill_id_user_id_bills"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bill_occurrences")),
        sa.UniqueConstraint("bill_id", "due", name=op.f("uq_bill_occurrences_bill_id_due")),
    )


def downgrade() -> None:
    op.drop_table("bill_occurrences")
    op.drop_index("ix_bills_user_id", table_name="bills")
    op.drop_table("bills")
