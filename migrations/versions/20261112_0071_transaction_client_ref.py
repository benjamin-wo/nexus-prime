"""A client key on transactions, so an entry saved offline and sent twice is recorded once.

The web app lets someone log an expense with no connection: it keeps the entry on the phone
with a key it made up (a UUID) and sends it, with that key in an ``Idempotency-Key`` header,
whenever it can. The reply may be lost on the way back, so the same entry can arrive more than
once. ``transactions.client_ref`` holds the key; the partial unique index allows one
transaction per user and key (rows without a key, which is every row made any other way,
are not in it). The key says nothing about the entry: a random string. Row-level security
(0056) already covers ``transactions``, and the app's role already has its privileges: a new
column needs neither.

Revision ID: 0071
Revises: 0070
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_transactions_user_id_client_ref"


def upgrade() -> None:
    op.add_column("transactions", sa.Column("client_ref", sa.Text(), nullable=True))
    op.create_index(
        INDEX,
        "transactions",
        ["user_id", "client_ref"],
        unique=True,
        postgresql_where=sa.text("client_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, "transactions", postgresql_where=sa.text("client_ref IS NOT NULL"))
    op.drop_column("transactions", "client_ref")
