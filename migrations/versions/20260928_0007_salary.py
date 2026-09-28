"""Salary schedules.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "salary_schedules",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("day", sa.SmallInteger(), nullable=True),
        sa.Column("anchor", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(amount IS NULL) = (currency IS NULL)",
            name=op.f("ck_salary_schedules_amount_with_currency"),
        ),
        sa.CheckConstraint(
            "(rule = 'biweekly') = (anchor IS NOT NULL)",
            name=op.f("ck_salary_schedules_anchor_for_biweekly"),
        ),
        sa.CheckConstraint(
            "(rule = 'monthly_day') = (day IS NOT NULL)",
            name=op.f("ck_salary_schedules_day_for_monthly"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount > 0", name=op.f("ck_salary_schedules_amount_positive")
        ),
        sa.CheckConstraint(
            "day IS NULL OR day BETWEEN 1 AND 31", name=op.f("ck_salary_schedules_day_range")
        ),
        sa.CheckConstraint(
            "rule IN ('monthly_day', 'last_weekday', 'biweekly')",
            name=op.f("ck_salary_schedules_rule"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_salary_schedules_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_salary_schedules")),
    )


def downgrade() -> None:
    op.drop_table("salary_schedules")
