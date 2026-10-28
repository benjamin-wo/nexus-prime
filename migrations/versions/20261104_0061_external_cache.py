"""Answers from outside services (trip weather), kept across deploys.

One small table for every kind of answer: ``key`` is a hash of what was asked (never a user
or a name), ``kind`` says what sort of answer it is, ``value`` is the answer itself and
``expires_at`` is when it goes stale, the same time the in-memory caches use. Like
``web_cache`` and ``fx_rates`` it is shared by all users, so it has no row-level security;
the app's role is granted new tables by 0056's default privileges.

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_cache",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_external_cache")),
    )
    op.create_index(op.f("ix_external_cache_expires_at"), "external_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_external_cache_expires_at"), table_name="external_cache")
    op.drop_table("external_cache")
