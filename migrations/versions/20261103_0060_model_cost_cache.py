"""How many of each day's input tokens the provider served from its prompt cache.

``cached_tokens`` is a part of ``input_tokens`` (cached input costs a fraction of the rest), so
the cost page can show how much of what is sent is cached. Rows from before this count 0.

Revision ID: 0060
Revises: 0059
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_costs",
        sa.Column("cached_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("model_costs", "cached_tokens")
