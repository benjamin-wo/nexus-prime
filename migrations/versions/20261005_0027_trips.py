"""Trips (M11a): dates, budget, set-aside and companions, and the expenses added to
or taken off a trip by hand.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("home_currency", sa.String(length=3), nullable=False),
        sa.Column("budget", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("set_aside", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("companions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("planned", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("end_on >= start_on", name=op.f("ck_trips_dates")),
        sa.CheckConstraint("budget IS NULL OR budget > 0", name=op.f("ck_trips_budget_positive")),
        sa.CheckConstraint(
            "set_aside IS NULL OR set_aside > 0", name=op.f("ck_trips_set_aside_positive")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_trips_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trips")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_trips_id_user_id")),
    )
    op.create_index("ix_trips_user_id_start_on", "trips", ["user_id", "start_on"], unique=False)
    op.create_table(
        "trip_links",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["trip_id", "user_id"],
            ["trips.id", "trips.user_id"],
            name=op.f("fk_trip_links_trip_id_user_id_trips"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name=op.f("fk_trip_links_transaction_id_user_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("trip_id", "transaction_id", name=op.f("pk_trip_links")),
    )
    op.create_index(
        "ix_trip_links_user_id_transaction_id",
        "trip_links",
        ["user_id", "transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trip_links_user_id_transaction_id", table_name="trip_links")
    op.drop_table("trip_links")
    op.drop_index("ix_trips_user_id_start_on", table_name="trips")
    op.drop_table("trips")
