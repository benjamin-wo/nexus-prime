"""A label for each day of a trip ("Busan"), and places to visit kept on a trip
without a day yet.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trips",
        sa.Column(
            "day_labels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("trip_bookings", "start_on", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM trip_bookings WHERE start_on IS NULL")
    op.alter_column("trip_bookings", "start_on", nullable=False)
    op.drop_column("trips", "day_labels")
