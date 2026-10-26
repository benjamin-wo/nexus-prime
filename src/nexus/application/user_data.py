"""What "Export all my data" and "Delete my data" cover, table by table.

Every table in the schema is in exactly one of three places:

- ``AREAS``: the user's own rows, exported as one JSON file per area and deleted.
- ``NOT_EXPORTED``: the user's own rows that are deleted but not exported, with the reason.
- ``SHARED``: not the user's data (market data, rates, caches, counters); kept, with the
  reason.

A new table must be added to one of them: ``tests/unit/test_user_data_coverage.py`` fails
otherwise. How a row is matched to its user, and the order rows are deleted in, are in
``nexus.infra.db.user_data``.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Area:
    file: str  # the JSON file in the export
    about: str  # one line for README.txt
    tables: tuple[str, ...]


AREAS: tuple[Area, ...] = (
    Area("profile.json", "Your account: time zones, currency, display name, pay schedule.",
         ("users", "salary_schedules")),
    Area("transactions.json",
         "Every transaction (deleted ones too), its splits and settlements, its history, "
         "receipt details and pairs you said are not duplicates.",
         ("transactions", "splits", "settlements", "transaction_revisions", "receipts",
          "duplicate_dismissals")),
    Area("categories.json", "Your categories.", ("categories",)),
    Area("category_rules.json", "Your category rules.", ("category_rules",)),
    Area("split_habits.json", "Who you usually split bills with, and your share.",
         ("split_habits",)),
    Area("wallets.json", "Your wallets.", ("wallets",)),
    Area("budgets.json", "Your monthly budgets.", ("budgets",)),
    Area("bills.json", "Your bills and their due dates.", ("bills", "bill_occurrences")),
    Area("subscriptions.json", "Recurring charges Nexus noticed or you track.",
         ("subscriptions",)),
    Area("imports.json", "Saved statement layouts and the statements you imported.",
         ("statement_mappings", "statement_imports")),
    Area("email.json",
         "Connected mailboxes (address and status, never the access grant) and the emails "
         "Nexus looked at (sender, subject and outcome, never the body).",
         ("email_connections", "inbound_emails")),
    Area("holdings.json", "Your holdings, trades, dividends and unsaved broker screenshots.",
         ("holdings", "trades", "dividends", "holding_drafts")),
    Area("watchlist.json", "Stocks you follow and the stock alerts Nexus kept.",
         ("watchlist", "market_alerts")),
    Area("trade_plans.json", "Your trade plans.", ("plans",)),
    Area("research.json", "Research runs (stocks and trips) and what they found.",
         ("department_runs",)),
    Area("trips.json",
         "Your trips, each with its bookings and plans, stops, to-dos, packing, cover and "
         "documents, costs others paid and how they were split, share link settings, "
         "changes made from chat and activity; and the trips you are a member of.",
         ("trips", "trip_bookings", "trip_covers", "trip_paid_by_others", "trip_links",
          "trip_shares", "trip_changes", "trip_members", "trip_activity")),
    Area("voice.json", "How you asked Nexus to talk: tone, emoji, length, humour and your note.",
         ("voice_settings",)),
    Area("memories.json", "What Nexus remembers about you.", ("memories",)),
    Area("chat.json", "Your chat history and what you asked for that Nexus could not do.",
         ("chat_log", "capability_gaps")),
    Area("notifications.json", "Your notification settings and the messages Nexus sent.",
         ("notification_settings", "notifications")),
)  # fmt: skip

NOT_EXPORTED: dict[str, str] = {
    "web_sessions": "sign-in sessions: secrets, and nothing you wrote",
    "email_links": "one-time links for connecting a mailbox: secrets",
    "invites": "single-use sign-in invites (hashes): secrets, and no content",
    "trip_invites": "single-use trip invites (hashes): secrets, and no content",
    "jobs": "queued background work: copies of data exported elsewhere, and short-lived",
    "transaction_sources": "internal keys that stop an imported item being imported twice",
    "budget_alerts": "internal markers that an alert was already sent",
    "trip_reminders": "internal markers that a reminder was already sent",
}

SHARED: dict[str, str] = {
    "market_bars": "daily prices, shared by every user: market data",
    "market_quotes": "latest stock quotes, shared by every user: market data",
    "market_symbols": "when each stock's prices were fetched: market data",
    "market_news": "company news, shared by every user: someone else's text",
    "market_earnings": "earnings dates, shared by every user: market data",
    "news_fetches": "when each stock's news was fetched: market data",
    "fx_rates": "reference exchange rates, shared by every user",
    "destination_photos": "Wikimedia Commons photos of places, shared by every trip there",
    "web_cache": "public web search answers, shared by all users",
    "web_credits": "search credits used each month by product, not by user",
    "inbound_events": "ids of Telegram updates already handled; no user, no content",
    "ops_events": "timings and error types with a keyed hash for the user, never what anyone "
    "said or spent; kept 30 days",
}


def exported_tables() -> tuple[str, ...]:
    return tuple(table for area in AREAS for table in area.tables)


def owned_tables() -> frozenset[str]:
    """Every table whose rows are the user's: deleted with them."""
    return frozenset(exported_tables()) | frozenset(NOT_EXPORTED)
