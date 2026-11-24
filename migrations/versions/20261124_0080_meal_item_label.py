"""What a meal item is called when shown: ``meal_items.display_name``.

Expand step of expand-then-contract (see deploy/README.md): one nullable column that the code
running before never touches, so a rolled-back deploy is unaffected. It holds the user's own word
for the food ("rice", or the item name from their photo); null means show the food's own name.
The food id and the nutrient snapshot are unchanged. ``meal_items`` keeps the row-level security
it already has.

Revision ID: 0080
Revises: 0079
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meal_items", sa.Column("display_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("meal_items", "display_name")
