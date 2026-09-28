from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nexus.domain.money import Money
from nexus.domain.planning import month_start, next_month_start, quiet_until, reached
from nexus.jobs.runner import backoff, slot_start

SGT = ZoneInfo("Asia/Singapore")


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


@pytest.mark.parametrize(
    ("spent", "expected"),
    [
        ("0", []),
        ("49.99", []),
        ("50.00", [50]),
        ("79.9999", [50]),
        ("80", [50, 80]),
        ("99.99", [50, 80]),
        ("100.00", [50, 80, 100]),
        ("250", [50, 80, 100]),
    ],
)
def test_thresholds_are_exact(spent: str, expected: list[int]) -> None:
    assert reached(sgd(spent), sgd("100")) == expected


def test_thresholds_need_one_currency() -> None:
    with pytest.raises(ValueError, match="currency"):
        reached(Money.of("1", "USD"), sgd("100"))


def test_month_bounds_roll_over_the_year() -> None:
    assert month_start(date(2026, 12, 31)) == date(2026, 12, 1)
    assert next_month_start(date(2026, 12, 31)) == date(2027, 1, 1)
    assert next_month_start(date(2026, 1, 31)) == date(2026, 2, 1)


@pytest.mark.parametrize(
    ("local", "until"),
    [
        (datetime(2026, 9, 28, 8, 0, tzinfo=SGT), None),
        (datetime(2026, 9, 28, 21, 59, tzinfo=SGT), None),
        (datetime(2026, 9, 28, 22, 0, tzinfo=SGT), datetime(2026, 9, 29, 8, 0, tzinfo=SGT)),
        (datetime(2026, 9, 30, 23, 30, tzinfo=SGT), datetime(2026, 10, 1, 8, 0, tzinfo=SGT)),
        (datetime(2026, 9, 28, 7, 59, tzinfo=SGT), datetime(2026, 9, 28, 8, 0, tzinfo=SGT)),
        (datetime(2026, 9, 28, 0, 0, tzinfo=SGT), datetime(2026, 9, 28, 8, 0, tzinfo=SGT)),
    ],
)
def test_quiet_hours(local: datetime, until: datetime | None) -> None:
    assert quiet_until(local) == until


def test_quiet_hours_need_a_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        quiet_until(datetime(2026, 9, 28, 12))


def test_slots_align_to_the_interval() -> None:
    every = timedelta(minutes=10)
    now = datetime(2026, 9, 28, 12, 17, 45, tzinfo=UTC)
    assert slot_start(now, every) == datetime(2026, 9, 28, 12, 10, tzinfo=UTC)
    assert slot_start(datetime(2026, 9, 28, 12, 10, tzinfo=UTC), every) == slot_start(now, every)


def test_backoff_grows_and_caps() -> None:
    assert [backoff(n) for n in (1, 2, 3)] == [timedelta(minutes=m) for m in (2, 4, 8)]
    assert backoff(20) == timedelta(minutes=60)
