"""Whether a scheduled payment counts as spending. Bills do; a regular investment or
a transfer to savings moves money without spending it, so marking it done logs
nothing.

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bills",
        sa.Column("spending", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("bills", "spending")
