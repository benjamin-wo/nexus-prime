"""Bookings read from email (M11b), and travel reminders already sent.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trip_bookings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=True),
        sa.Column("email_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('flight', 'hotel', 'rail')", name=op.f("ck_trip_bookings_kind")
        ),
        sa.CheckConstraint(
            "(amount IS NULL) = (currency IS NULL)", name=op.f("ck_trip_bookings_cost")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_trip_bookings_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["trip_id", "user_id"],
            ["trips.id", "trips.user_id"],
            name=op.f("fk_trip_bookings_trip_id_user_id_trips"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name=op.f("fk_trip_bookings_transaction_id_user_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_bookings")),
        sa.UniqueConstraint("user_id", "email_id", name=op.f("uq_trip_bookings_user_id_email_id")),
    )
    op.create_index(
        "ix_trip_bookings_user_id_start_on", "trip_bookings", ["user_id", "start_on"], unique=False
    )
    op.create_table(
        "trip_reminders",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_trip_reminders_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name=op.f("pk_trip_reminders")),
    )


def downgrade() -> None:
    op.drop_table("trip_reminders")
    op.drop_index("ix_trip_bookings_user_id_start_on", table_name="trip_bookings")
    op.drop_table("trip_bookings")
