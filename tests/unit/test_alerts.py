"""Alerts during the US session: what a live price says about a plan, a big move, the
words of an alert, the NYSE calendar behind the morning summary, and the settings that
steer them. Every ticker and figure here is made up."""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from nexus.application.market_summary import due_now, session_to_report
from nexus.domain.alerts import (
    MINUS,
    AlertKind,
    big_move,
    move_text,
    plan_alerts,
    signed,
    stop_text,
)
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Role, User, UserId
from nexus.domain.market import (
    NYSE_HOLIDAYS,
    MarketStatus,
    Session,
    is_trading_day,
    last_weekday_closed,
    previous_trading_day,
    session_day,
    session_of,
    session_open_at,
)
from nexus.domain.notifications import (
    MAX_MOVE_PERCENT,
    MIN_MOVE_PERCENT,
    NotificationSettings,
    describe_quiet,
    move_percent,
)
from nexus.domain.plans import Verdict
from tests.unit.test_plan_follow import MADE, saved

D = Decimal
NY = ZoneInfo("America/New_York")
SG = ZoneInfo("Asia/Singapore")


def ny(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=NY)


# --- plans against a live price -----------------------------------------------------------
# saved(): buy zone 124 to 125, stop 122, first target 130.


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ("126.00", []),  # above the zone
        ("125.00", [AlertKind.PLAN_ENTRY]),  # at its top
        ("124.00", [AlertKind.PLAN_ENTRY]),
        ("123.00", [AlertKind.PLAN_ENTRY]),  # through the zone, still above the stop
        ("122.00", []),  # at the stop: the setup is broken, not a chance to buy
        ("100.00", []),
        ("131.00", []),  # a plan not bought has no target to reach
    ],
)
def test_a_plan_waiting_for_its_zone(price: str, expected: list[AlertKind]) -> None:
    assert plan_alerts(saved(), D(price), holds=False) == expected


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ("126.00", []),
        ("122.01", []),
        ("122.00", [AlertKind.PLAN_STOP]),  # at the stop counts
        ("90.00", [AlertKind.PLAN_STOP]),
        ("129.99", []),
        ("130.00", [AlertKind.PLAN_TARGET]),  # at the target counts
        ("140.00", [AlertKind.PLAN_TARGET]),
    ],
)
def test_a_plan_already_entered(price: str, expected: list[AlertKind]) -> None:
    plan = saved(entered_on=MADE)
    assert plan_alerts(plan, D(price), holds=False) == expected


def test_a_plan_for_a_stock_already_held_is_entered_from_the_start() -> None:
    plan = saved(Verdict.HOLD)
    assert plan_alerts(plan, D("121"), holds=True) == [AlertKind.PLAN_STOP]
    assert plan_alerts(plan, D("131"), holds=True) == [AlertKind.PLAN_TARGET]
    assert plan_alerts(plan, D("124"), holds=True) == []  # no buy zone to enter


def test_a_stop_is_told_for_a_stock_the_user_holds_even_if_the_plan_is_not_entered() -> None:
    plan = saved()
    assert plan_alerts(plan, D("121"), holds=True) == [AlertKind.PLAN_STOP]
    assert plan_alerts(plan, D("121"), holds=False) == []


def test_a_plan_without_a_stop_or_target_has_nothing_to_reach() -> None:
    plan = saved(entered_on=MADE, stop=None, body={})
    assert plan_alerts(plan, D("50"), holds=True) == []
    assert plan_alerts(plan, D("500"), holds=True) == []
    unzoned = saved(entry_low=None, entry_high=None)
    assert plan_alerts(unzoned, D("50"), holds=False) == []


# --- big moves ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ("104.99", None),
        ("105.00", D("5.00")),  # exactly the threshold counts
        ("110.00", D("10.00")),
        ("95.00", D("-5.00")),
        ("95.01", None),
        ("60.00", D("-40.00")),
    ],
)
def test_a_big_move_is_the_threshold_or_more_either_way(price: str, expected: D | None) -> None:
    assert big_move(D(price), D("100"), D("5")) == expected


