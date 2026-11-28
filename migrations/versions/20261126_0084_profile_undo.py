"""What a health profile was before Prime changed it, for the Undo button.

Expand step of expand-then-contract (see deploy/README.md): one new table, nothing else. The
code running before never reads it.

``profile_undo``: when Prime saves a profile change from chat, the profile as it was goes here
under a random token, and the reply's Undo button carries that token. Pressing it puts the old
profile back (``previous`` NULL: there was none, so the profile is removed) if the row is under
30 minutes old. A server-side table rather than a map in memory, so any worker can answer the
press. Rows are the user's own: the data export and delete-my-data cover the table.

Row-level security is the policy 0056 gave the other user-owned tables (copied here on purpose:
a migration keeps meaning what it meant).

Revision ID: 0084
Revises: 0083
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"


def upgrade() -> None:
    op.create_table(
        "profile_undo",
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("previous", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_profile_undo_user_id_users")
        ),
        sa.PrimaryKeyConstraint("token", name=op.f("pk_profile_undo")),
    )
    op.create_index("ix_profile_undo_user_id_created_at", "profile_undo", ["user_id", "created_at"])
    op.execute("ALTER TABLE profile_undo ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON profile_undo FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY} ON profile_undo")
    op.drop_table("profile_undo")
