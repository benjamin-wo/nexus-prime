"""Web access: invites, sessions, and when a member was granted web access.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_invites_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by"], ["users.id"], name=op.f("fk_invites_redeemed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
    )
    op.create_table(
        "web_sessions",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_web_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_web_sessions")),
    )
    op.create_index("ix_web_sessions_user_id", "web_sessions", ["user_id"], unique=False)
    op.add_column(
        "users", sa.Column("web_access_granted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "web_access_granted_at")
    op.drop_index("ix_web_sessions_user_id", table_name="web_sessions")
    op.drop_table("web_sessions")
    op.drop_table("invites")
