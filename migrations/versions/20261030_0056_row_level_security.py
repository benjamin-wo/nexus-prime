"""Row-level security: a second safety net under the per-user queries.

The app already filters every query by user. This makes Postgres refuse the rest: the app's
connections run as the ``nexus_app`` role (``SET ROLE``, see ``DB_APP_ROLE``), and each
user-owned table has a policy that, once the transaction names a user (``app.user_id``, set
with ``set_config(..., true)``), shows and accepts only that user's rows. With no user named
(background jobs, sign-in, admin tasks) every row is visible. The migration user owns the
tables, is not forced through the policies, and so still sees everything.

The table list and how each row is tied to its user are copied here on purpose: a migration
must keep meaning what it meant, whatever the app's registry (``application.user_data``,
``infra.db.user_data``) says later. A table added after this one needs its own policy;
``tests/integration/test_row_security.py`` fails until it has one.

Left without row security, and why:

- ``jobs``: queued work is written for other users by system code, and keyed by payload.
- ``trip_invites``: a signed-in person opens an invite someone else made, by its token hash.
- The LangGraph checkpoint tables: keyed by chat thread, with no user column.
- Shared data (market data, rates, caches, counters): not anyone's.

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-30
"""

# ruff: noqa: S608  (the SQL is built from this file's own constants, never from input)

from collections.abc import Sequence

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "nexus_app"

# The user named for this transaction; NULL when none is (unset, or reset to '' at the end of
# a transaction that set it).
NAMED = "NULLIF(current_setting('app.user_id', true), '')"
USER = f"{NAMED}::uuid"
NO_USER = f"{NAMED} IS NULL"

# Tables whose rows belong to a user by ``user_id`` alone.
BY_USER_ID: tuple[str, ...] = (
    "salary_schedules", "transactions", "splits", "settlements", "transaction_revisions",
    "receipts", "duplicate_dismissals", "categories", "category_rules", "wallets", "budgets",
    "bills", "bill_occurrences", "subscriptions", "statement_mappings", "statement_imports",
    "email_connections", "inbound_emails", "holdings", "trades", "dividends", "holding_drafts",
    "watchlist", "market_alerts", "plans", "department_runs", "trip_paid_by_others",
    "trip_links", "trip_shares", "memories", "chat_log", "capability_gaps",
    "notification_settings", "notifications", "web_sessions", "email_links",
    "transaction_sources", "budget_alerts", "trip_reminders",
)  # fmt: skip

# Tables tied by other columns (any of them matching is enough).
BY_COLUMNS: dict[str, tuple[str, ...]] = {
    "invites": ("created_by", "redeemed_by"),
}

# A trip and the rows under it. Besides their owner (``user_id``), the trip's members see
# them and may change them: a member's edit is the owner's trip being edited, so the rows
# keep the owner's id. The owner's money on the trip (``trip_paid_by_others``,
# ``trip_links``, ``trip_shares``) is above, owner only.
TRIP_ID_COLUMN: dict[str, str] = {
    "trips": "id",
    "trip_bookings": "trip_id",
    "trip_covers": "trip_id",
    "trip_changes": "trip_id",
}

POLICY = "nexus_user_rows"


def _own(*columns: str) -> str:
    return " OR ".join(f"{column} = {USER}" for column in columns)


def _policy(table: str, using: str, check: str | None = None) -> str:
    check = using if check is None else check
    return (
        f"CREATE POLICY {POLICY} ON {table} FOR ALL "
        f"USING ({NO_USER} OR {using}) WITH CHECK ({NO_USER} OR {check})"
    )


# Also see these rows, besides the table's own policy: read only.
TRIP_MATES: dict[str, str] = {
    "users": "nexus_shares_trip_with(id)",
    "trip_members": "nexus_on_trip(trip_id)",
    "trip_activity": "nexus_on_trip(trip_id)",
}
MATES_POLICY = "nexus_trip_mates"


def _policies() -> dict[str, str]:
    rules: dict[str, str] = {}
    for table in BY_USER_ID:
        rules[table] = _policy(table, _own("user_id"))
    for table, columns in BY_COLUMNS.items():
        rules[table] = _policy(table, _own(*columns))
    for table, trip_column in TRIP_ID_COLUMN.items():
        mine = _own("user_id")
        rules[table] = _policy(table, f"{mine} OR nexus_on_trip({trip_column})")
    # Users, memberships and a trip's activity are only ever changed by the people they
    # are about (that is the policy above) but also read by the people on the same trip: a
    # member opening the owner's trip reads the owner's name and zone, and who else is on it.
    rules["users"] = _policy("users", _own("id"))
    rules["trip_members"] = _policy("trip_members", _own("owner_id", "member_id"))
    rules["trip_activity"] = _policy("trip_activity", _own("owner_id", "actor_id"))
    return rules


# SECURITY DEFINER, owned by the migration user, so they read ``trip_members`` without going
# through its own policy (which would recurse). They name no user themselves: the setting is
# read inside, so a caller can't ask about anyone but the user the transaction names.
FUNCTIONS = (
    f"""
    CREATE FUNCTION nexus_on_trip(p_trip uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM public.trip_members m
            WHERE m.trip_id = p_trip AND m.member_id = {USER}
        )
    $$
    """,
    f"""
    CREATE FUNCTION nexus_shares_trip_with(p_user uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM public.trip_members a
            WHERE (a.owner_id = p_user AND a.member_id = {USER})
               OR (a.member_id = p_user AND a.owner_id = {USER})
               OR (a.member_id = {USER} AND EXISTS (
                    SELECT 1 FROM public.trip_members b
                    WHERE b.trip_id = a.trip_id AND b.member_id = p_user))
        )
    $$
    """,
)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;  -- made at the same moment
        END
        $$
        """
    )
    # So the app's connection (logged in as the migration user) may SET ROLE to it.
    op.execute(f"GRANT {ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}")
    # The schema's version is the migrations' to change.
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE}"
    )

    for function in FUNCTIONS:
        op.execute(function)
    for table, policy in _policies().items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(policy)
    for table, visible in TRIP_MATES.items():
        op.execute(f"CREATE POLICY {MATES_POLICY} ON {table} FOR SELECT USING ({visible})")


def downgrade() -> None:
    for table in TRIP_MATES:
        op.execute(f"DROP POLICY {MATES_POLICY} ON {table}")
    for table in _policies():
        op.execute(f"DROP POLICY {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION nexus_shares_trip_with(uuid)")
    op.execute("DROP FUNCTION nexus_on_trip(uuid)")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {ROLE}"
    )
    # Takes back what this database granted. The role itself belongs to the whole server, so
    # it stays when another database still uses it.
    op.execute(f"DROP OWNED BY {ROLE}")
    op.execute(
        f"""
        DO $$
        BEGIN
            DROP ROLE {ROLE};
        EXCEPTION WHEN dependent_objects_still_exist OR insufficient_privilege THEN NULL;
        END
        $$
        """
    )
