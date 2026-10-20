"""The latest quote per stock (live prices while the US market is open), shared by every user.

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_quotes",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("prev_close", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("open", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", name=op.f("pk_market_quotes")),
    )


def downgrade() -> None:
    op.drop_table("market_quotes")
