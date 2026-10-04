"""Daily stock prices, shared by every user, and when each stock was last fetched.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_bars",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(19, 6), nullable=False),
        sa.Column("high", sa.Numeric(19, 6), nullable=False),
        sa.Column("low", sa.Numeric(19, 6), nullable=False),
        sa.Column("close", sa.Numeric(19, 6), nullable=False),
        sa.Column("adj_close", sa.Numeric(19, 6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "day", name=op.f("pk_market_bars")),
    )
    op.create_table(
        "market_symbols",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", name=op.f("pk_market_symbols")),
    )


def downgrade() -> None:
    op.drop_table("market_symbols")
    op.drop_table("market_bars")
