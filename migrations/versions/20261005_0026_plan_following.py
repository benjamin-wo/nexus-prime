"""Following research plans after each close: when the buy zone was reached, the
last day checked, how each plan ended, and whether to send alerts.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("entered_on", sa.Date(), nullable=True))
    op.add_column("plans", sa.Column("checked_through", sa.Date(), nullable=True))
    op.add_column("plans", sa.Column("outcome_price", sa.Numeric(19, 4), nullable=True))
    op.add_column("plans", sa.Column("outcome_day", sa.Date(), nullable=True))
    op.add_column("plans", sa.Column("result_percent", sa.Numeric(9, 1), nullable=True))
    op.add_column(
        "plans",
        sa.Column("alerts", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_index("ix_plans_status", "plans", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_plans_status", table_name="plans")
    for column in (
        "alerts",
        "result_percent",
        "outcome_day",
        "outcome_price",
        "checked_through",
        "entered_on",
    ):
        op.drop_column("plans", column)
