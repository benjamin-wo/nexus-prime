"""Wallets: named places money sits, and moves of money between a user's own wallets.

A move is a transaction with direction 'move' and a from and a to wallet. Every user gets
a Spending wallet (the account the budget watches).

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOVE_WALLETS = (
    "(direction = 'move' AND from_wallet_id IS NOT NULL AND to_wallet_id IS NOT NULL "
    "AND from_wallet_id <> to_wallet_id) "
    "OR (direction <> 'move' AND from_wallet_id IS NULL AND to_wallet_id IS NULL)"
)


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "match_words",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('spending', 'investment', 'savings', 'card', 'other')",
            name=op.f("ck_wallets_kind"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_wallets_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallets")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_wallets_id_user_id")),
    )
    op.create_index(
        "uq_wallets_user_id_lower_name",
        "wallets",
        ["user_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_index(
        "uq_wallets_user_id_spending",
        "wallets",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'spending'"),
    )
    op.execute(
        "INSERT INTO wallets (id, user_id, name, kind) "
        "SELECT gen_random_uuid(), id, 'Spending', 'spending' FROM users"
    )

    op.add_column("transactions", sa.Column("from_wallet_id", sa.UUID(), nullable=True))
    op.add_column("transactions", sa.Column("to_wallet_id", sa.UUID(), nullable=True))
    op.add_column("transactions", sa.Column("received_amount", sa.Numeric(19, 4), nullable=True))
    op.add_column("transactions", sa.Column("received_currency", sa.String(3), nullable=True))
    for column in ("from_wallet_id", "to_wallet_id"):
        op.create_foreign_key(
            op.f(f"fk_transactions_{column}_user_id_wallets"),
            "transactions",
            "wallets",
            [column, "user_id"],
            ["id", "user_id"],
        )
    op.drop_constraint(op.f("ck_transactions_direction"), "transactions", type_="check")
    op.create_check_constraint(
        op.f("ck_transactions_direction"), "transactions", "direction IN ('in', 'out', 'move')"
    )
    op.create_check_constraint(op.f("ck_transactions_move_wallets"), "transactions", MOVE_WALLETS)
    op.create_check_constraint(
        op.f("ck_transactions_move_no_category"),
        "transactions",
        "direction <> 'move' OR (category_id IS NULL AND category_rule_id IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_transactions_received_pair"),
        "transactions",
        "(received_amount IS NULL) = (received_currency IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_transactions_received_positive"),
        "transactions",
        "received_amount IS NULL OR received_amount > 0",
    )


def downgrade() -> None:
    # Moves have no place in the old schema: they go, with whatever pointed at them.
    moves = "(SELECT id FROM transactions WHERE direction = 'move')"
    op.execute(f"DELETE FROM transaction_revisions WHERE transaction_id IN {moves}")  # noqa: S608
    op.execute(f"DELETE FROM trip_links WHERE transaction_id IN {moves}")  # noqa: S608
    for table in ("receipts", "transaction_sources", "inbound_emails", "trip_bookings"):
        # Fixed table names above, no user input.
        op.execute(f"UPDATE {table} SET transaction_id = NULL WHERE transaction_id IN {moves}")  # noqa: S608
    op.execute("DELETE FROM transactions WHERE direction = 'move'")

    for name in (
        "received_positive",
        "received_pair",
        "move_no_category",
        "move_wallets",
        "direction",
    ):
        op.drop_constraint(op.f(f"ck_transactions_{name}"), "transactions", type_="check")
    op.create_check_constraint(
        op.f("ck_transactions_direction"), "transactions", "direction IN ('in', 'out')"
    )
    for column in ("to_wallet_id", "from_wallet_id"):
        op.drop_constraint(
            op.f(f"fk_transactions_{column}_user_id_wallets"), "transactions", type_="foreignkey"
        )
    for column in ("received_currency", "received_amount", "to_wallet_id", "from_wallet_id"):
        op.drop_column("transactions", column)
    op.drop_index("uq_wallets_user_id_spending", table_name="wallets")
    op.drop_index("uq_wallets_user_id_lower_name", table_name="wallets")
    op.drop_table("wallets")
