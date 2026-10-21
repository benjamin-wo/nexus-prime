"""Keeping a plan fresh, in the rules: the notes when the price is already past the plan,
what makes a plan go stale, what is worth a message, and how the record treats a replaced
plan. Every ticker and figure here is made up."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from nexus.application.research import NEWS_EVERY, NEWS_IN_SESSION, news_every
from nexus.domain.market import MarketStatus, PriceKind
from nexus.domain.plans import (
    PlanNumbers,
    PlanStatus,
    RefreshKind,
    RefreshReason,
    SavedPlan,
    Verdict,
    plan,
    price_notes,
    record,
    refresh_message,
    refresh_reason,
)
from tests.unit.test_plan_follow import saved
from tests.unit.test_plans import TODAY, held, levels

D = Decimal
LIVE = PriceKind.LIVE


def numbers(close: str = "127.00", **kw: Any) -> PlanNumbers:
    return plan(levels(close, **kw), today=TODAY)


# --- the notes when the live price is already past the plan ----------------------------


def test_a_live_price_in_the_buy_zone_is_noted_for_a_plan_that_waits_for_a_dip() -> None:
    n = numbers()  # close 127: zone 124.00 to 125.00, stop 122.00
    assert n.verdict is Verdict.WAIT
    assert price_notes(n, D("124.50"), LIVE) == [
        "The price is already in the buy zone: 124.50 now, buy zone 124.00 to 125.00."
    ]
    assert price_notes(n, D("125.00"), PriceKind.PROVISIONAL_CLOSE) != []


def test_a_live_price_under_the_buy_zone_or_the_stop_is_noted() -> None:
    n = numbers()
    [under] = price_notes(n, D("123.00"), LIVE)
    assert under.startswith("The price is already under the buy zone: 123.00 now, buy zone 124.00")
    assert "worked out from the last close" in under
    [stopped] = price_notes(n, D("121.50"), LIVE)
    assert stopped.startswith("The price is already under the stop: 121.50 now, stop 122.00.")


def test_no_note_when_the_price_is_the_close_or_has_not_gone_past_the_plan() -> None:
    n = numbers()
    assert price_notes(n, D("100.00"), PriceKind.CLOSE) == []
    assert price_notes(n, D("126.00"), LIVE) == []  # above the zone, as the plan says
    # A plan whose close is already in the zone says so itself.
    inside = numbers("124.50")
    assert inside.verdict is Verdict.IN_ZONE
    assert price_notes(inside, D("124.60"), LIVE) == []
    assert price_notes(inside, D("123.00"), LIVE) != []


def test_no_note_for_a_plan_that_makes_no_call() -> None:
    n = numbers("127.00", support=[], averages={})  # falling with no support below
    assert n.verdict is Verdict.NO_TRADE
    assert price_notes(n, D("50.00"), LIVE) == []


def test_a_held_stock_has_an_add_more_zone() -> None:
    n = plan(levels("127.00"), today=TODAY, held=held())
    assert n.verdict is Verdict.HOLD
    [note] = price_notes(n, D("124.50"), LIVE)
    assert note.startswith("The price is already in the add-more zone: 124.50 now")


# --- what makes a plan go stale ---------------------------------------------------------

MADE = datetime(2026, 9, 28, 4, tzinfo=UTC)  # the plan's created_at: Monday, midnight in New York
ATR = D("2.00")
STEADY = D("127.50")


def why(
    *,
    now: datetime = MADE + timedelta(days=1),
    price: Decimal | None = STEADY,
    atr: Decimal | None = ATR,
    earnings: list[date] | None = None,
    **plan_changes: object,
) -> RefreshReason | None:
    return refresh_reason(
        saved(Verdict.WAIT, **plan_changes), now=now, price=price, atr=atr, earnings=earnings or []
    )


def test_a_fresh_plan_with_a_steady_price_is_left_alone() -> None:
    assert why() is None
    assert why(price=None) is None


def test_a_price_more_than_an_atr_away_goes_stale_in_either_direction() -> None:
    assert why(price=D("129.00")) is None  # exactly one ATR from the close of 127
    up = why(price=D("131.60"))
    assert up is not None and up.kind is RefreshKind.MOVED and up.atrs == D("2.3")
    assert up.text == "price moved 2.3 ATR"
    down = why(price=D("124.40"))
    assert down is not None and down.kind is RefreshKind.MOVED and down.atrs == D("1.3")


def test_a_move_is_measured_from_the_price_the_plan_was_written_with() -> None:
    # Written at a live 120.00: 127.50 is 3.8 ATR away, though it is near the close of 127.
    assert why(price=D("127.50")) is None  # against the close of 127, a quarter of an ATR
    written = refresh_reason(
        saved(price=D("120.00")),
        now=MADE + timedelta(days=1),
        price=D("127.50"),
        atr=ATR,
        earnings=[],
    )
    assert written is not None and written.atrs == D("3.8")  # 7.5 / 2 = 3.75, rounded up


def test_no_atr_means_no_move_trigger() -> None:
    assert why(price=D("200.00"), atr=None) is None
    assert why(price=D("200.00"), atr=D("0")) is None


def test_earnings_since_the_plan_was_made_and_now_past_make_it_stale() -> None:
    now = MADE + timedelta(days=3)  # Thursday 1 Oct, New York morning
    reported = date(2026, 9, 30)
    found = why(now=now, earnings=[reported])
    assert found is not None and found.kind is RefreshKind.EARNINGS
    # Not before the plan was made, not today (it may not have reported yet), not ahead.
    assert why(now=now, earnings=[date(2026, 9, 28)]) is None
    assert why(now=now, earnings=[date(2026, 9, 28) - timedelta(days=30)]) is None
    assert why(now=now, earnings=[date(2026, 10, 1)]) is None
    assert why(now=now, earnings=[date(2026, 10, 9)]) is None


def test_a_plan_a_week_old_goes_stale() -> None:
    assert why(now=MADE + timedelta(days=7) - timedelta(minutes=1)) is None
    found = why(now=MADE + timedelta(days=7))
    assert found is not None and found.kind is RefreshKind.AGE


def test_a_plan_past_its_date_is_stale_and_that_comes_first() -> None:
    # valid until 12 Oct (a New York date): still good on the day, over the day after.
    made = MADE + timedelta(days=10)
    eve = datetime(2026, 10, 12, 23, 0, tzinfo=UTC)  # 19:00 on the 12th in New York
    assert (
        refresh_reason(saved(created_at=made), now=eve, price=D("127.00"), atr=ATR, earnings=[])
        is None
    )
    morning = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)  # 01:00 on the 13th in New York
    found = refresh_reason(
        saved(created_at=made), now=morning, price=D("300.00"), atr=ATR, earnings=[]
    )
    assert found is not None and found.kind is RefreshKind.EXPIRED
    assert found.text == "it had run out"


# --- what is worth a message ----------------------------------------------------------


def refreshed(verdict: Verdict = Verdict.WAIT, **changes: object) -> SavedPlan:
    base: dict[str, object] = {
        "symbol": "NVDA",
        "entry_low": D("170.00"),
        "entry_high": D("174.00"),
        "stop": D("165.00"),
        "body": {"atr": "3.00", "targets": [{"price": "180.00"}]},
    }
    base.update(changes)
    return saved(verdict, **base)


def test_a_changed_verdict_is_told_in_one_plain_line() -> None:
    old = refreshed(verdict=Verdict.IN_ZONE)
    new = refreshed(verdict=Verdict.WAIT)
    assert refresh_message(old, new, "price moved 2.3 ATR") == (
        "NVDA plan refreshed (price moved 2.3 ATR): now Wait, was Buy. "
        "Entry 170\N{EN DASH}174, stop 165. First target 180."
    )


def test_a_refresh_that_changed_little_is_made_quietly() -> None:
    old = refreshed()
    # Entry and target 1.4 up (under half an ATR of 3), stop the same.
    new = refreshed(
        entry_low=D("171.40"),
        entry_high=D("175.40"),
        body={"atr": "3.00", "targets": [{"price": "181.40"}]},
    )
    assert refresh_message(old, new, "it was a week old") is None
    assert refresh_message(old, refreshed(), "it was a week old") is None


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"entry_low": D("172.00"), "entry_high": D("176.00")},
            "Entry 172\N{EN DASH}176, stop 165.",
        ),
        ({"stop": D("167.00")}, "Entry 170\N{EN DASH}174, stop 167."),
        (
            {"body": {"atr": "3.00", "targets": [{"price": "182.00"}]}},
            "Entry 170\N{EN DASH}174, stop 165. First target 182.",
        ),
    ],
)
def test_an_entry_stop_or_target_that_moved_over_half_an_atr_is_told(
    changes: dict[str, object], expected: str
) -> None:
    message = refresh_message(refreshed(), refreshed(Verdict.WAIT, **changes), "it was a week old")
    assert message is not None
    assert message.startswith("NVDA plan refreshed (it was a week old): still Wait. ")
    assert expected in message


def test_an_entry_that_appears_or_goes_is_told() -> None:
    new = refreshed(entry_low=None, entry_high=None, verdict=Verdict.NO_TRADE)
    message = refresh_message(refreshed(), new, "price moved 1.4 ATR")
    assert message is not None and "now No trade, was Wait. No entry zone, stop 165." in message
    same_verdict = refreshed(entry_low=None, entry_high=None)
    message = refresh_message(refreshed(), same_verdict, "price moved 1.4 ATR")
    assert message is not None and "still Wait. No entry zone" in message


# --- the record leaves replaced plans out -------------------------------------------------


def test_a_plan_replaced_by_its_refresh_is_not_scored() -> None:
    target = saved(status=PlanStatus.TARGET, entered_on=date(2026, 9, 29), result_percent=D("4.4"))
    replaced = saved(status=PlanStatus.REFRESHED)
    open_now = saved()
    r = record([target, replaced, open_now])
    assert (r.finished, r.targets, r.expired, r.stopped, r.open) == (1, 1, 0, 0, 1)
    assert r.average_result == D("4.4")
    # With only a replaced plan there is nothing to count at all.
    nothing = record([replaced])
    assert (nothing.finished, nothing.open, nothing.never_entered) == (0, 0, 0)


# --- news is due more often while the session is open -----------------------------------------

SESSION = datetime(2026, 10, 19, 14, 42, tzinfo=UTC)  # 10:42 in New York, a Monday
OPEN = MarketStatus(True, "regular", None, SESSION)
SHUT = MarketStatus(False, "post-market", None, SESSION)


def test_news_is_due_hourly_in_the_session_and_every_six_hours_otherwise() -> None:
    assert news_every(OPEN, SESSION) == NEWS_IN_SESSION == timedelta(hours=1)
    assert news_every(SHUT, SESSION) == NEWS_EVERY == timedelta(hours=6)
    # Without the exchange's status the usual hours stand in.
    assert news_every(None, SESSION) == NEWS_IN_SESSION
    assert news_every(None, datetime(2026, 10, 19, 22, 0, tzinfo=UTC)) == NEWS_EVERY  # 18:00 there
    assert news_every(None, datetime(2026, 10, 17, 14, 42, tzinfo=UTC)) == NEWS_EVERY  # Saturday
    # A listed holiday inside the usual hours is no session.
    thanksgiving = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)
    assert news_every(None, thanksgiving) == NEWS_EVERY
