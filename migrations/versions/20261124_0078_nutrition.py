"""Food logging: the shared food database, meals and their items.

Expand step of expand-then-contract (see deploy/README.md): three new tables that the code
running before never touches.

- ``foods``: shared by every user (USDA FoodData Central now, SG FoodID later), so no user_id
  and no row-level security, like ``exercises`` (0074). Loaded at startup, not here.
- ``meal_entries``, ``meal_items``: one user's meals; each item keeps a snapshot of the
  nutrients computed when it was logged, so updating ``foods`` never rewrites history.

The user tables get row-level security, the policy 0056 gave the others (copied here on
purpose: a migration keeps meaning what it meant).

Revision ID: 0078
Revises: 0076
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0078"
# The safety layer's 0077 is built on a sibling branch; the chain is fixed when they merge.
down_revision: str | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from 0056.
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"
POLICY = "nexus_user_rows"

TABLES = ("meal_entries", "meal_items")


def upgrade() -> None:
    op.create_table(
        "foods",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("kcal_100g", sa.Numeric(7, 2), nullable=False),
        sa.Column("protein_g_100g", sa.Numeric(6, 2), nullable=False),
        sa.Column("carbs_g_100g", sa.Numeric(6, 2), nullable=False),
        sa.Column("fat_g_100g", sa.Numeric(6, 2), nullable=False),
        sa.Column("fibre_g_100g", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "portions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('usda', 'sgfoodid', 'custom')", name=op.f("ck_foods_source")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(portions) = 'array'", name=op.f("ck_foods_portions_array")
        ),
        sa.CheckConstraint(
            "kcal_100g >= 0 AND protein_g_100g >= 0 AND carbs_g_100g >= 0 AND fat_g_100g >= 0 "
            "AND (fibre_g_100g IS NULL OR fibre_g_100g >= 0)",
            name=op.f("ck_foods_not_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_foods")),
    )

    op.create_table(
        "meal_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("meal", sa.Text(), nullable=False),
        sa.Column("eaten_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "meal IN ('breakfast', 'lunch', 'dinner', 'snack')", name=op.f("ck_meal_entries_meal")
        ),
        sa.CheckConstraint(
            "source IN ('chat', 'voice', 'manual', 'photo')", name=op.f("ck_meal_entries_source")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_meal_entries_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal_entries")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_meal_entries_id_user_id")),
    )
    op.create_index("ix_meal_entries_user_id_eaten_at", "meal_entries", ["user_id", "eaten_at"])

    op.create_table(
        "meal_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("food_id", sa.Text(), nullable=False),
        sa.Column("grams", sa.Numeric(8, 2), nullable=False),
        sa.Column("portion_label", sa.Text(), nullable=False),
        sa.Column("estimate_kind", sa.Text(), nullable=False),
        sa.Column("cooking", sa.Text(), nullable=True),
        sa.Column(
            "extra_uncertainty", sa.Numeric(4, 2), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("kcal", sa.Numeric(9, 3), nullable=False),
        sa.Column("protein_g", sa.Numeric(9, 3), nullable=False),
        sa.Column("carbs_g", sa.Numeric(9, 3), nullable=False),
        sa.Column("fat_g", sa.Numeric(9, 3), nullable=False),
        sa.Column("fibre_g", sa.Numeric(9, 3), nullable=True),
        sa.CheckConstraint(
            "estimate_kind IN ('weighed', 'portion', 'estimated')",
            name=op.f("ck_meal_items_estimate_kind"),
        ),
        sa.CheckConstraint(
            "cooking IS NULL OR cooking IN ('fried', 'stir-fried', 'curry/gravy')",
            name=op.f("ck_meal_items_cooking"),
        ),
        sa.CheckConstraint("grams > 0", name=op.f("ck_meal_items_grams_positive")),
        sa.CheckConstraint(
            "extra_uncertainty >= 0", name=op.f("ck_meal_items_extra_uncertainty_not_negative")
        ),
        sa.CheckConstraint(
            "kcal >= 0 AND protein_g >= 0 AND carbs_g >= 0 AND fat_g >= 0 "
            "AND (fibre_g IS NULL OR fibre_g >= 0)",
            name=op.f("ck_meal_items_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "user_id"],
            ["meal_entries.id", "meal_entries.user_id"],
            name=op.f("fk_meal_items_entry_id_user_id_meal_entries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["food_id"], ["foods.id"], name=op.f("fk_meal_items_food_id_foods")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_meal_items_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal_items")),
    )
    op.create_index("ix_meal_items_entry_id_position", "meal_items", ["entry_id", "position"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} FOR ALL "
            f"USING ({NO_USER} OR user_id = {USER}) WITH CHECK ({NO_USER} OR user_id = {USER})"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY {POLICY} ON {table}")
    op.drop_table("meal_items")
    op.drop_table("meal_entries")
    op.drop_table("foods")
