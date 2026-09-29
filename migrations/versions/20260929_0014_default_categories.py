"""The new default categories for existing users: "Food & Drink" becomes "Dining
Out", "Entertainment" becomes "Activities", and any default a user is missing is
added. Transactions keep their categories (only names change), and a user who
already has a category by the new name keeps both as they were.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULTS = (
    "Dining Out",
    "Groceries",
    "Transport",
    "Shopping",
    "Bills & Utilities",
    "Socialising",
    "Health",
    "Travel",
    "Activities",
    "Income",
    "Other",
)
RENAMES = (("Food & Drink", "Dining Out"), ("Entertainment", "Activities"))


_RENAME = sa.text(
    """
    UPDATE categories AS c SET name = :new
    WHERE lower(c.name) = lower(:old)
      AND NOT EXISTS (
        SELECT 1 FROM categories AS d
        WHERE d.user_id = c.user_id AND lower(d.name) = lower(:new)
      )
    """
)
_ADD_MISSING = sa.text(
    """
    INSERT INTO categories (id, user_id, name, active)
    SELECT gen_random_uuid(), u.id, :name, true FROM users AS u
    WHERE NOT EXISTS (
      SELECT 1 FROM categories AS c
      WHERE c.user_id = u.id AND lower(c.name) = lower(:name)
    )
    """
)


def upgrade() -> None:
    db = op.get_bind()
    for old, new in RENAMES:
        db.execute(_RENAME, {"old": old, "new": new})
    for name in DEFAULTS:
        db.execute(_ADD_MISSING, {"name": name})


def downgrade() -> None:
    # Names only; nothing to undo safely. Renamed or added categories stay.
    pass
