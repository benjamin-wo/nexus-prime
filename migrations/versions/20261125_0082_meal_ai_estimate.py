"""A meal item can be the model's own estimate, for a food that isn't in the database.

Expand step of expand-then-contract (see deploy/README.md): ``meal_items.food_id`` becomes
nullable and ``source_detail`` is a new column with a default, so the code running before keeps
working (it writes ``food_id`` always and never reads ``source_detail``). A row with no
``food_id`` must say ``ai_estimate``; ``estimate_kind`` gains the value ``ai_estimate``. Row
security is untouched: no table is added.

Revision ID: 0082
Revises: 0081
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "estimate_kind IN ('weighed', 'portion', 'estimated')"
NEW_KINDS = "estimate_kind IN ('weighed', 'portion', 'estimated', 'ai_estimate')"


def upgrade() -> None:
    op.alter_column("meal_items", "food_id", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "meal_items",
        sa.Column("source_detail", sa.Text(), nullable=False, server_default="db"),
    )
    op.drop_constraint(op.f("ck_meal_items_estimate_kind"), "meal_items", type_="check")
    op.create_check_constraint(op.f("ck_meal_items_estimate_kind"), "meal_items", NEW_KINDS)
    op.create_check_constraint(
        op.f("ck_meal_items_source_detail"),
        "meal_items",
        "source_detail IN ('db', 'ai_estimate')",
    )
    op.create_check_constraint(
        op.f("ck_meal_items_food_or_estimate"),
        "meal_items",
        "food_id IS NOT NULL OR source_detail = 'ai_estimate'",
    )


def downgrade() -> None:
    op.execute("DELETE FROM meal_items WHERE food_id IS NULL")
    op.drop_constraint(op.f("ck_meal_items_food_or_estimate"), "meal_items", type_="check")
    op.drop_constraint(op.f("ck_meal_items_source_detail"), "meal_items", type_="check")
    op.drop_constraint(op.f("ck_meal_items_estimate_kind"), "meal_items", type_="check")
    op.execute("DELETE FROM meal_items WHERE estimate_kind = 'ai_estimate'")
    op.create_check_constraint(op.f("ck_meal_items_estimate_kind"), "meal_items", OLD_KINDS)
    op.drop_column("meal_items", "source_detail")
    op.alter_column("meal_items", "food_id", existing_type=sa.Text(), nullable=False)
