"""Accounts stop depending on Telegram: ``user_identities`` and a nullable Telegram id.

NOTE FOR WHOEVER MERGES SECOND: another branch has a revision 0072. Whichever of 0072 and
0073 lands second must set its ``down_revision`` to the other, so there stays one head.

This is the expand step of expand-then-contract (see deploy/README.md): everything here works
with the code that runs before it, which a failed deploy rolls back to while the database
stays. That code still inserts users with a Telegram id and reads ``users.telegram_user_id``,
and it never touches the new table or column, so nothing it does breaks:

- ``user_identities``: one row per way a person signs in (``telegram``, ``email`` or
  ``apple``), unique by ``(provider, subject)``. ``subject`` is the provider's own id for them
  (the Telegram user id as text, the Apple ``sub``, the lower-cased email). ``email`` is the
  address the provider vouched for, if any, always stored lower-case (a CHECK), and not
  unique here (two providers may vouch for the same address). Deleted with the user
  (``ON DELETE CASCADE``); row-level security is 0056's pattern for a
  table tied by ``user_id``. The app's role gets its privileges from 0056's default ones.
- Backfill: every user with a real (positive) Telegram id gets a ``telegram`` identity.
  Demo accounts have made-up negative ids and get none.
- ``users.telegram_user_id`` may now be null (the unique index stays; nulls don't collide),
  and ``users.email`` is new, nullable, lower-case (a CHECK) and unique where set. Nothing
  reads or fills it yet.

Users created by the previous code while this is live get no identity row; Telegram lookups
still read ``users.telegram_user_id``, so they work; the backfill statement below is safe to
run again to add their identity.

Revision ID: 0073
Revises: 0071
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "nexus_user_rows"
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"

BACKFILL = """
    INSERT INTO user_identities (user_id, provider, subject)
    SELECT id, 'telegram', telegram_user_id::text FROM users
    WHERE telegram_user_id > 0
    ON CONFLICT (provider, subject) DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column(
            "id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "provider IN ('telegram', 'email', 'apple')",
            name=op.f("ck_user_identities_provider"),
        ),
        sa.CheckConstraint(
            "email IS NULL OR email = lower(email)", name=op.f("ck_user_identities_email_lower")
        ),
        sa.UniqueConstraint(
            "provider", "subject", name=op.f("uq_user_identities_provider_subject")
        ),
    )  # fmt: skip
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])

    # Row-level security: 0056's pattern for a table tied by user_id.
    op.execute("ALTER TABLE user_identities ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON user_identities FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )

    op.execute(BACKFILL)

    op.alter_column("users", "telegram_user_id", nullable=True)
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_email_lower"), "users", "email IS NULL OR email = lower(email)"
    )
    op.create_index(
        "uq_users_email",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_email", "users", postgresql_where=sa.text("email IS NOT NULL"))
    op.drop_constraint(op.f("ck_users_email_lower"), "users", type_="check")
    op.drop_column("users", "email")
    missing: int = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM users WHERE telegram_user_id IS NULL"))
        .scalar_one()
    )
    if missing:
        raise RuntimeError(
            f"cannot downgrade: {missing} user(s) have no Telegram id (they signed up another "
            "way). Give them one or delete them first."
        )
    op.alter_column("users", "telegram_user_id", nullable=False)
    op.drop_table("user_identities")  # takes its policy and index with it
