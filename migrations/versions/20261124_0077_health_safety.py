"""Health safety: when a safety signal first fired.

Expand step (see deploy/README.md): one new table that the code running before never touches.
``health_safety_events`` holds a signal kind and a time per row, never free text, so the app
can show a soft check-in once. Row-level security is the policy 0056 gave the others (copied
here on purpose: a migration keeps meaning what it meant).

Revision ID: 0077
Revises: 0076
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"
TABLE = "health_safety_events"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('intake_below_floor', 'rapid_loss', 'many_weigh_ins', "
            "'compensating_language')",
            name=op.f("ck_health_safety_events_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_health_safety_events_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_health_safety_events")),
    )
    op.create_index(
        "ix_health_safety_events_user_id_kind_created_at", TABLE, ["user_id", "kind", "created_at"]
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY} ON {TABLE}")
    op.drop_table(TABLE)
