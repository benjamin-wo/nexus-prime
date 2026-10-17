"""Scheduled moves: a not-spending bill can point at a wallet, and one due date of a bill
can be skipped.

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bills", sa.Column("wallet_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_bills_wallet_id_user_id_wallets"),
        "bills",
        "wallets",
        ["wallet_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_check_constraint(
        op.f("ck_bills_wallet_not_spending"), "bills", "wallet_id IS NULL OR NOT spending"
    )
    op.add_column(
        "bill_occurrences", sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_bill_occurrences_not_paid_and_skipped"),
        "bill_occurrences",
        "paid_at IS NULL OR skipped_at IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_bill_occurrences_not_paid_and_skipped"), "bill_occurrences", type_="check"
    )
    op.drop_column("bill_occurrences", "skipped_at")
    op.drop_constraint(op.f("ck_bills_wallet_not_spending"), "bills", type_="check")
    op.drop_constraint(op.f("fk_bills_wallet_id_user_id_wallets"), "bills", type_="foreignkey")
    op.drop_column("bills", "wallet_id")
