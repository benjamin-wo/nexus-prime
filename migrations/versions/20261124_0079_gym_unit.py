"""The weight unit a user logs sets in: ``users.weight_unit`` ('kg' or 'lb').

Expand step of expand-then-contract (see deploy/README.md): one nullable column that the code
running before never touches, so a rolled-back deploy is unaffected. Null means no choice yet,
and logging a set without a unit then uses kg. Every ``users`` row keeps the row-level security
it already has.

Revision ID: 0079
Revises: 0075
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("weight_unit", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "weight_unit")
