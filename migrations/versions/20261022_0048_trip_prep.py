"""A trip's Prep tab: to-dos, the suggestions marked "Not needed", and cover and
documents (travel insurance, visas, other documents).

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trips",
        sa.Column(
            "todos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "trips",
        sa.Column(
            "prep_dismissed",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_table(
        "trip_covers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("starts", sa.Date(), nullable=True),
        sa.Column("ends", sa.Date(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=True),
        sa.Column("logged_transaction_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('insurance', 'visa', 'document', 'other')",
            name=op.f("ck_trip_covers_kind"),
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80", name=op.f("ck_trip_covers_name_length")
        ),
        sa.CheckConstraint(
            "reference IS NULL OR char_length(reference) <= 60",
            name=op.f("ck_trip_covers_reference_length"),
        ),
        sa.CheckConstraint(
            "phone IS NULL OR char_length(phone) <= 30", name=op.f("ck_trip_covers_phone_length")
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 200", name=op.f("ck_trip_covers_note_length")
        ),
        sa.CheckConstraint(
            "starts IS NULL OR ends IS NULL OR ends >= starts", name=op.f("ck_trip_covers_dates")
        ),
        sa.CheckConstraint(
            "cost_amount IS NULL OR cost_amount > 0", name=op.f("ck_trip_covers_cost_positive")
        ),
        sa.CheckConstraint(
            "(cost_amount IS NULL) = (cost_currency IS NULL)", name=op.f("ck_trip_covers_cost")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_trip_covers_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["trip_id", "user_id"],
            ["trips.id", "trips.user_id"],
            name=op.f("fk_trip_covers_trip_id_user_id_trips"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["logged_transaction_id"],
            ["transactions.id"],
            name=op.f("fk_trip_covers_logged_transaction_id_transactions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_covers")),
    )
    op.create_index(
        op.f("ix_trip_covers_user_id_trip_id"), "trip_covers", ["user_id", "trip_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_trip_covers_user_id_trip_id"), table_name="trip_covers")
    op.drop_table("trip_covers")
    op.drop_column("trips", "prep_dismissed")
    op.drop_column("trips", "todos")
