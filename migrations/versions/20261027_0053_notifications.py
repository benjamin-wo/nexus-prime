"""A record of every Telegram message, and a daily cap on how many a user gets.

``notifications`` keeps each message Nexus meant to send for 30 days: sent, held for quiet
hours or the next digest, told in a digest, or dropped. ``notification_settings.daily_cap``
is how many a day (3 to 20) go before the rest wait for a digest.

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_settings",
        sa.Column("daily_cap", sa.SmallInteger(), server_default=sa.text("6"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_notification_settings_daily_cap"),
        "notification_settings",
        "daily_cap BETWEEN 3 AND 20",
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("has_buttons", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("held_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("digest_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "level IN ('urgent', 'now', 'digest')", name=op.f("ck_notifications_level")
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'held', 'digested', 'dropped')",
            name=op.f("ck_notifications_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        op.f("ix_notifications_user_id_created_at"),
        "notifications",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_user_id_created_at"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_constraint(
        op.f("ck_notification_settings_daily_cap"), "notification_settings", type_="check"
    )
    op.drop_column("notification_settings", "daily_cap")
