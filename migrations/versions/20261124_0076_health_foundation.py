"""Health foundation: body and activity samples, the wellness profile, separate consents.

This is the expand step of expand-then-contract (see deploy/README.md): three new tables that
the code running before never touches, so a rolled-back deploy is unaffected.

- ``health_samples``: one table for measurements from any source (typed, chat, Health Connect,
  HealthKit, a brand's service). A value keeps the unit it was entered in. Imported samples are
  unique per (user, source, brand, external id); typed and chat entries per (user, kind, start).
- ``health_profiles``: one row per user, the figures energy and goal numbers are worked from.
- ``health_consents``: withdrawable consents by scope, beside ``users.health_consent_at`` (0075),
  which stays the master "health processing" consent.

Every new user-owned table gets row-level security, the policy 0056 gave the others (copied
here on purpose: a migration keeps meaning what it meant). The app's role is granted new tables
by 0056's default privileges.

Revision ID: 0076
Revises: 0075
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"

TABLES = ("health_samples", "health_profiles", "health_consents")


def upgrade() -> None:
    op.create_table(
        "health_samples",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('weight', 'body_fat', 'steps', 'active_energy', 'resting_heart_rate', "
            "'hrv', 'sleep', 'workout')",
            name=op.f("ck_health_samples_kind"),
        ),
        sa.CheckConstraint(
            "unit IN ('kg', 'lb', 'percent', 'count', 'kcal', 'bpm', 'ms', 'min')",
            name=op.f("ck_health_samples_unit"),
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'chat', 'health_connect', 'healthkit', 'oauth')",
            name=op.f("ck_health_samples_source"),
        ),
        sa.CheckConstraint("value >= 0", name=op.f("ck_health_samples_value_not_negative")),
        sa.CheckConstraint("end_at >= start_at", name=op.f("ck_health_samples_end_after_start")),
        sa.CheckConstraint(
            "(source = 'oauth') = (source_name IS NOT NULL)",
            name=op.f("ck_health_samples_source_name"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_health_samples_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_health_samples")),
    )
    op.create_index(
        "ix_health_samples_user_id_kind_start_at",
        "health_samples",
        ["user_id", "kind", "start_at"],
    )
    op.create_index(
        "uq_health_samples_user_id_source_external_id",
        "health_samples",
        ["user_id", "source", sa.text("coalesce(source_name, '')"), "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "uq_health_samples_manual_user_id_kind_start_at",
        "health_samples",
        ["user_id", "kind", "start_at"],
        unique=True,
        postgresql_where=sa.text("source IN ('manual', 'chat') AND external_id IS NULL"),
    )

    op.create_table(
        "health_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("sex_for_equations", sa.Text(), nullable=False),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("height_cm", sa.Numeric(4, 1), nullable=True),
        sa.Column("activity_level", sa.Text(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("target_rate_pct_per_week", sa.Numeric(4, 2), nullable=True),
        sa.Column("numbers_free", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ed_history", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("unit_system", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sex_for_equations IN ('female', 'male', 'unspecified')",
            name=op.f("ck_health_profiles_sex"),
        ),
        sa.CheckConstraint(
            "activity_level IS NULL OR activity_level IN "
            "('sedentary', 'light', 'moderate', 'active', 'very_active')",
            name=op.f("ck_health_profiles_activity_level"),
        ),
        sa.CheckConstraint(
            "goal IN ('lose', 'maintain', 'gain', 'performance')",
            name=op.f("ck_health_profiles_goal"),
        ),
        sa.CheckConstraint(
            "unit_system IN ('metric', 'imperial')", name=op.f("ck_health_profiles_unit_system")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_health_profiles_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_health_profiles")),
    )

    op.create_table(
        "health_consents",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('ai_processing', 'source:health_connect', 'source:healthkit', "
            "'source:oauth', 'model_improvement')",
            name=op.f("ck_health_consents_scope"),
        ),
        sa.CheckConstraint(
            "withdrawn_at IS NULL OR withdrawn_at >= granted_at",
            name=op.f("ck_health_consents_withdrawn_after"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_health_consents_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "scope", name=op.f("pk_health_consents")),
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
    op.drop_table("health_consents")
    op.drop_table("health_profiles")
    op.drop_table("health_samples")