def test_a_big_move_needs_a_previous_close() -> None:
    assert big_move(D("100"), D("0"), D("5")) is None


def test_the_users_own_threshold_decides() -> None:
    assert big_move(D("103"), D("100"), D("3")) == D("3.00")
    assert big_move(D("103"), D("100"), D("3.1")) is None


def test_the_words_of_a_big_move() -> None:
    at = datetime(2026, 10, 19, 14, 42, tzinfo=UTC)  # 22:42 in Singapore
    assert move_text("NVDA", D("-5.44"), D("182.4"), at, SG) == (
        f"📉 NVDA {MINUS}5.4% today at 10:42pm, 182.40"
    )
    assert move_text("AMD", D("6.05"), D("1234.5"), at, SG) == (
        "📈 AMD +6.1% today at 10:42pm, 1,234.50"
    )
    assert signed(D("0.04")) == "+0.0%" and signed(D("-12")) == f"{MINUS}12.0%"


def test_the_words_of_a_stop_follow_the_plans() -> None:
    at = datetime(2026, 10, 19, 14, 42, tzinfo=UTC)
    text = stop_text(saved(), D("121.5"), at, SG)
    assert text == (
        "🛑 ACME is at 121.50 as of 10:42pm, at or below its stop of 122.00. The plan says "
        "cut it: the reason to own it has broken."
    )


# --- the NYSE calendar --------------------------------------------------------------------


def test_the_listed_holidays_are_weekdays_in_this_year_and_next() -> None:
    assert len(NYSE_HOLIDAYS) == 20
    assert {d.year for d in NYSE_HOLIDAYS} == {2026, 2027}
    assert all(d.weekday() < 5 for d in NYSE_HOLIDAYS)
    assert date(2026, 7, 3) in NYSE_HOLIDAYS  # 4 July is a Saturday: observed on the Friday
    assert date(2027, 7, 5) in NYSE_HOLIDAYS  # a Sunday: observed on the Monday
    assert date(2027, 12, 31) not in NYSE_HOLIDAYS  # New Year's Day 2028 is a Saturday


def test_trading_days_skip_weekends_and_holidays() -> None:
    assert is_trading_day(date(2026, 10, 19)) and not is_trading_day(date(2026, 10, 17))
    assert not is_trading_day(date(2026, 11, 26))  # Thanksgiving
    assert previous_trading_day(date(2026, 11, 27)) == date(2026, 11, 25)
    assert previous_trading_day(date(2026, 10, 19)) == date(2026, 10, 16)


def test_the_last_weekday_closed() -> None:
    assert last_weekday_closed(ny("2026-10-20 15:59")) == date(2026, 10, 19)
    assert last_weekday_closed(ny("2026-10-20 16:00")) == date(2026, 10, 20)
    assert last_weekday_closed(ny("2026-10-19 09:00")) == date(2026, 10, 16)  # Monday morning
    assert last_weekday_closed(ny("2026-10-18 12:00")) == date(2026, 10, 16)  # Sunday
    # A holiday is still the last weekday: the summary then skips it.
    assert last_weekday_closed(ny("2026-11-27 08:00")) == date(2026, 11, 26)


def test_where_the_market_is() -> None:
    open_ = MarketStatus(True, "regular", None, ny("2026-10-20 10:00"))
    assert session_of(open_, ny("2026-10-20 10:00")) is Session.LIVE
    assert session_of(None, ny("2026-10-20 10:00")) is Session.LIVE
    assert session_of(None, ny("2026-10-20 16:00")) is Session.CLOSED_TODAY
    assert session_of(None, ny("2026-10-20 08:00")) is Session.PREVIOUS
    assert session_of(None, ny("2026-10-17 12:00")) is Session.PREVIOUS  # a Saturday
    assert session_of(None, ny("2026-11-26 18:00")) is Session.PREVIOUS  # Thanksgiving
    holiday = MarketStatus(False, None, "Made-up Day", ny("2026-10-20 18:00"))
    assert session_of(holiday, ny("2026-10-20 18:00")) is Session.PREVIOUS
    assert session_day(None, ny("2026-10-20 18:00")) == date(2026, 10, 20)
    assert session_day(None, ny("2026-10-20 08:00")) == date(2026, 10, 19)
    assert session_day(None, ny("2026-10-19 08:00")) == date(2026, 10, 16)
    assert session_open_at(date(2026, 10, 20)) == ny("2026-10-20 09:30")


