"""The shared exercise catalogue: an ``exercises`` table for the Health -> Gym app.

This is the expand step of expand-then-contract (see deploy/README.md): a new table that the
code running before it never touches, so a rolled-back deploy is unaffected.

``exercises`` holds the same rows for every user (free-exercise-db, public domain), keyed by
the source's own id. It has no ``user_id`` and no row-level security. It is created empty: the
app loads ``nexus/infra/exercises/catalogue.json`` into it at startup (an idempotent upsert), so
a data update never needs a migration. The app's role gets its privileges from 0056's default
ones.

Revision ID: 0074
Revises: 0073
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY = sa.text("'{}'::text[]")


def upgrade() -> None:
    op.create_table(
        "exercises",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("equipment", sa.Text(), nullable=True),
        sa.Column("force", sa.Text(), nullable=True),
        sa.Column("mechanic", sa.Text(), nullable=True),
        sa.Column("primary_muscles", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "secondary_muscles", postgresql.ARRAY(sa.Text()), nullable=False, server_default=EMPTY
        ),
        sa.Column(
            "instructions", postgresql.ARRAY(sa.Text()), nullable=False, server_default=EMPTY
        ),
        sa.Column("images", postgresql.ARRAY(sa.Text()), nullable=False, server_default=EMPTY),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exercises")),
    )


def downgrade() -> None:
    op.drop_table("exercises")
