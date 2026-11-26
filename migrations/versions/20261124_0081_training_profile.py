"""The Gym coach's inputs: days a week, session length, equipment, experience and focus.

Expand step of expand-then-contract (see deploy/README.md): one new table the code running
before never touches, so a rolled-back deploy is unaffected. It is a table of its own, not a
column on ``health_profiles``, so a user can set it before (or without) filling in the body
profile, and saving one never touches the other. One row per user; ``equipment`` is a JSON
list of the exercise catalogue's equipment values.

Row-level security is the policy 0056 gave the other user-owned tables (copied here on purpose:
a migration keeps meaning what it meant).

Revision ID: 0081
Revises: 0080
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"


def upgrade() -> None:
    op.create_table(
        "training_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("days_per_week", sa.Integer(), nullable=False),
        sa.Column("session_minutes", sa.Integer(), nullable=False),
        sa.Column("equipment", postgresql.JSONB(), nullable=False),
        sa.Column("experience", sa.Text(), nullable=False),
        sa.Column("focus", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "days_per_week BETWEEN 1 AND 7", name=op.f("ck_training_profiles_days_per_week")
        ),
        sa.CheckConstraint(
            "session_minutes BETWEEN 10 AND 240",
            name=op.f("ck_training_profiles_session_minutes"),
        ),
        sa.CheckConstraint(
            "experience IN ('beginner', 'intermediate', 'advanced')",
            name=op.f("ck_training_profiles_experience"),
        ),
        sa.CheckConstraint(
            "focus IN ('strength', 'hypertrophy', 'general')",
            name=op.f("ck_training_profiles_focus"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_training_profiles_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_training_profiles")),
    )
    op.execute("ALTER TABLE training_profiles ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON training_profiles FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY} ON training_profiles")
    op.drop_table("training_profiles")
