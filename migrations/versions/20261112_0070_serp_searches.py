"""Live fare and price searches each user made each day, for the per-user daily limit.

The app's SerpApi searches (flight fares, product prices, flight status) are capped at 10 a
day for each user, and at 240 a month for the whole app. The monthly count needs no table of
its own: it is a row in ``web_credits`` (0037) with the product ``serpapi``, so the trip
researcher's searches and the chat's are counted in one place. This adds the per-user day:
one row per user and day with how many searches were let through. Only a count, never what
was searched for. Like the user's other tables it has row-level security (see 0056): once a
transaction names a user (``app.user_id``) it shows and accepts only that user's rows. Rows
go with the user.

Revision ID: 0070
Revises: 0069
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056 on purpose: a migration keeps meaning what it meant.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"


def upgrade() -> None:
    op.create_table(
        "serp_searches",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("searches", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("searches >= 0", name=op.f("ck_serp_searches_not_negative")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_serp_searches_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "day", name=op.f("pk_serp_searches")),
    )
    # The app's role is granted new tables by 0056's default privileges.
    op.execute("ALTER TABLE serp_searches ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON serp_searches FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY} ON serp_searches")
    op.drop_table("serp_searches")
