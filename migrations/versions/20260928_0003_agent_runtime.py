"""Agent runtime: capability gaps, inbound event dedupe, LangGraph checkpoints.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import psycopg
import sqlalchemy as sa
from alembic import op
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _libpq_url() -> str:
    url = op.get_bind().engine.url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def upgrade() -> None:
    op.create_table(
        "capability_gaps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_capability_gaps_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_gaps")),
    )
    op.create_table(
        "inbound_events",
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("channel", "event_id", name=op.f("pk_inbound_events")),
    )
    # The checkpointer ships its own versioned DDL, including CREATE INDEX
    # CONCURRENTLY, which can't run inside a transaction. Run it here, outside
    # Alembic's transaction, so the schema still only changes through Alembic.
    with op.get_context().autocommit_block():
        with psycopg.connect(_libpq_url(), autocommit=True, row_factory=dict_row) as conn:
            PostgresSaver(conn).setup()


def downgrade() -> None:
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.drop_table("inbound_events")
    op.drop_table("capability_gaps")
