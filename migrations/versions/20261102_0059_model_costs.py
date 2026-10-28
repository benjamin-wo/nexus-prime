"""What the AI models cost: one row per day, user, feature and model.

Calls, tokens and US dollars, counted as they happen and added up in place; never what was
asked or answered. ``user_id`` is NULL for work done for no one in particular (a market-wide
job), and the unique index counts every NULL as the same user, so those rows add up too. Like
the user's other tables it has row-level security (see 0056): once a transaction names a user
(``app.user_id``) it shows and accepts only that user's rows. Rows go with the user.

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056 on purpose: a migration keeps meaning what it meant.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"


def upgrade() -> None:
    op.create_table(
        "model_costs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("feature", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("calls", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 6), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "calls >= 0 AND input_tokens >= 0 AND output_tokens >= 0 AND cost_usd >= 0",
            name=op.f("ck_model_costs_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_model_costs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_costs")),
    )
    op.create_index(
        "uq_model_costs_day_user_feature_model",
        "model_costs",
        [
            "day",
            sa.literal_column("coalesce(user_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "feature",
            "model",
        ],
        unique=True,
    )
    op.create_index("ix_model_costs_user_id", "model_costs", ["user_id"])
    # The app's role is granted new tables by 0056's default privileges.
    op.execute("ALTER TABLE model_costs ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON model_costs FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY} ON model_costs")
    op.drop_index("ix_model_costs_user_id", table_name="model_costs")
    op.drop_index("uq_model_costs_day_user_feature_model", table_name="model_costs")
    op.drop_table("model_costs")
