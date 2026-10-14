"""Operational events: what the app did and how it went (kinds, names, timings,
status codes, error types and a keyed hash for the user), never what anyone said,
wrote or spent. Kept 30 days.

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ops_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("ms", sa.Integer()),
        sa.Column("trace", sa.String(32)),
        sa.Column("user_ref", sa.String(16)),
        sa.Column("channel", sa.String(16)),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_ops_events_at", "ops_events", ["at"])
    op.create_index("ix_ops_events_kind_at", "ops_events", ["kind", "at"])


def downgrade() -> None:
    op.drop_table("ops_events")
