"""Header photos for trips: a famous view of the place, in the season, kept once and
shared by every trip there.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "destination_photos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("place_key", sa.Text(), nullable=False),
        sa.Column("season", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Numeric(8, 5), nullable=True),
        sa.Column("spot", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("licence", sa.Text(), nullable=True),
        sa.Column("licence_url", sa.Text(), nullable=True),
        sa.Column("page", sa.Text(), nullable=True),
        sa.Column("mime", sa.Text(), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "season IN ('spring', 'summer', 'autumn', 'winter', 'any')",
            name=op.f("ck_destination_photos_season"),
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'none')", name=op.f("ck_destination_photos_status")
        ),
        sa.CheckConstraint(
            "status = 'none' OR (data IS NOT NULL AND mime IS NOT NULL AND author IS NOT NULL "
            "AND licence IS NOT NULL)",
            name=op.f("ck_destination_photos_ready_has_photo"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_destination_photos")),
        sa.UniqueConstraint(
            "place_key", "season", name=op.f("uq_destination_photos_place_key_season")
        ),
    )
    op.add_column("trips", sa.Column("photo_id", sa.UUID(), nullable=True))
    op.add_column("trips", sa.Column("photo_tried_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_trips_photo_id_destination_photos"),
        "trips",
        "destination_photos",
        ["photo_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_trips_photo_id_destination_photos"), "trips", type_="foreignkey")
    op.drop_column("trips", "photo_tried_at")
    op.drop_column("trips", "photo_id")
    op.drop_table("destination_photos")
