"""A watchlist per user, and news and earnings dates per stock (shared).

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_watchlist_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist")),
        sa.UniqueConstraint("user_id", "symbol", name=op.f("uq_watchlist_user_id_symbol")),
    )
    op.create_table(
        "market_news",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "external_id", name=op.f("pk_market_news")),
    )
    op.create_index(
        "ix_market_news_symbol_published_at",
        "market_news",
        ["symbol", "published_at"],
        unique=False,
    )
    op.create_table(
        "market_earnings",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("timing", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("symbol", "day", name=op.f("pk_market_earnings")),
    )
    op.create_table(
        "news_fetches",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", name=op.f("pk_news_fetches")),
    )


def downgrade() -> None:
    op.drop_table("news_fetches")
    op.drop_table("market_earnings")
    op.drop_index("ix_market_news_symbol_published_at", table_name="market_news")
    op.drop_table("market_news")
    op.drop_table("watchlist")
