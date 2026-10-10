"""A trip's read-only link for the people going on it.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trip_shares",
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["trip_id", "user_id"],
            ["trips.id", "trips.user_id"],
            name=op.f("fk_trip_shares_trip_id_user_id_trips"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_trip_shares_user_id_users")
        ),
        sa.PrimaryKeyConstraint("trip_id", name=op.f("pk_trip_shares")),
        sa.UniqueConstraint("token", name=op.f("uq_trip_shares_token")),
    )


def downgrade() -> None:
    op.drop_table("trip_shares")
