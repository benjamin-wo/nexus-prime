"""How a trip gets about (public transport or a hire car), and the way picked for
each hop between two of its entries.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trips",
        sa.Column("getting_around", sa.Text(), server_default=sa.text("'transit'"), nullable=False),
    )
    op.add_column(
        "trips",
        sa.Column(
            "hop_modes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_trips_getting_around_known"), "trips", "getting_around IN ('transit', 'car')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_trips_getting_around_known"), "trips", type_="check")
    op.drop_column("trips", "hop_modes")
    op.drop_column("trips", "getting_around")
