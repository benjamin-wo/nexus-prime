from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from nexus.domain.ledger import UserId
from nexus.domain.notifications import (
    Frequency,
    NotificationSettings,
    heading,
    is_due,
    last_slot,
)

SG = ZoneInfo("Asia/Singapore")


def sg(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=SG)


@pytest.mark.parametrize(
    ("frequency", "now", "slot"),
    [
        (Frequency.DAILY, sg(28, 21, 30), sg(28, 21)),
        (Frequency.DAILY, sg(28, 20, 59), sg(27, 21)),
        (Frequency.THRICE_DAILY, sg(28, 9, 5), sg(28, 9)),
        (Frequency.THRICE_DAILY, sg(28, 13, 59), sg(28, 9)),
        (Frequency.THRICE_DAILY, sg(28, 7, 0), sg(27, 20)),
        (Frequency.HOURLY, sg(28, 15, 42), sg(28, 15)),
        (Frequency.HOURLY, sg(28, 23, 10), sg(28, 21)),  # none in quiet hours
        (Frequency.HOURLY, sg(28, 7, 59), sg(27, 21)),
    ],
)
def test_summaries_fall_due_at_fixed_local_times(
    frequency: Frequency, now: datetime, slot: datetime
) -> None:
    assert last_slot(frequency, now.astimezone(UTC), SG) == slot


def test_instant_is_always_due_and_off_never() -> None:
    now = sg(28, 12).astimezone(UTC)
    assert last_slot(Frequency.INSTANT, now, SG) == now
    assert last_slot(Frequency.OFF, now, SG) is None


def test_due_once_per_slot() -> None:
    user = UserId(uuid4())
    told = NotificationSettings(user, Frequency.DAILY, sg(27, 21, 3))
    assert not is_due(told, sg(28, 20, 59), SG)
    assert is_due(told, sg(28, 21, 0), SG)
    assert not is_due(NotificationSettings(user, Frequency.DAILY, sg(28, 21, 1)), sg(28, 22), SG)
    assert not is_due(NotificationSettings(user), sg(28, 21, 5), SG)  # not started yet
    assert not is_due(NotificationSettings(user, Frequency.OFF, sg(1, 0)), sg(28, 21, 5), SG)


def test_headings_say_what_a_summary_covers() -> None:
    assert heading(Frequency.DAILY, sg(27, 21), sg(28, 21), SG) == "Today"
    assert heading(Frequency.THRICE_DAILY, sg(28, 9), sg(28, 14), SG) == "Since 9am"
    assert heading(Frequency.HOURLY, sg(28, 14, 30), sg(28, 15), SG) == "Since 2:30pm"
    assert heading(Frequency.THRICE_DAILY, sg(27, 20), sg(28, 9), SG) == "Since 8pm yesterday"
