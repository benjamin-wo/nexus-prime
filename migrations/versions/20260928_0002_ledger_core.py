"""Ledger core: users, categories, transactions, sources, revisions, splits, settlements.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("home_currency", sa.String(length=3), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("home_currency ~ '^[A-Z]{3}$'", name=op.f("ck_users_home_currency")),
        sa.CheckConstraint("role IN ('owner', 'member')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_user_id", name=op.f("uq_users_telegram_user_id")),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_categories_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_categories_id_user_id")),
    )
    op.create_index(
        "uq_categories_user_id_lower_name",
        "categories",
        ["user_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counterparty", sa.Text(), nullable=True),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_transactions_currency")),
        sa.CheckConstraint("direction IN ('in', 'out')", name=op.f("ck_transactions_direction")),
        sa.CheckConstraint(
            "source IN ('text', 'photo', 'email', 'import', 'manual')",
            name=op.f("ck_transactions_source"),
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'pending')", name=op.f("ck_transactions_status")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_transactions_amount_positive")),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name=op.f("fk_transactions_category_id_user_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_transactions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_transactions_id_user_id")),
    )
    op.create_index(
        "ix_transactions_user_id_occurred_at",
        "transactions",
        ["user_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "splits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("participant_name", sa.Text(), nullable=False),
        sa.Column("share_amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("share_amount > 0", name=op.f("ck_splits_share_positive")),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name=op.f("fk_splits_transaction_id_user_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_splits")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_splits_id_user_id")),
    )
    op.create_index(
        "ix_splits_user_id_transaction_id", "splits", ["user_id", "transaction_id"], unique=False
    )
    op.create_table(
        "transaction_revisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('create', 'edit', 'delete', 'restore', 'split')",
            name=op.f("ck_transaction_revisions_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name=op.f("fk_transaction_revisions_transaction_id_user_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_revisions")),
    )
    op.create_index(
        "ix_transaction_revisions_user_id_id",
        "transaction_revisions",
        ["user_id", "id"],
        unique=False,
    )
    op.create_table(
        "transaction_sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name=op.f("fk_transaction_sources_transaction_id_user_id_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_transaction_sources_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_sources")),
        sa.UniqueConstraint(
            "user_id",
            "source",
            "external_id",
            name=op.f("uq_transaction_sources_user_id_source_external_id"),
        ),
    )
    op.create_table(
        "settlements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("split_id", sa.UUID(), nullable=False),
        sa.Column("income_transaction_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_settlements_amount_positive")),
        sa.ForeignKeyConstraint(
            ["income_transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name=op.f("fk_settlements_income_transaction_id_user_id_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["split_id", "user_id"],
            ["splits.id", "splits.user_id"],
            name=op.f("fk_settlements_split_id_user_id_splits"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settlements")),
    )
    op.create_index("ix_settlements_split_id", "settlements", ["split_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_settlements_split_id", table_name="settlements")
    op.drop_table("settlements")
    op.drop_table("transaction_sources")
    op.drop_index("ix_transaction_revisions_user_id_id", table_name="transaction_revisions")
    op.drop_table("transaction_revisions")
    op.drop_index("ix_splits_user_id_transaction_id", table_name="splits")
    op.drop_table("splits")
    op.drop_index("ix_transactions_user_id_occurred_at", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("uq_categories_user_id_lower_name", table_name="categories")
    op.drop_table("categories")
    op.drop_table("users")
