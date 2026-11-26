"""Gym training data: routines, a training plan, workouts and their sets.

This is the expand step of expand-then-contract (see deploy/README.md): four new tables and
two nullable columns on ``users`` that the code running before never touches, so a rolled-back
deploy is unaffected.

- ``routines`` (slots as JSONB), ``training_plans`` (one row per user), ``workouts`` and
  ``workout_sets`` (deleted with their workout; each points at the shared ``exercises``).
- ``users.show_health``: whether Health shows in the web menu, with the same three states as
  ``show_invest`` and ``show_travel`` (0068): null undecided, true shown, false switched off.
  Nobody has Health data yet, so nobody needs the backfill 0068 did.
- ``users.health_consent_at``: when the user agreed to Nexus keeping their health data; null
  if they haven't or withdrew. Writes to the new tables need it (checked by the app).

Every new user-owned table gets row-level security, the policy 0056 gave the others (copied
here on purpose: a migration keeps meaning what it meant). The app's role is granted new tables
by 0056's default privileges.

Revision ID: 0075
Revises: 0074
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"

TABLES = ("routines", "training_plans", "workouts", "workout_sets")


def upgrade() -> None:
    op.add_column("users", sa.Column("show_health", sa.Boolean(), nullable=True))
    op.add_column(
        "users", sa.Column("health_consent_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "routines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slots", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("jsonb_typeof(slots) = 'array'", name=op.f("ck_routines_slots_array")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_routines_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routines")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_routines_id_user_id")),
    )
    op.create_index("ix_routines_user_id_created_at", "routines", ["user_id", "created_at"])

    op.create_table(
        "training_plans",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "weekly",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "rotation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('weekly', 'rotation')", name=op.f("ck_training_plans_kind")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_training_plans_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_training_plans")),
    )

    op.create_table(
        "workouts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("routine_id", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_workouts_finish_after_start"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workouts_user_id_users")),
        sa.ForeignKeyConstraint(
            ["routine_id", "user_id"],
            ["routines.id", "routines.user_id"],
            name=op.f("fk_workouts_routine_id_user_id_routines"),
            ondelete="SET NULL (routine_id)",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workouts")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_workouts_id_user_id")),
    )
    op.create_index("ix_workouts_user_id_started_at", "workouts", ["user_id", "started_at"])

    op.create_table(
        "workout_sets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("workout_id", sa.UUID(), nullable=False),
        sa.Column("exercise_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Numeric(7, 2), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=True),
        sa.Column("rpe", sa.Numeric(3, 1), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('warmup', 'working')", name=op.f("ck_workout_sets_kind")),
        sa.CheckConstraint("unit IN ('kg', 'lb')", name=op.f("ck_workout_sets_unit")),
        sa.CheckConstraint(
            "reps IS NOT NULL OR seconds IS NOT NULL", name=op.f("ck_workout_sets_reps_or_seconds")
        ),
        sa.CheckConstraint("reps IS NULL OR reps > 0", name=op.f("ck_workout_sets_reps_positive")),
        sa.CheckConstraint(
            "seconds IS NULL OR seconds > 0", name=op.f("ck_workout_sets_seconds_positive")
        ),
        sa.CheckConstraint(
            "weight IS NULL OR weight >= 0", name=op.f("ck_workout_sets_weight_not_negative")
        ),
        sa.CheckConstraint(
            "rpe IS NULL OR (rpe BETWEEN 1 AND 10 AND rpe * 2 = round(rpe * 2))",
            name=op.f("ck_workout_sets_rpe"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_workout_sets_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workout_id", "user_id"],
            ["workouts.id", "workouts.user_id"],
            name=op.f("fk_workout_sets_workout_id_user_id_workouts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"], ["exercises.id"], name=op.f("fk_workout_sets_exercise_id_exercises")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workout_sets")),
    )
    op.create_index(
        "ix_workout_sets_user_id_exercise_id_done_at",
        "workout_sets",
        ["user_id", "exercise_id", "done_at"],
    )
    op.create_index(
        "ix_workout_sets_workout_id_position", "workout_sets", ["workout_id", "position"]
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} FOR ALL "
            f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY {POLICY} ON {table}")
    op.drop_table("workout_sets")
    op.drop_table("workouts")
    op.drop_table("training_plans")
    op.drop_table("routines")
    op.drop_column("users", "health_consent_at")
    op.drop_column("users", "show_health")
