"""Category rules, and which rule filed each transaction.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "category_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(pattern) BETWEEN 2 AND 60",
            name=op.f("ck_category_rules_pattern_length"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name=op.f("fk_category_rules_category_id_user_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_category_rules_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_rules")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_category_rules_id_user_id")),
    )
    op.create_index(
        "uq_category_rules_user_id_pattern",
        "category_rules",
        ["user_id", "pattern"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.add_column("transactions", sa.Column("category_rule_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_transactions_category_rule_id_user_id_category_rules"),
        "transactions",
        "category_rules",
        ["category_rule_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_check_constraint(
        op.f("ck_transactions_rule_needs_category"),
        "transactions",
        "category_rule_id IS NULL OR category_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_transactions_rule_needs_category"), "transactions", type_="check")
    op.drop_constraint(
        op.f("fk_transactions_category_rule_id_user_id_category_rules"),
        "transactions",
        type_="foreignkey",
    )
    op.drop_column("transactions", "category_rule_id")
    op.drop_index("uq_category_rules_user_id_pattern", table_name="category_rules")
    op.drop_table("category_rules")
