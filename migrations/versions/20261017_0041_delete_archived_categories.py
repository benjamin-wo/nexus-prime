"""Categories are deleted, not archived: archived ones with no transactions go (with
their rules and budget), the rest become normal categories again, and the flag goes.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    db = op.get_bind()
    empty = [
        row.id
        for row in db.execute(
            sa.text(
                "SELECT c.id FROM categories AS c WHERE NOT c.active "
                "AND NOT EXISTS (SELECT 1 FROM transactions AS t WHERE t.category_id = c.id)"
            )
        )
    ]
    if empty:
        # A transaction can still name a rule of such a category; the check
        # (category_rule_id IS NULL OR category_id IS NOT NULL) only needs the rule id cleared.
        for statement in (
            "UPDATE transactions SET category_rule_id = NULL WHERE category_rule_id IN "
            "(SELECT id FROM category_rules WHERE category_id IN :ids)",
            "DELETE FROM category_rules WHERE category_id IN :ids",
            "DELETE FROM budgets WHERE category_id IN :ids",
            "DELETE FROM categories WHERE id IN :ids",
        ):
            db.execute(sa.text(statement).bindparams(sa.bindparam("ids", empty, expanding=True)))
    op.execute("UPDATE categories SET active = true WHERE NOT active")
    op.drop_column("categories", "active")


def downgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
