"""Trips: costs split evenly by default, payments by other travellers, and whether a
share link shows bookings.

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trips",
        sa.Column("split_evenly", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "trips",
        sa.Column(
            "not_split",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "trip_shares",
        sa.Column("show_bookings", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_table(
        "trip_paid_by_others",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("person", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column(
            "split_with",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_trip_paid_by_others_amount_positive")),
        sa.ForeignKeyConstraint(
            ["trip_id", "user_id"],
            ["trips.id", "trips.user_id"],
            name=op.f("fk_trip_paid_by_others_trip_id_user_id_trips"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_trip_paid_by_others_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_paid_by_others")),
    )
    op.create_index(
        op.f("ix_trip_paid_by_others_user_id_trip_id"),
        "trip_paid_by_others",
        ["user_id", "trip_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_trip_paid_by_others_user_id_trip_id"), table_name="trip_paid_by_others")
    op.drop_table("trip_paid_by_others")
    op.drop_column("trip_shares", "show_bookings")
    op.drop_column("trips", "not_split")
    op.drop_column("trips", "split_evenly")
