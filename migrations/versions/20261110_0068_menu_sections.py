"""Whether Invest and Travel show in the web app's menu: ``users.show_invest`` and
``users.show_travel``.

Both are nullable on purpose. NULL means "not decided": the tab is hidden, and it turns on
by itself the first time the user uses the feature in chat. TRUE means shown. FALSE means the
user switched it off: hidden, and never turned on by itself again. Chat and the API work the
same whatever they say; only the menu changes.

Everyone who already uses a section keeps seeing it: a user with a holding, a watchlist
stock, a trade or a trade plan starts with ``show_invest`` on, and a user with a trip (their
own, or one they were added to), a booking or a trip research run starts with ``show_travel``
on. Everyone else starts undecided. No table is new and the columns sit on ``users`` (no
row-level security policy there, see 0056), so policies and grants are as they were.

Revision ID: 0068
Revises: 0067
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("show_invest", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("show_travel", sa.Boolean(), nullable=True))
    # The migration user is not forced through row-level security (0056), so it sees every
    # user's rows.
    op.execute(
        "UPDATE users u SET show_invest = true WHERE "
        "EXISTS (SELECT 1 FROM holdings x WHERE x.user_id = u.id) "
        "OR EXISTS (SELECT 1 FROM watchlist x WHERE x.user_id = u.id) "
        "OR EXISTS (SELECT 1 FROM trades x WHERE x.user_id = u.id) "
        "OR EXISTS (SELECT 1 FROM plans x WHERE x.user_id = u.id)"
    )
    op.execute(
        "UPDATE users u SET show_travel = true WHERE "
        "EXISTS (SELECT 1 FROM trips x WHERE x.user_id = u.id) "
        "OR EXISTS (SELECT 1 FROM trip_members x WHERE x.member_id = u.id) "
        "OR EXISTS (SELECT 1 FROM trip_bookings x WHERE x.user_id = u.id) "
        "OR EXISTS (SELECT 1 FROM department_runs x "
        "WHERE x.user_id = u.id AND x.department = 'travel')"
    )


def downgrade() -> None:
    op.drop_column("users", "show_travel")
    op.drop_column("users", "show_invest")
