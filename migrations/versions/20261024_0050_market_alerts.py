"""Alerts during the US session, quiet hours and a morning summary of the stock market.

Per user: when quiet hours start and end, how big a move in a day is a big move, and
whether the morning summary is on (``notification_settings``). ``market_alerts`` keeps
each alert once per stock, kind and trading day.

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_settings",
        sa.Column("quiet_start", sa.Time(), server_default=sa.text("'23:00:00'"), nullable=False),
    )
    op.add_column(
        "notification_settings",
        sa.Column("quiet_end", sa.Time(), server_default=sa.text("'08:00:00'"), nullable=False),
    )
    op.add_column(
        "notification_settings",
        sa.Column(
            "move_alert_percent",
            sa.Numeric(precision=4, scale=1),
            server_default=sa.text("5"),
            nullable=False,
        ),
    )
    op.add_column(
        "notification_settings",
        sa.Column("market_summary", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_notification_settings_move_alert_percent"),
        "notification_settings",
        "move_alert_percent BETWEEN 1 AND 20",
    )
    op.create_table(
        "market_alerts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("urgent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('plan_entry', 'plan_stop', 'plan_target', 'big_move')",
            name=op.f("ck_market_alerts_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_market_alerts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_alerts")),
        sa.UniqueConstraint(
            "user_id",
            "symbol",
            "kind",
            "day",
            name=op.f("uq_market_alerts_user_id_symbol_kind_day"),
        ),
    )
    op.create_index(
        op.f("ix_market_alerts_user_id_day"), "market_alerts", ["user_id", "day"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_market_alerts_user_id_day"), table_name="market_alerts")
    op.drop_table("market_alerts")
    op.drop_constraint(
        op.f("ck_notification_settings_move_alert_percent"),
        "notification_settings",
        type_="check",
    )
    op.drop_column("notification_settings", "market_summary")
    op.drop_column("notification_settings", "move_alert_percent")
    op.drop_column("notification_settings", "quiet_end")
    op.drop_column("notification_settings", "quiet_start")