# --- when the morning summary is due ------------------------------------------------------


def person(zone: str) -> User:
    return User(
        UserId(uuid4()),
        1,
        1,
        zone,
        "SGD",
        Role.MEMBER,
        datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_a_morning_after_a_trading_day_has_a_session_to_tell_of() -> None:
    # 08:00 Singapore on Tuesday 20 October is 20:00 on Monday in New York.
    assert session_to_report(datetime(2026, 10, 20, 8, tzinfo=SG)) == date(2026, 10, 19)
    # 08:00 in New York on a Tuesday: Monday closed 16 hours ago.
    assert session_to_report(ny("2026-10-20 08:00")) == date(2026, 10, 19)
    # Saturday 08:00 in Singapore is Friday evening in New York.
    assert session_to_report(datetime(2026, 10, 24, 8, tzinfo=SG)) == date(2026, 10, 23)


def test_a_weekend_never_repeats_friday() -> None:
    assert session_to_report(datetime(2026, 10, 25, 8, tzinfo=SG)) is None  # Sunday
    assert session_to_report(datetime(2026, 10, 26, 8, tzinfo=SG)) is None  # Monday, Asia
    assert session_to_report(ny("2026-10-26 08:00")) is None  # Monday in New York


def test_the_morning_after_a_holiday_has_nothing_to_tell_of() -> None:
    # Thanksgiving, Thursday 26 November 2026: no session, so Friday morning is skipped.
    assert session_to_report(datetime(2026, 11, 27, 8, tzinfo=SG)) is None
    assert session_to_report(ny("2026-11-27 08:00")) is None
    # The morning after Friday's half day is a Saturday: Friday's session is told of.
    assert session_to_report(datetime(2026, 11, 28, 8, tzinfo=SG)) == date(2026, 11, 27)


def test_the_summary_is_due_from_eight_to_noon_local_time() -> None:
    user = person("Asia/Singapore")
    assert not due_now(user, datetime(2026, 10, 20, 7, 59, tzinfo=SG))
    assert due_now(user, datetime(2026, 10, 20, 8, 0, tzinfo=SG))
    assert due_now(user, datetime(2026, 10, 20, 11, 59, tzinfo=SG))
    assert not due_now(user, datetime(2026, 10, 20, 12, 0, tzinfo=SG))
    la = person("America/Los_Angeles")
    assert due_now(la, datetime(2026, 10, 20, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles")))


# --- the settings -------------------------------------------------------------------------


def test_the_defaults() -> None:
    settings = NotificationSettings(UserId(uuid4()))
    assert (settings.quiet_start, settings.quiet_end) == (time(23), time(8))
    assert settings.move_alert_percent == D(5) and settings.market_summary is True


@pytest.mark.parametrize(("raw", "kept"), [(1, "1.0"), ("3", "3.0"), (2.55, "2.6"), ("20", "20.0")])
def test_a_big_move_can_be_one_to_twenty_percent(raw: object, kept: str) -> None:
    assert move_percent(raw) == D(kept)  # type: ignore[arg-type]
    assert MIN_MOVE_PERCENT == 1 and MAX_MOVE_PERCENT == 20


@pytest.mark.parametrize("raw", [0, "0.9", "20.1", -5, 50, "abc", "NaN", "Infinity", ""])
def test_a_threshold_outside_one_to_twenty_is_refused(raw: object) -> None:
    with pytest.raises(InvalidInput):
        move_percent(raw)  # type: ignore[arg-type]


def test_quiet_hours_in_words() -> None:
    assert describe_quiet(time(23), time(8)) == "11pm to 8am"
    assert describe_quiet(time(22, 30), time(7)) == "10:30pm to 7am"
    assert describe_quiet(time(23), time(23)) == "none"
