"""A table can't be added to the schema without deciding what "Export all my data" and
"Delete my data" do with it.

Every table must be one of: exported and deleted (``AREAS``), deleted but not exported
(``NOT_EXPORTED``), or not the user's at all (``SHARED``), each of the last two with a reason.
A table is the user's if it has a ``user_id``, any foreign key to ``users``, or a foreign key
chain to another table that is. If this fails after you added a table, add it to
``nexus.application.user_data`` (and, if it is the user's, to ``ERASE_ORDER`` in
``nexus.infra.db.user_data``, children before the tables they reference).
"""

from sqlalchemy import Table

from nexus.application.user_data import (
    AREAS,
    NOT_EXPORTED,
    SHARED,
    exported_tables,
    owned_tables,
)
from nexus.infra.db.tables import CHECKPOINT_TABLES, metadata
from nexus.infra.db.user_data import (
    CHECKPOINT_THREAD_TABLES,
    ERASE_ORDER,
    exported_columns,
    is_secret,
    tie_columns,
)

TABLES = metadata.tables


def user_linked() -> dict[str, str]:
    """Tables that hold a user's data, with why: found from the schema alone."""
    linked: dict[str, str] = {}
    for table in TABLES.values():
        if table.name == "users":
            continue
        if "user_id" in table.c:
            linked[table.name] = "has a user_id column"
        for fk in table.foreign_keys:
            if fk.column.table.name == "users":
                linked.setdefault(table.name, f"{fk.parent.name} references users")
    changed = True
    while changed:  # a foreign key chain to a table that is linked, such as trips
        changed = False
        for table in TABLES.values():
            for fk in table.foreign_keys:
                parent = fk.column.table.name
                if table.name not in linked and parent in linked:
                    linked[table.name] = f"{fk.parent.name} references {parent}"
                    changed = True
    return linked


def test_every_table_is_exported_and_deleted_or_listed_as_not_the_users() -> None:
    placed = [*exported_tables(), *NOT_EXPORTED, *SHARED]
    duplicated = sorted({t for t in placed if placed.count(t) > 1})
    assert duplicated == [], f"in more than one list: {duplicated}"
    missing = sorted(set(TABLES) - set(placed))
    assert missing == [], (
        f"{missing}: decide what export and delete do with each; add it to AREAS or "
        "NOT_EXPORTED (the user's) or SHARED (not the user's) in nexus.application.user_data"
    )
    assert sorted(set(placed) - set(TABLES)) == [], "listed, but not in the schema"


def test_a_table_that_points_at_a_user_is_never_called_shared() -> None:
    linked = user_linked()
    wrong = {name: why for name, why in linked.items() if name in SHARED}
    assert wrong == {}, "these hold a user's data, so they must be exported/deleted"
    unowned = {name: why for name, why in linked.items() if name not in owned_tables()}
    assert unowned == {}
    assert "users" in owned_tables()


def test_every_exclusion_has_a_reason() -> None:
    for name, reason in {**NOT_EXPORTED, **SHARED}.items():
        assert len(reason) > 10, name
    assert len({a.file for a in AREAS}) == len(AREAS)
    assert all(a.file.endswith(".json") and a.about and a.tables for a in AREAS)


def test_delete_covers_exactly_the_owned_tables_children_first() -> None:
    assert len(ERASE_ORDER) == len(set(ERASE_ORDER))
    assert set(ERASE_ORDER) == owned_tables()
    assert ERASE_ORDER[-1] == "users"
    position = {name: i for i, name in enumerate(ERASE_ORDER)}
    wrong = []
    for name in ERASE_ORDER:
        for fk in TABLES[name].foreign_keys:
            parent = fk.column.table.name
            if parent in position and parent != name and position[name] > position[parent]:
                wrong.append(f"{name} is deleted after {parent}, which it references")
    assert wrong == []


def points_at_a_user(table: Table) -> set[str]:
    """Columns that name a user, or the owner of the row they belong to (a trip's)."""
    columns: set[str] = set()
    for fk in table.foreign_keys:
        parent = fk.column
        if parent.table.name == "users" or (
            parent.name == "user_id" and parent.table.name in owned_tables()
        ):
            columns.add(fk.parent.name)
    if "user_id" in table.c:
        columns.add("user_id")
    return columns


def test_a_row_is_found_by_every_column_that_names_a_user() -> None:
    for name in ERASE_ORDER:
        table = TABLES[name]
        ties = set(tie_columns(name))
        if name == "jobs":
            assert ties == {"payload->user_id"}
            continue
        assert ties <= set(table.c.keys()), name
        if name == "users":
            assert ties == {"id"}
            continue
        # Reading and deleting both use these, so a column missing here would leave rows
        # (a membership, an invite someone used) behind, or export someone else's.
        assert points_at_a_user(table) <= ties, name


def test_secrets_never_leave() -> None:
    for name in exported_tables():
        names = {c.name for c in exported_columns(TABLES[name])}
        assert not [n for n in names if is_secret(TABLES[name].c[n])], name
    for name in ERASE_ORDER:
        for column in TABLES[name].c:
            secret_looking = any(
                word in column.name for word in ("token", "secret", "password", "hash", "csrf")
            )
            kept = column.name in {c.name for c in exported_columns(TABLES[name])}
            assert not (secret_looking and kept), f"{name}.{column.name}"
    # The ones that exist today.
    assert "token" not in {c.name for c in exported_columns(TABLES["email_connections"])}
    assert "token" not in {c.name for c in exported_columns(TABLES["trip_shares"])}
    assert "token_hash" not in {c.name for c in exported_columns(TABLES["trip_invites"])}


def test_the_chat_checkpoints_are_removed_with_the_user() -> None:
    assert set(CHECKPOINT_THREAD_TABLES) == CHECKPOINT_TABLES - {"checkpoint_migrations"}
