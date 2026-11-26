"""The views shown with a reply, kept in the chat log (ADR 0005).

Expand step of expand-then-contract (see deploy/README.md): one nullable column, nothing else.
The code running before never reads it.

``chat_log.views``: for a Nexus reply that came with views, a JSON list of
``{"kind", "params", "focus"}``: which views, opened with what, and which one was in focus.
Never figures: a card's figures are read fresh when it is drawn. NULL for every other line.
The column is on a user-owned table, so the data export, delete-my-data and row-level
security that already cover ``chat_log`` cover it.

Revision ID: 0085
Revises: 0084
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_log", sa.Column("views", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_log", "views")
