"""Connected mailboxes, the emails swept from them, and one-time connect links.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("token", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("synced_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider IN ('gmail')", name=op.f("ck_email_connections_provider")),
        sa.CheckConstraint(
            "status IN ('active', 'broken')", name=op.f("ck_email_connections_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_email_connections_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_connections")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_email_connections_id_user_id")),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "address",
            name=op.f("uq_email_connections_user_id_provider_address"),
        ),
    )
    op.create_table(
        "email_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_email_links_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_links_token_hash")),
    )
    op.create_table(
        "inbound_emails",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'logged', 'skipped', 'not_receipt', 'no_amount', "
            "'duplicate', 'failed')",
            name=op.f("ck_inbound_emails_status"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "user_id"],
            ["email_connections.id", "email_connections.user_id"],
            name=op.f("fk_inbound_emails_connection_id_user_id_email_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name=op.f("fk_inbound_emails_transaction_id_user_id_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_inbound_emails_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_emails")),
        sa.UniqueConstraint(
            "connection_id",
            "provider_message_id",
            name=op.f("uq_inbound_emails_connection_id_provider_message_id"),
        ),
    )
    op.create_index(
        "ix_inbound_emails_user_id_received_at",
        "inbound_emails",
        ["user_id", "received_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_emails_user_id_received_at", table_name="inbound_emails")
    op.drop_table("inbound_emails")
    op.drop_table("email_links")
    op.drop_table("email_connections")
