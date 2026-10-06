"""Runner-up photos for a place and season (so a trip can show another), a trip's
choice to show no photo, and its packing list.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "destination_photos",
        sa.Column("rank", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.drop_constraint(
        op.f("uq_destination_photos_place_key_season"), "destination_photos", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_destination_photos_place_key_season_rank"),
        "destination_photos",
        ["place_key", "season", "rank"],
    )
    op.create_check_constraint(
        op.f("ck_destination_photos_rank_range"), "destination_photos", "rank BETWEEN 0 AND 9"
    )
    op.add_column(
        "trips",
        sa.Column("photo_off", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "trips",
        sa.Column(
            "packing",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("trips", "packing")
    op.drop_column("trips", "photo_off")
    op.drop_constraint(
        op.f("ck_destination_photos_rank_range"), "destination_photos", type_="check"
    )
    op.drop_constraint(
        op.f("uq_destination_photos_place_key_season_rank"), "destination_photos", type_="unique"
    )
    op.execute("DELETE FROM destination_photos WHERE rank > 0")
    op.create_unique_constraint(
        op.f("uq_destination_photos_place_key_season"),
        "destination_photos",
        ["place_key", "season"],
    )
    op.drop_column("destination_photos", "rank")
