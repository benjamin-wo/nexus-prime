"""Fold the old bot's "Dining" into "Dining Out" and "General" into "Other".

For each user who has both, the old category's transactions and rules move to the
new one, and so does its budget unless the new one already has a budget. The old
category is archived, not deleted. This is a relabel, not an edit: no undo history
is written, so "undo" never reverses it.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MERGES = (("Dining", "Dining Out"), ("General", "Other"))

# Each step works on the pairs: a user's old and new category, when both exist
# and the new one is in use.
_STEPS = (
    sa.text(
        """
        WITH pairs AS (
          SELECT s.user_id, s.id AS source, t.id AS target
          FROM categories AS s JOIN categories AS t ON t.user_id = s.user_id
          WHERE lower(s.name) = lower(:old) AND lower(t.name) = lower(:new)
            AND t.active AND s.id <> t.id
        )
        UPDATE transactions AS x SET category_id = p.target
        FROM pairs AS p WHERE x.user_id = p.user_id AND x.category_id = p.source
        """
    ),
    sa.text(
        """
        WITH pairs AS (
          SELECT s.user_id, s.id AS source, t.id AS target
          FROM categories AS s JOIN categories AS t ON t.user_id = s.user_id
          WHERE lower(s.name) = lower(:old) AND lower(t.name) = lower(:new)
            AND t.active AND s.id <> t.id
        )
        UPDATE category_rules AS r SET category_id = p.target, updated_at = now()
        FROM pairs AS p WHERE r.user_id = p.user_id AND r.category_id = p.source
        """
    ),
    sa.text(
        """
        WITH pairs AS (
          SELECT s.user_id, s.id AS source, t.id AS target
          FROM categories AS s JOIN categories AS t ON t.user_id = s.user_id
          WHERE lower(s.name) = lower(:old) AND lower(t.name) = lower(:new)
            AND t.active AND s.id <> t.id
        )
        UPDATE budgets AS b SET category_id = p.target, updated_at = now()
        FROM pairs AS p
        WHERE b.user_id = p.user_id AND b.category_id = p.source
          AND NOT EXISTS (
            SELECT 1 FROM budgets AS o WHERE o.user_id = p.user_id AND o.category_id = p.target
          )
        """
    ),
    sa.text(
        """
        WITH pairs AS (
          SELECT s.user_id, s.id AS source, t.id AS target
          FROM categories AS s JOIN categories AS t ON t.user_id = s.user_id
          WHERE lower(s.name) = lower(:old) AND lower(t.name) = lower(:new)
            AND t.active AND s.id <> t.id
        )
        UPDATE categories AS c SET active = false
        FROM pairs AS p WHERE c.user_id = p.user_id AND c.id = p.source
        """
    ),
)


def upgrade() -> None:
    db = op.get_bind()
    for old, new in MERGES:
        for step in _STEPS:
            db.execute(step, {"old": old, "new": new})


def downgrade() -> None:
    # Which transactions were moved isn't recorded; the archived categories stay.
    pass
