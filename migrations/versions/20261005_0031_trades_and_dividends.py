"""Trade history with realised gains, dividends on held shares, and dividends in
daily prices.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "market_bars",
        sa.Column("div_cash", sa.Numeric(19, 6), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "market_symbols",
        sa.Column("dividends", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("price", sa.Numeric(19, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("traded_on", sa.Date(), nullable=False),
        sa.Column("realised", sa.Numeric(19, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("side IN ('buy', 'sell')", name=op.f("ck_trades_side")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_trades_quantity_positive")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_trades_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
    )
    op.create_index("ix_trades_user_id_traded_on", "trades", ["user_id", "traded_on"])
    op.create_table(
        "dividends",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("per_share", sa.Numeric(19, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("shares", sa.Numeric(24, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("per_share > 0", name=op.f("ck_dividends_per_share_positive")),
        sa.CheckConstraint("shares > 0", name=op.f("ck_dividends_shares_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_dividends_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dividends")),
        sa.UniqueConstraint(
            "user_id", "symbol", "ex_date", name=op.f("uq_dividends_user_id_symbol_ex_date")
        ),
    )


def downgrade() -> None:
    op.drop_table("dividends")
    op.drop_index("ix_trades_user_id_traded_on", table_name="trades")
    op.drop_table("trades")
    op.drop_column("market_symbols", "dividends")
    op.drop_column("market_bars", "div_cash")
