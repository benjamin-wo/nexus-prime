"""Shared trips: people who can edit a trip's plan, the links that add them, what they
changed, guest accounts, and a name to show for each user.

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_role"), "users", "role IN ('owner', 'member', 'guest')"
    )

    op.create_table(
        "trip_invites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "may_create_guest", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_by", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["trip_id", "owner_id"],
            ["trips.id", "trips.user_id"],
            name=op.f("fk_trip_invites_trip_id_owner_id_trips"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by"], ["users.id"], name=op.f("fk_trip_invites_redeemed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_trip_invites_token_hash")),
    )
    op.create_index(op.f("ix_trip_invites_trip_id"), "trip_invites", ["trip_id"], unique=False)

    op.create_table(
        "trip_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("added_by_invite", sa.UUID(), nullable=True),
        sa.CheckConstraint("member_id <> owner_id", name=op.f("ck_trip_members_member_not_owner")),
        sa.ForeignKeyConstraint(
            ["trip_id", "owner_id"],
            ["trips.id", "trips.user_id"],
            name=op.f("fk_trip_members_trip_id_owner_id_trips"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["users.id"], name=op.f("fk_trip_members_member_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["added_by_invite"],
            ["trip_invites.id"],
            name=op.f("fk_trip_members_added_by_invite_trip_invites"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_members")),
        sa.UniqueConstraint("trip_id", "member_id", name=op.f("uq_trip_members_trip_id_member_id")),
    )
    op.create_index(op.f("ix_trip_members_member_id"), "trip_members", ["member_id"], unique=False)

    op.create_table(
        "trip_activity",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(summary) BETWEEN 1 AND 200", name=op.f("ck_trip_activity_summary_length")
        ),
        sa.ForeignKeyConstraint(
            ["trip_id", "owner_id"],
            ["trips.id", "trips.user_id"],
            name=op.f("fk_trip_activity_trip_id_owner_id_trips"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_trip_activity_actor_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_activity")),
    )
    op.create_index(
        op.f("ix_trip_activity_trip_id_at"),
        "trip_activity",
        ["trip_id", sa.literal_column("at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_trip_activity_trip_id_at"), table_name="trip_activity")
    op.drop_table("trip_activity")
    op.drop_index(op.f("ix_trip_members_member_id"), table_name="trip_members")
    op.drop_table("trip_members")
    op.drop_index(op.f("ix_trip_invites_trip_id"), table_name="trip_invites")
    op.drop_table("trip_invites")

    # A guest account can't exist in the old schema. Keep the row but give it no way in:
    # an ordinary member without web access, and no sessions.
    op.execute(
        "DELETE FROM web_sessions WHERE user_id IN (SELECT id FROM users WHERE role = 'guest')"
    )
    op.execute(
        "UPDATE users SET role = 'member', web_access_granted_at = NULL WHERE role = 'guest'"
    )
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_role"), "users", "role IN ('owner', 'member')")
    op.drop_column("users", "display_name")
