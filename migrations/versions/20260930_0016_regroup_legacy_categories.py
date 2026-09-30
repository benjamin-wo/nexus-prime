"""Regroup the old bot's categories into the defaults, and add "Subscriptions &
Software" as a twelfth default.

The old bot named categories as it went ("Software", "Digital Services", "Others",
"Automotive"...). Each such category (one with transactions imported from the old
bot, that isn't a default or "Personal Care") is folded into the default its name
points to, by keyword, or into Other when none fits: its transactions and rules
move over, its budget too unless the default already has one, and it's archived,
not deleted. Categories users added themselves are left alone. As with 0015, no
undo history is written.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-30
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_DEFAULT = "Subscriptions & Software"
DEFAULTS = (
    "Dining Out",
    "Groceries",
    "Transport",
    "Shopping",
    "Bills & Utilities",
    "Socialising",
    "Health",
    "Travel",
    "Activities",
    NEW_DEFAULT,
    "Income",
    "Other",
)
KEEP = ("personal care",)  # the user keeps this one as their own

# First match wins, so the specific come before the broad ("Digital bills" is
# software, "Bills" is bills). Each entry is a regex fragment, matched anywhere in
# the casefolded name; \b marks the words that must stand alone.
KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        NEW_DEFAULT,
        (
            "software",
            "digital",
            "subscription",
            "in-app",
            r"\bapps?\b",
            "saas",
            "cloud",
            "streaming",
        ),
    ),
    ("Groceries", ("grocer", "supermarket")),
    (
        "Dining Out",
        (
            "dining",
            "food",
            "restaurant",
            "cafe",
            "coffee",
            "meal",
            "lunch",
            "dinner",
            "breakfast",
            "hawker",
            "takeaway",
        ),
    ),
    (
        "Transport",
        (
            "transport",
            "taxi",
            "grab",
            r"\bcar\b",
            "automotive",
            "fuel",
            "petrol",
            "parking",
            "commute",
            r"\bmrt\b",
            r"\bbus(es)?\b",
            r"\brides?\b",
        ),
    ),
    ("Travel", ("travel", "flight", "hotel", "holiday", "vacation", r"\btrips?\b")),
    (
        "Health",
        (
            "health",
            "medical",
            "pharmacy",
            "clinic",
            "dental",
            "doctor",
            "fitness",
            "gym",
            "wellness",
        ),
    ),
    (
        "Bills & Utilities",
        (
            "bill",
            "utilit",
            "phone",
            "mobile",
            "internet",
            "telco",
            r"\brent\b",
            "insurance",
            "electric",
            "water",
        ),
    ),
    ("Socialising", ("social", "friends", "party", "drinks", r"\bbar\b", "gathering")),
    (
        "Activities",
        (
            "entertainment",
            "activit",
            "hobb",
            "game",
            "movie",
            "cinema",
            "sport",
            "leisure",
            "concert",
            r"\bevents?\b",
        ),
    ),
    (
        "Shopping",
        (
            "shop",
            "clothing",
            "apparel",
            "retail",
            "electronic",
            "gadget",
            "household",
            "furniture",
            "gift",
        ),
    ),
    ("Income", ("income", "salary", "payroll")),
)


def target_for(name: str) -> str:
    lowered = name.casefold()
    for default, words in KEYWORDS:
        if any(re.search(word, lowered) for word in words):
            return default
    return "Other"


_ADD_DEFAULT = sa.text(
    """
    INSERT INTO categories (id, user_id, name, active)
    SELECT gen_random_uuid(), u.id, :name, true FROM users AS u
    WHERE NOT EXISTS (
      SELECT 1 FROM categories AS c WHERE c.user_id = u.id AND lower(c.name) = lower(:name)
    )
    """
)
# Active categories with transactions imported from the old bot.
_LEGACY = sa.text(
    """
    SELECT c.id, c.user_id, c.name FROM categories AS c
    WHERE c.active AND EXISTS (
      SELECT 1 FROM transactions AS t
      WHERE t.user_id = c.user_id AND t.category_id = c.id AND t.source = 'import'
    )
    """
)
_DEFAULT_ID = sa.text(
    "SELECT id FROM categories WHERE user_id = :u AND lower(name) = lower(:n) AND active"
)
_MERGE = (
    sa.text("UPDATE transactions SET category_id = :t WHERE user_id = :u AND category_id = :s"),
    sa.text(
        "UPDATE category_rules SET category_id = :t, updated_at = now() "
        "WHERE user_id = :u AND category_id = :s"
    ),
    sa.text(
        "UPDATE budgets SET category_id = :t, updated_at = now() "
        "WHERE user_id = :u AND category_id = :s AND NOT EXISTS ("
        "SELECT 1 FROM budgets AS o WHERE o.user_id = :u AND o.category_id = :t)"
    ),
    sa.text("UPDATE categories SET active = false WHERE user_id = :u AND id = :s"),
)


def upgrade() -> None:
    db = op.get_bind()
    db.execute(_ADD_DEFAULT, {"name": NEW_DEFAULT})
    defaults = {d.casefold() for d in DEFAULTS}
    for source_id, user_id, name in db.execute(_LEGACY).all():
        if name.casefold() in defaults or name.casefold() in KEEP:
            continue
        target = db.execute(_DEFAULT_ID, {"u": user_id, "n": target_for(name)}).scalar()
        if target is None:  # the user archived that default: leave this one be
            continue
        for step in _MERGE:
            db.execute(step, {"u": user_id, "s": source_id, "t": target})


def downgrade() -> None:
    # Which transactions were moved isn't recorded; the archived categories stay.
    pass
