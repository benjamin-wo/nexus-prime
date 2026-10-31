"""Who pays the salary.

An optional name on the pay schedule (the employer, say). It is put on the salary rows the
payday check-in and "salary 5000" log, so the ledger shows a name instead of "No merchant".
The column rides with ``salary_schedules``, so row-level security, export and deletion
already cover it.

Revision ID: 0062
Revises: 0061
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("salary_schedules", sa.Column("payer", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_salary_schedules_payer_length"),
        "salary_schedules",
        "payer IS NULL OR length(payer) BETWEEN 1 AND 80",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_salary_schedules_payer_length"), "salary_schedules", type_="check")
    op.drop_column("salary_schedules", "payer")
