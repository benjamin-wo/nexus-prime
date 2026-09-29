"""Forwarding addresses: a second kind of email connection, and when one last
heard anything (so a quiet one gets a nudge).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("email_connections", sa.Column("last_received_at", sa.DateTime(timezone=True)))
    op.add_column("email_connections", sa.Column("nudged_at", sa.DateTime(timezone=True)))
    op.drop_constraint(op.f("ck_email_connections_provider"), "email_connections", type_="check")
    op.create_check_constraint(
        op.f("ck_email_connections_provider"),
        "email_connections",
        "provider IN ('gmail', 'forward')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM email_connections WHERE provider = 'forward'")
    op.drop_constraint(op.f("ck_email_connections_provider"), "email_connections", type_="check")
    op.create_check_constraint(
        op.f("ck_email_connections_provider"), "email_connections", "provider IN ('gmail')"
    )
    op.drop_column("email_connections", "nudged_at")
    op.drop_column("email_connections", "last_received_at")
