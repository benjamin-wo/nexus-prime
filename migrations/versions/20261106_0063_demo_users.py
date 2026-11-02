"""Demo users: private, short-lived accounts for the public live demo.

``users.demo_expires_at`` is NULL for a real user and the moment a demo account ends for a
demo one (the clean-up job erases it then). A demo has a made-up Telegram id, always negative
(real ones are positive), and no chat, so nothing can ever be sent to Telegram for it. The
three counters are what a demo has used of its small allowances (chat messages, voice notes,
photos and PDFs); they are counted in one statement, so two requests can't both take the last
one.

When a demo is erased its model costs go with it (they are the user's rows), so they are first
added to ``demo_costs``, the same day, feature and model rows without the user. Together with
the live demos' own rows they make the day's demo spend, which a daily cap reads and the
owner's cost page shows. ``demo_starts`` counts the demos started each (UTC) day. Neither
table holds anything about a person.

Revision ID: 0063
Revises: 0062
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("demo_expires_at", sa.DateTime(timezone=True), nullable=True))
    for name in ("demo_messages", "demo_voice", "demo_photos"):
        op.add_column(
            "users",
            sa.Column(name, sa.Integer(), server_default=sa.text("0"), nullable=False),
        )
    op.create_check_constraint(
        op.f("ck_users_demo_telegram_id"),
        "users",
        "demo_expires_at IS NULL OR telegram_user_id < 0",
    )
    op.create_check_constraint(
        op.f("ck_users_demo_counts"),
        "users",
        "demo_messages >= 0 AND demo_voice >= 0 AND demo_photos >= 0",
    )
    op.create_index(
        "ix_users_demo_expires_at",
        "users",
        ["demo_expires_at"],
        postgresql_where=sa.text("demo_expires_at IS NOT NULL"),
    )

    op.create_table(
        "demo_costs",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("feature", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("calls", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("cached_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 6), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("day", "feature", "model", name=op.f("pk_demo_costs")),
    )
    op.create_table(
        "demo_starts",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("starts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_demo_starts")),
    )


def downgrade() -> None:
    op.drop_table("demo_starts")
    op.drop_table("demo_costs")
    op.drop_index("ix_users_demo_expires_at", table_name="users")
    op.drop_constraint(op.f("ck_users_demo_counts"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_demo_telegram_id"), "users", type_="check")
    for name in ("demo_photos", "demo_voice", "demo_messages", "demo_expires_at"):
        op.drop_column("users", name)
