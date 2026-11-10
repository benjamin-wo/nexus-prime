from datetime import UTC, datetime, timedelta

import pytest

from nexus.infra.db.catch_up import (
    CatchUpError,
    asyncpg_dsn,
    decide,
    newest,
    parse_since,
    topological_order,
)

SINCE = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
BEFORE = SINCE - timedelta(minutes=30)
AFTER = SINCE + timedelta(minutes=30)


@pytest.mark.parametrize(
    ("target_has", "same", "railway_ts", "target_ts", "expected"),
    [
        (False, False, AFTER, None, "insert"),
        (False, False, None, None, "insert"),
        (False, False, BEFORE, None, "skip_old"),
        (True, True, AFTER, AFTER, "same"),
        (True, False, AFTER, BEFORE, "update"),
        (True, False, AFTER, None, "update"),
        (True, False, AFTER, AFTER, "conflict"),
        (True, False, BEFORE, AFTER, "target_newer"),
        (True, False, BEFORE, BEFORE, "unexplained"),
        (True, False, None, None, "unexplained"),
    ],
)
def test_decide(
    target_has: bool,
    same: bool,
    railway_ts: datetime | None,
    target_ts: datetime | None,
    expected: str,
) -> None:
    verdict = decide(
        target_has=target_has,
        same=same,
        railway_ts=railway_ts,
        target_ts=target_ts,
        since=SINCE,
    )
    assert verdict == expected


def test_newest_ignores_nulls() -> None:
    assert newest([None, BEFORE, AFTER, None]) == AFTER
    assert newest([None, None]) is None


def test_topological_order_puts_parents_first_and_survives_cycles() -> None:
    edges = {("child", "parent"), ("grandchild", "child"), ("self", "self")}
    order = topological_order(["grandchild", "child", "parent", "self"], edges)
    assert order.index("parent") < order.index("child") < order.index("grandchild")
    cyclic = topological_order(["a", "b", "c"], {("a", "b"), ("b", "a"), ("c", "a")})
    assert sorted(cyclic) == ["a", "b", "c"]


def test_dsn_drops_the_sqlalchemy_driver() -> None:
    assert asyncpg_dsn("postgresql+asyncpg://u:p@h:5432/d") == "postgresql://u:p@h:5432/d"
    assert asyncpg_dsn("postgresql://u:p@h/d") == "postgresql://u:p@h/d"
    with pytest.raises(CatchUpError):
        asyncpg_dsn("nonsense")


def test_since_needs_a_zone() -> None:
    assert parse_since("2026-11-10T12:00:00Z") == SINCE
    assert parse_since("2026-11-10T13:00:00+01:00") == SINCE
    with pytest.raises(CatchUpError):
        parse_since("2026-11-10T12:00:00")
    with pytest.raises(CatchUpError):
        parse_since("yesterday")
