"""Receipt archive.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "receipts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "object_key LIKE 'receipts/' || user_id || '/%'",
            name=op.f("ck_receipts_key_owner"),
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_receipts_size_positive")),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name=op.f("fk_receipts_transaction_id_user_id_transactions"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_receipts_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipts")),
        sa.UniqueConstraint("object_key", name=op.f("uq_receipts_object_key")),
    )
    op.create_index("ix_receipts_created_at", "receipts", ["created_at"], unique=False)
    op.create_index(
        "uq_receipts_transaction_id",
        "receipts",
        ["transaction_id"],
        unique=True,
        postgresql_where=sa.text("transaction_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_receipts_transaction_id", table_name="receipts")
    op.drop_index("ix_receipts_created_at", table_name="receipts")
    op.drop_table("receipts")
