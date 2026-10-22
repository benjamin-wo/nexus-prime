"""Which messages go at once, wait for quiet hours or wait for a digest. All times are
local (the made-up user lives in Singapore) and every text is made up."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.notifications import (
    DIGEST_LINES,
    Decision,
    Digest,
    HoldUntil,
    Level,
    Notification,
    Send,
    Status,
    daily_cap,
    decide,
    digest_text,
    local_day,
    next_digest_at,
)

SG = ZoneInfo("Asia/Singapore")
NY = ZoneInfo("America/New_York")
START, END = time(23), time(8)
CAP = 6


def sg(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=SG)


def pick(
    level: Level,
    now: datetime,
    *,
    sent: int = 0,
    buttons: bool = False,
    quiet: tuple[time, time] = (START, END),
) -> Decision:
    return decide(level, now, quiet[0], quiet[1], sent, CAP, buttons)


# --- urgent ---------------------------------------------------------------------------


@pytest.mark.parametrize("now", [sg(20, 12), sg(20, 23, 30), sg(21, 3)])
@pytest.mark.parametrize("buttons", [False, True])
def test_urgent_is_sent_at_any_hour_and_even_over_the_cap(now: datetime, buttons: bool) -> None:
    assert pick(Level.URGENT, now, sent=CAP + 10, buttons=buttons) == Send()


# --- now --------------------------------------------------------------------------------


def test_now_is_sent_in_the_daytime_under_the_cap() -> None:
    assert pick(Level.NOW, sg(20, 12), sent=0) == Send()
    assert pick(Level.NOW, sg(20, 12), sent=CAP - 1) == Send()


@pytest.mark.parametrize("buttons", [False, True])
def test_now_in_quiet_hours_is_held_until_they_end(buttons: bool) -> None:
    assert pick(Level.NOW, sg(20, 23, 30), buttons=buttons) == HoldUntil(sg(21, 8))
    assert pick(Level.NOW, sg(21, 3), buttons=buttons) == HoldUntil(sg(21, 8))
    # Quiet hours come first: a user over the cap hears from it at 8 either way.
    assert pick(Level.NOW, sg(21, 3), sent=CAP, buttons=buttons) == HoldUntil(sg(21, 8))


def test_now_over_the_cap_goes_in_the_digest() -> None:
    assert pick(Level.NOW, sg(20, 12), sent=CAP) == Digest(sg(20, 19))
    assert pick(Level.NOW, sg(20, 12), sent=CAP + 3) == Digest(sg(20, 19))
    assert pick(Level.NOW, sg(20, 20), sent=CAP) == Digest(sg(21, 8))


def test_now_with_buttons_is_sent_even_over_the_cap() -> None:
    assert pick(Level.NOW, sg(20, 12), sent=CAP, buttons=True) == Send()
    assert pick(Level.NOW, sg(20, 12), sent=CAP + 5, buttons=True) == Send()


@pytest.mark.parametrize(
    ("now", "result"),
    [
        (sg(20, 7, 59, 59), HoldUntil(sg(20, 8))),  # the last second of quiet hours
        (sg(20, 8), Send()),  # the first second after
        (sg(20, 22, 59, 59), Send()),
        (sg(20, 23), HoldUntil(sg(21, 8))),
    ],
)
def test_quiet_hours_start_and_end_on_the_minute(now: datetime, result: Decision) -> None:
    assert pick(Level.NOW, now) == result


def test_quiet_hours_within_one_day_and_none_at_all() -> None:
    day = (time(1), time(6))
    assert pick(Level.NOW, sg(20, 3), quiet=day) == HoldUntil(sg(20, 6))
    assert pick(Level.NOW, sg(20, 23, 30), quiet=day) == Send()
    none = (time(0), time(0))
    assert pick(Level.NOW, sg(20, 3), quiet=none) == Send()


# --- digest -----------------------------------------------------------------------------


@pytest.mark.parametrize("buttons", [False, True])
def test_digest_is_never_sent_alone(buttons: bool) -> None:
    assert pick(Level.DIGEST, sg(20, 12), buttons=buttons) == Digest(sg(20, 19))
    assert pick(Level.DIGEST, sg(20, 12), sent=0, buttons=buttons) != Send()
    assert pick(Level.DIGEST, sg(20, 19, 30), buttons=buttons) == Digest(sg(21, 8))
    assert pick(Level.DIGEST, sg(21, 2), buttons=buttons) == Digest(sg(21, 8))


def test_the_next_digest_comes_at_quiet_end_or_in_the_evening() -> None:
    assert next_digest_at(sg(20, 9), START, END) == sg(20, 19)
    assert next_digest_at(sg(20, 19), START, END) == sg(21, 8)  # strictly after
    assert next_digest_at(sg(20, 18, 59), START, END) == sg(20, 19)
    assert next_digest_at(sg(20, 23, 59), START, END) == sg(21, 8)
    assert next_digest_at(sg(20, 7, 30), START, END) == sg(20, 8)


def test_a_digest_is_not_due_inside_quiet_hours_or_when_there_are_none_to_end() -> None:
    # Quiet from 18:00 to 07:00: the evening digest would be in quiet hours.
    early = (time(18), time(7))
    assert next_digest_at(sg(20, 9), *early) == sg(21, 7)
    # No quiet hours: only the evening.
    none = (time(8), time(8))
    assert next_digest_at(sg(20, 3), *none) == sg(20, 19)
    assert next_digest_at(sg(20, 20), *none) == sg(21, 19)


# --- the user's day ---------------------------------------------------------------------


def test_the_day_is_the_users_local_day() -> None:
    start, end = local_day(datetime(2026, 10, 20, 15, 59, 59, tzinfo=UTC), SG)  # 23:59:59
    assert (start, end) == (sg(20, 0), sg(21, 0))
    start, end = local_day(datetime(2026, 10, 20, 16, 0, tzinfo=UTC), SG)  # midnight
    assert (start, end) == (sg(21, 0), sg(22, 0))
    assert start <= datetime(2026, 10, 20, 16, 0, tzinfo=UTC) < end
    # The same instant is another day for a user in New York (12:00 on the 20th).
    start, end = local_day(datetime(2026, 10, 20, 16, 0, tzinfo=UTC), NY)
    assert start.astimezone(UTC) == datetime(2026, 10, 20, 4, 0, tzinfo=UTC)
    assert end.astimezone(UTC) == datetime(2026, 10, 21, 4, 0, tzinfo=UTC)


def test_a_day_when_the_clocks_change_is_not_24_hours_long() -> None:
    start, end = local_day(datetime(2026, 11, 1, 12, 0, tzinfo=UTC), NY)  # clocks go back
    assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=25)


# --- the daily cap ----------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "value"), [(3, 3), (6, 6), (20, 20), ("12", 12), (7.0, 7)])
def test_a_daily_cap_is_a_whole_number_from_3_to_20(raw: int | float | str, value: int) -> None:
    assert daily_cap(raw) == value


@pytest.mark.parametrize("raw", [2, 0, -1, 21, 100, 4.5, "x", "", "NaN", "Infinity", True])
def test_other_daily_caps_are_refused(raw: int | float | str) -> None:
    with pytest.raises(InvalidInput):
        daily_cap(raw)


# --- the digest message -------------------------------------------------------------------


def item(text: str, n: int = 0) -> Notification:
    return Notification(
        uuid4(),
        UserId(uuid4()),
        "big_move",
        Level.DIGEST,
        text,
        None,
        False,
        sg(20, 10, n),
        Status.HELD,
        held_until=sg(20, 19),
    )


def test_a_digest_lists_what_was_held_oldest_first() -> None:
    text = digest_text([item("📉 ACME -5.4% today", 1), item("You've used 80% of Food.", 2)])
    assert text == "While you were away:\n• 📉 ACME -5.4% today\n• You've used 80% of Food."


def test_a_digest_lists_twelve_and_says_how_many_more() -> None:
    items = [item(f"Thing {n}", n) for n in range(DIGEST_LINES + 3)]
    lines = digest_text(items).split("\n")
    assert len(lines) == 1 + DIGEST_LINES + 1
    assert lines[1] == "• Thing 0" and lines[DIGEST_LINES] == f"• Thing {DIGEST_LINES - 1}"
    assert lines[-1] == "and 3 more — see Notifications on the web"
    assert "more" not in digest_text(items[:DIGEST_LINES])


def test_a_digest_line_is_one_short_line() -> None:
    long = "Tokyo changed:\nadded Dinner at Sushi Ten, " + "moved Senso-ji " * 30
    line = digest_text([item(long)]).split("\n")[1]
    assert "\n" not in line and line.startswith("• Tokyo changed: added Dinner")
    assert len(line) <= 2 + 200 and line.endswith("…")
