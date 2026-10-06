"""The chat as the user saw it, so the web chat can show it again.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user', 'nexus')", name=op.f("ck_chat_log_role")),
        sa.CheckConstraint("length(text) BETWEEN 1 AND 4000", name=op.f("ck_chat_log_text_length")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_chat_log_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_log")),
    )
    op.create_index("ix_chat_log_user_id_id", "chat_log", ["user_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_chat_log_user_id_id", table_name="chat_log")
    op.drop_table("chat_log")
