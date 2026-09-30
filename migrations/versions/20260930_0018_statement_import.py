"""Statement import: saved CSV layouts per bank, and each confirmed import.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "statement_mappings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("header_key", sa.Text(), nullable=False),
        sa.Column("mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 60", name=op.f("ck_statement_mappings_name_length")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_statement_mappings_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statement_mappings")),
        sa.UniqueConstraint(
            "user_id", "header_key", name=op.f("uq_statement_mappings_user_id_header_key")
        ),
    )
    op.create_table(
        "statement_imports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("transaction_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_statement_imports_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statement_imports")),
    )
    op.create_index(
        "ix_statement_imports_user_id_created_at",
        "statement_imports",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_statement_imports_user_id_created_at", table_name="statement_imports")
    op.drop_table("statement_imports")
    op.drop_table("statement_mappings")
