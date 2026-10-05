"""Itinerary entries added by hand: plans (activities) as a booking kind, and free
notes on a trip.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("notes", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_trip_bookings_kind"), "trip_bookings", type_="check")
    op.create_check_constraint(
        op.f("ck_trip_bookings_kind"),
        "trip_bookings",
        "kind IN ('flight', 'hotel', 'rail', 'activity')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM trip_bookings WHERE kind = 'activity'")
    op.drop_constraint(op.f("ck_trip_bookings_kind"), "trip_bookings", type_="check")
    op.create_check_constraint(
        op.f("ck_trip_bookings_kind"), "trip_bookings", "kind IN ('flight', 'hotel', 'rail')"
    )
    op.drop_column("trips", "notes")
