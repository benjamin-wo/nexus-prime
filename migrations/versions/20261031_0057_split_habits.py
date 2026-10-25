"""Splitting habits: "I always split dinners with Ann".

One row per person and category the user has a habit for (``applies_to`` is a category's
name; NULL means any category), with the other person's ``share`` of the bill. Applied when an
expense is logged from chat. Like the user's other tables it has row-level security (see 0056):
once a transaction names a user (``app.user_id``) it shows and accepts only that user's rows.

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056 on purpose: a migration keeps meaning what it meant.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"


def upgrade() -> None:
    op.create_table(
        "split_habits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("person", sa.Text(), nullable=False),
        sa.Column("applies_to", sa.Text(), nullable=True),
        sa.Column(
            "share", sa.Numeric(precision=5, scale=4), server_default=sa.text("0.5"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("share > 0 AND share < 1", name=op.f("ck_split_habits_share_range")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_split_habits_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_split_habits")),
    )
    op.create_index(
        "uq_split_habits_user_id_lower_person_applies_to",
        "split_habits",
        [
            "user_id",
            sa.literal_column("lower(person)"),
            sa.literal_column("coalesce(applies_to, '')"),
        ],
        unique=True,
    )
    # The app's role is granted new tables by 0056's default privileges.
    op.execute("ALTER TABLE split_habits ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON split_habits FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY} ON split_habits")
    op.drop_index("uq_split_habits_user_id_lower_person_applies_to", table_name="split_habits")
    op.drop_table("split_habits")
