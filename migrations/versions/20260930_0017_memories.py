"""What Nexus remembers about each user: facts, preferences and episodes.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("happened_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('fact', 'preference', 'episode')", name=op.f("ck_memories_kind")
        ),
        sa.CheckConstraint("length(text) BETWEEN 1 AND 300", name=op.f("ck_memories_text_length")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_memories_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
    )
    op.create_index(
        "ix_memories_user_id_updated_at", "memories", ["user_id", "updated_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_memories_user_id_updated_at", table_name="memories")
    op.drop_table("memories")
