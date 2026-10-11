"""Web search answers kept for a day, and the search credits each product used a month.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_web_cache")),
    )
    op.create_index(op.f("ix_web_cache_expires_at"), "web_cache", ["expires_at"])
    op.create_table(
        "web_credits",
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("product", sa.String(length=20), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.CheckConstraint("credits >= 0", name=op.f("ck_web_credits_credits_not_negative")),
        sa.PrimaryKeyConstraint("month", "product", name=op.f("pk_web_credits")),
    )


def downgrade() -> None:
    op.drop_table("web_credits")
    op.drop_index(op.f("ix_web_cache_expires_at"), table_name="web_cache")
    op.drop_table("web_cache")
