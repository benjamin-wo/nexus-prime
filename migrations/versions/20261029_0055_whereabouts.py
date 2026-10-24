"""Each user's current time zone follows where they are; their home zone is kept.

``users.timezone`` stays the current zone, so everything that reads it follows. New:
``home_timezone`` (where they live; the zone they go back to), ``timezone_source`` (what
set the current zone: home, phone, chat or trip) and ``timezone_set_at`` (when their
phone or they last said where they are; null if never).

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("home_timezone", sa.Text(), nullable=True))
    op.execute("UPDATE users SET home_timezone = timezone")
    op.alter_column("users", "home_timezone", nullable=False)
    op.add_column(
        "users",
        sa.Column("timezone_source", sa.Text(), server_default=sa.text("'home'"), nullable=False),
    )
    op.add_column("users", sa.Column("timezone_set_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_timezone_source"),
        "users",
        "timezone_source IN ('home', 'phone', 'chat', 'trip')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_timezone_source"), "users", type_="check")
    op.drop_column("users", "timezone_set_at")
    op.drop_column("users", "timezone_source")
    op.drop_column("users", "home_timezone")
