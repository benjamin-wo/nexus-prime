"""Exchange rates already looked up, so a past day's rate is fetched only once.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("base", sa.String(length=3), nullable=False),
        sa.Column("quote", sa.String(length=3), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("effective", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("effective <= day", name=op.f("ck_fx_rates_effective_not_later")),
        sa.CheckConstraint("value > 0", name=op.f("ck_fx_rates_value_positive")),
        sa.PrimaryKeyConstraint("base", "quote", "day", name=op.f("pk_fx_rates")),
    )


def downgrade() -> None:
    op.drop_table("fx_rates")
