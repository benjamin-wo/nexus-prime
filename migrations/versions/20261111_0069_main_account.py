"""The default wallet is called "Main account", not "Spending".

New users get the new name from the app. This renames the wallet of everyone who already has
the old one: the user's one wallet of kind ``spending`` (the default wallet is found by that
kind, never by its name) whose name is exactly ``Spending``. A user who renamed it keeps
their name. Wallet names are unique per user without regard to case
(``uq_wallets_user_id_lower_name``), so a user who already has another wallet called
"Main account" keeps ``Spending`` rather than hit the index.

The downgrade is the same in reverse: ``Main account`` on the ``spending`` wallet goes back
to ``Spending`` unless the user has another wallet by that name.

Nothing else changes: no table or column is new, so policies and grants are as they were.

Revision ID: 0069
Revises: 0068
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename(old: str, new: str) -> None:
    # The migration user is not forced through row-level security (0056), so it sees every
    # user's rows. ``old`` and ``new`` are fixed words above, never user input.
    op.execute(
        f"UPDATE wallets w SET name = '{new}' "  # noqa: S608
        f"WHERE w.kind = 'spending' AND w.name = '{old}' "
        "AND NOT EXISTS (SELECT 1 FROM wallets o WHERE o.user_id = w.user_id "
        f"AND o.id <> w.id AND lower(o.name) = lower('{new}'))"
    )


def upgrade() -> None:
    _rename("Spending", "Main account")


def downgrade() -> None:
    _rename("Main account", "Spending")
