"""Which card paid for an expense: card details on wallets, a Cash wallet, "paid with" on
expenses, and a usual card.

A wallet of kind card can say who issued it, which product and network it is and its last
four digits (never more); every user gets a Cash wallet (one that is already called Cash and
is kind other becomes it); an expense (direction out, never money in or a move) can name the
wallet it was paid with; and a user can name the wallet new expenses are paid with when none
is said. Deleting a wallet clears these references and nothing else, so the foreign keys
name the user too and null only the wallet column (``SET NULL (column)``, Postgres 15 and
later). No table is new, so row-level security (0056) is as it was.

Revision ID: 0065
Revises: 0064
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "kind IN ('spending', 'investment', 'savings', 'card', 'other')"
NEW_KINDS = "kind IN ('spending', 'investment', 'savings', 'card', 'cash', 'other')"
CARD_DETAILS = (
    "kind = 'card' OR (issuer IS NULL AND product IS NULL AND network IS NULL AND last4 IS NULL)"
)


def upgrade() -> None:
    for column in ("issuer", "product", "network", "last4"):
        op.add_column("wallets", sa.Column(column, sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_wallets_kind"), "wallets", type_="check")
    op.create_check_constraint(op.f("ck_wallets_kind"), "wallets", NEW_KINDS)
    op.create_check_constraint(
        op.f("ck_wallets_last4"), "wallets", "last4 IS NULL OR last4 ~ '^[0-9]{4}$'"
    )
    op.create_check_constraint(
        op.f("ck_wallets_network"),
        "wallets",
        "network IS NULL OR network IN ('visa', 'mastercard', 'amex', 'other')",
    )
    op.create_check_constraint(
        op.f("ck_wallets_issuer_length"), "wallets", "issuer IS NULL OR char_length(issuer) <= 40"
    )
    op.create_check_constraint(
        op.f("ck_wallets_product_length"),
        "wallets",
        "product IS NULL OR char_length(product) <= 60",
    )
    op.create_check_constraint(op.f("ck_wallets_card_details"), "wallets", CARD_DETAILS)
    op.create_index(
        "uq_wallets_user_id_cash",
        "wallets",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'cash'"),
    )
    # Everyone gets a Cash wallet. A wallet they already call Cash (any case) and left as
    # kind other is that wallet; failing that, one called "Cash wallet" (what a downgrade and
    # a new upgrade find). Wallet names are unique per user, so if another kind of wallet
    # already has the name, the new one is called "Cash wallet", or "Cash account".
    op.execute("UPDATE wallets SET kind = 'cash' WHERE lower(name) = 'cash' AND kind = 'other'")
    op.execute(
        "UPDATE wallets w SET kind = 'cash' WHERE lower(w.name) = 'cash wallet' "
        "AND w.kind = 'other' AND NOT EXISTS "
        "(SELECT 1 FROM wallets c WHERE c.user_id = w.user_id AND c.kind = 'cash')"
    )
    op.execute(
        "INSERT INTO wallets (id, user_id, name, kind) "
        "SELECT gen_random_uuid(), u.id, "
        "CASE WHEN NOT EXISTS (SELECT 1 FROM wallets w WHERE w.user_id = u.id "
        "AND lower(w.name) = 'cash') THEN 'Cash' "
        "WHEN NOT EXISTS (SELECT 1 FROM wallets w WHERE w.user_id = u.id "
        "AND lower(w.name) = 'cash wallet') THEN 'Cash wallet' ELSE 'Cash account' END, 'cash' "
        "FROM users u WHERE NOT EXISTS "
        "(SELECT 1 FROM wallets w WHERE w.user_id = u.id AND w.kind = 'cash')"
    )

    op.add_column("transactions", sa.Column("paid_with_wallet_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_transactions_paid_with_wallet_id_user_id_wallets"),
        "transactions",
        "wallets",
        ["paid_with_wallet_id", "user_id"],
        ["id", "user_id"],
        ondelete="SET NULL (paid_with_wallet_id)",
    )
    op.create_check_constraint(
        op.f("ck_transactions_paid_with_out"),
        "transactions",
        "paid_with_wallet_id IS NULL OR direction = 'out'",
    )
    op.create_index(
        "ix_transactions_user_id_paid_with_wallet_id_occurred_at",
        "transactions",
        ["user_id", "paid_with_wallet_id", "occurred_at"],
        unique=False,
    )

    op.add_column("users", sa.Column("usual_card_wallet_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_usual_card_wallet_id_id_wallets"),
        "users",
        "wallets",
        ["usual_card_wallet_id", "id"],
        ["id", "user_id"],
        ondelete="SET NULL (usual_card_wallet_id)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_users_usual_card_wallet_id_id_wallets"), "users", type_="foreignkey"
    )
    op.drop_column("users", "usual_card_wallet_id")

    op.drop_index("ix_transactions_user_id_paid_with_wallet_id_occurred_at", "transactions")
    op.drop_constraint(op.f("ck_transactions_paid_with_out"), "transactions", type_="check")
    op.drop_constraint(
        op.f("fk_transactions_paid_with_wallet_id_user_id_wallets"),
        "transactions",
        type_="foreignkey",
    )
    op.drop_column("transactions", "paid_with_wallet_id")

    # A Cash wallet becomes a plain "other" one, with whatever moves it has.
    op.drop_index("uq_wallets_user_id_cash", table_name="wallets")
    op.execute("UPDATE wallets SET kind = 'other' WHERE kind = 'cash'")
    for name in ("card_details", "product_length", "issuer_length", "network", "last4"):
        op.drop_constraint(op.f(f"ck_wallets_{name}"), "wallets", type_="check")
    op.drop_constraint(op.f("ck_wallets_kind"), "wallets", type_="check")
    op.create_check_constraint(op.f("ck_wallets_kind"), "wallets", OLD_KINDS)
    for column in ("last4", "network", "product", "issuer"):
        op.drop_column("wallets", column)
