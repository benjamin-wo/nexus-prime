"""A workout the agent suggests for today, and what a started workout was planned as.

Expand step of expand-then-contract (see deploy/README.md): a new table, one new nullable
column on ``workouts`` and one on ``training_profiles``, and the five coach inputs made
nullable. The code running before always writes all five, so a rolled-back deploy is
unaffected; the only thing it could not read is a partly filled profile, which it only meets
after this deploy has written one.

``workout_suggestions``: what the agent suggested ("a back workout, 45 minutes"), kept for the
Start button on its card. Reads ignore one older than a day; nothing deletes them (the user's
data export and delete-my-data cover the table). ``workouts.planned_slots`` is the suggestion's
exercises, copied to the workout it started. ``training_profiles.place`` is where the user
trains ('gym' or 'home').

Row-level security is the policy 0056 gave the other user-owned tables (copied here on purpose:
a migration keeps meaning what it meant).

Revision ID: 0083
Revises: 0081
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0083"
down_revision: str | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"

INPUTS = ("days_per_week", "session_minutes", "equipment", "experience", "focus")


def upgrade() -> None:
    for column in INPUTS:
        op.alter_column("training_profiles", column, nullable=True)
    op.add_column("training_profiles", sa.Column("place", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_training_profiles_place"),
        "training_profiles",
        "place IS NULL OR place IN ('gym', 'home')",
    )
    op.add_column("workouts", sa.Column("planned_slots", postgresql.JSONB(), nullable=True))
    op.create_table(
        "workout_suggestions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("focus", sa.Text(), nullable=False),
        sa.Column("slots", postgresql.JSONB(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_workout_suggestions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workout_suggestions")),
    )
    op.create_index(
        "ix_workout_suggestions_user_id_created_at",
        "workout_suggestions",
        ["user_id", "created_at"],
    )
    op.execute("ALTER TABLE workout_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON workout_suggestions FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY} ON workout_suggestions")
    op.drop_table("workout_suggestions")
    op.drop_column("workouts", "planned_slots")
    # A partly filled profile can't be kept once the five are required again.
    op.execute(
        "DELETE FROM training_profiles WHERE days_per_week IS NULL OR session_minutes IS NULL "
        "OR equipment IS NULL OR experience IS NULL OR focus IS NULL"
    )
    op.drop_constraint(op.f("ck_training_profiles_place"), "training_profiles")
    op.drop_column("training_profiles", "place")
    for column in INPUTS:
        op.alter_column("training_profiles", column, nullable=False)
