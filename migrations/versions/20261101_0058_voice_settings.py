"""How Nexus talks: one row per user who changed it.

A preset (``default``, ``chill``, ``direct``, ``hype``, ``cheeky``), three dials (emoji,
length, humour) and an optional note in the user's own words. No row means the default voice.
Like the user's other tables it has row-level security (see 0056): once a transaction names a
user (``app.user_id``) it shows and accepts only that user's row.

Revision ID: 0058
Revises: 0057
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056 on purpose: a migration keeps meaning what it meant.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"


def upgrade() -> None:
    op.create_table(
        "voice_settings",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("emoji", sa.Text(), nullable=False),
        sa.Column("length", sa.Text(), nullable=False),
        sa.Column("humour", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "preset IN ('default', 'chill', 'direct', 'hype', 'cheeky')",
            name=op.f("ck_voice_settings_preset"),
        ),
        sa.CheckConstraint(
            "emoji IN ('none', 'some', 'lots')", name=op.f("ck_voice_settings_emoji")
        ),
        sa.CheckConstraint(
            "length IN ('short', 'normal', 'detailed')", name=op.f("ck_voice_settings_length")
        ),
        sa.CheckConstraint(
            "humour IN ('off', 'light', 'playful')", name=op.f("ck_voice_settings_humour")
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) BETWEEN 1 AND 200",
            name=op.f("ck_voice_settings_note_length"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_voice_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_voice_settings")),
    )
    # The app's role is granted new tables by 0056's default privileges.
    op.execute("ALTER TABLE voice_settings ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON voice_settings FOR ALL "
        f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY} ON voice_settings")
    op.drop_table("voice_settings")
