"""Sliding web sessions, and one-time sign-in links from the bot.

A session now carries its own length (``lifetime_seconds``) and whether it slides
(``renewable``): a renewable session used at least once a day is pushed out to a full
lifetime again, a non-renewable one (a short demo session, the Mini App's) never is. Rows
that exist keep their expiry and become renewable with a 90-day lifetime.

``login_links`` holds the links the bot's ``/web`` command sends: stored only as a hash,
valid for 5 minutes, spent once. Like ``web_sessions`` it belongs to a user by ``user_id``,
so it has the same row-level security policy as 0056 gave the other user-owned tables.

Revision ID: 0064
Revises: 0063
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NINETY_DAYS = 90 * 24 * 60 * 60
# As in 0056: with no user named for the transaction every row is visible.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
OWN = f"user_id = {NAMED}::uuid"
POLICY = f"USING ({NAMED} IS NULL OR {OWN}) WITH CHECK ({NAMED} IS NULL OR {OWN})"


def upgrade() -> None:
    op.add_column(
        "web_sessions",
        sa.Column("renewable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "web_sessions",
        sa.Column(
            "lifetime_seconds",
            sa.Integer(),
            server_default=sa.text(str(NINETY_DAYS)),
            nullable=False,
        ),
    )
    op.create_table(
        "login_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_login_links_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_login_links_token_hash")),
    )
    op.create_index("ix_login_links_user_id", "login_links", ["user_id"], unique=False)
    op.execute("ALTER TABLE login_links ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY nexus_user_rows ON login_links FOR ALL {POLICY}")


def downgrade() -> None:
    op.execute("DROP POLICY nexus_user_rows ON login_links")
    op.drop_index("ix_login_links_user_id", table_name="login_links")
    op.drop_table("login_links")
    op.drop_column("web_sessions", "lifetime_seconds")
    op.drop_column("web_sessions", "renewable")
