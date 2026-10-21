"""Keep a plan fresh: plans refreshed by themselves, the price each was made at, and a
closed status for a plan its refresh replaced.

``plans.keep_fresh`` turns the refresh on for a plan. ``refreshed_from`` links a plan to
the one it replaced (the same user's: the foreign key carries ``user_id``), and
``last_refresh_check`` is when the plan was last sent for an automatic refresh.
``price``, ``price_at`` and ``price_kind`` are the price the plan was written with (a live
quote, a provisional close or a close). The status check gains ``refreshed``.

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = "status IN ('open', 'target', 'stopped', 'expired')"
NEW_STATUSES = "status IN ('open', 'target', 'stopped', 'expired', 'refreshed')"


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("keep_fresh", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("plans", sa.Column("refreshed_from", sa.UUID(), nullable=True))
    op.add_column(
        "plans", sa.Column("last_refresh_check", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("plans", sa.Column("price", sa.Numeric(precision=19, scale=4), nullable=True))
    op.add_column("plans", sa.Column("price_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plans", sa.Column("price_kind", sa.Text(), nullable=True))
    op.create_unique_constraint(op.f("uq_plans_id_user_id"), "plans", ["id", "user_id"])
    op.create_foreign_key(
        op.f("fk_plans_refreshed_from_user_id_plans"),
        "plans",
        "plans",
        ["refreshed_from", "user_id"],
        ["id", "user_id"],
        ondelete="SET NULL (refreshed_from)",
    )
    op.drop_constraint(op.f("ck_plans_status"), "plans", type_="check")
    op.create_check_constraint(op.f("ck_plans_status"), "plans", NEW_STATUSES)


def downgrade() -> None:
    # A plan its refresh replaced was closed without an outcome of its own; before
    # "refreshed" existed that was a plan that ran out.
    op.execute("UPDATE plans SET status = 'expired' WHERE status = 'refreshed'")
    op.drop_constraint(op.f("ck_plans_status"), "plans", type_="check")
    op.create_check_constraint(op.f("ck_plans_status"), "plans", OLD_STATUSES)
    op.drop_constraint(op.f("fk_plans_refreshed_from_user_id_plans"), "plans", type_="foreignkey")
    op.drop_constraint(op.f("uq_plans_id_user_id"), "plans", type_="unique")
    for column in (
        "price_kind",
        "price_at",
        "price",
        "last_refresh_check",
        "refreshed_from",
        "keep_fresh",
    ):
        op.drop_column("plans", column)
