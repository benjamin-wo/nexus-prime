"""Following a plan after each close, and scoring how it ended. Every ticker and
figure here is made up."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from nexus.domain.ledger import UserId
from nexus.domain.market import Bar
from nexus.domain.plans import EventKind, PlanStatus, SavedPlan, Verdict, follow, record

D = Decimal
MADE = date(2026, 9, 28)  # a Monday; the plan uses Friday's close


def saved(verdict: Verdict = Verdict.WAIT, **changes: object) -> SavedPlan:
    base: dict[str, object] = {
        "id": uuid4(),
        "user_id": UserId(uuid4()),
        "run_id": None,
        "symbol": "ACME",
        "verdict": verdict,
        "as_of": date(2026, 9, 25),
        "valid_until": MADE + timedelta(days=14),
        "close": D("127.00"),
        "entry_low": D("124.00"),
        "entry_high": D("125.00"),
        "stop": D("122.00"),
        "body": {"targets": [{"price": "130.00"}, {"price": "140.00"}], "trail_to": "124.50"},
        "status": PlanStatus.OPEN,
        "created_at": datetime(2026, 9, 28, 4, tzinfo=UTC),
    }
    base.update(changes)
    return SavedPlan(**base)  # type: ignore[arg-type]


def day(n: int, close: str, low: str | None = None, high: str | None = None) -> Bar:
    c = D(close)
    return Bar("ACME", MADE + timedelta(days=n), c, D(high or close), D(low or close), c, c, 1)


def test_a_buy_plan_counts_once_it_dips_into_the_zone_then_hits_its_target() -> None:
    plan = saved()
    # Day 1 stays above the zone: nothing yet, but the day is checked.
    first = follow(plan, [day(1, "127.50", low="126.00")], today=MADE + timedelta(days=1))
    assert first.status is PlanStatus.OPEN and first.events == []
    assert first.entered_on is None and first.checked_through == MADE + timedelta(days=1)
    # Day 2 dips to 124.80: bought. Day 4 reaches 130.20: first target.
    bars = [
        day(1, "127.50", low="126.00"),
        day(2, "125.50", low="124.80"),
        day(3, "128.00"),
        day(4, "129.50", high="130.20"),
    ]
    done = follow(plan, bars, today=MADE + timedelta(days=4))
    assert [e.kind for e in done.events] == [EventKind.ENTRY, EventKind.TARGET]
    assert done.status is PlanStatus.TARGET and done.entered_on == MADE + timedelta(days=2)
    assert done.outcome_price == D("130.00")
    assert done.result_percent == D("4.4")  # from mid-zone 124.50


def test_a_close_below_the_stop_ends_it_even_on_a_day_that_touched_the_target() -> None:
    plan = saved(entered_on=MADE + timedelta(days=1), checked_through=MADE + timedelta(days=1))
    bars = [day(2, "121.50", low="121.00", high="130.50")]
    done = follow(plan, bars, today=MADE + timedelta(days=2))
    assert done.status is PlanStatus.STOPPED and done.outcome_price == D("121.50")
    assert done.result_percent == D("-2.4")
    assert [e.kind for e in done.events] == [EventKind.STOPPED]


def test_plans_run_out_honestly() -> None:
    later = MADE + timedelta(days=15)
    # A buy plan that never dipped to its zone: ran out, never bought, no result.
    never = follow(saved(), [day(3, "128.00", low="126.50")], today=later)
    assert never.status is PlanStatus.EXPIRED and never.entered_on is None
    assert never.result_percent is None
    # A held stock's plan counts from the day it was made, measured from that close.
    held = follow(saved(Verdict.HOLD), [day(3, "128.00"), day(9, "126.00")], today=later)
    assert held.status is PlanStatus.EXPIRED and held.outcome_price == D("126.00")
    assert held.result_percent == D("-0.8")
    # Days already checked aren't looked at again.
    checked = saved(Verdict.HOLD, checked_through=MADE + timedelta(days=3))
    again = follow(checked, [day(3, "121.00")], today=MADE + timedelta(days=4))
    assert again.status is PlanStatus.OPEN and again.events == []


def test_the_record_counts_misses_too() -> None:
    plans = [
        saved(status=PlanStatus.TARGET, entered_on=MADE, result_percent=D("4.4")),
        saved(status=PlanStatus.STOPPED, entered_on=MADE, result_percent=D("-2.4")),
        saved(status=PlanStatus.EXPIRED),  # never bought
        saved(Verdict.HOLD, status=PlanStatus.EXPIRED, result_percent=D("-0.8")),
        saved(),  # still open
        saved(Verdict.NO_TRADE, status=PlanStatus.OPEN),  # not a call: not counted
    ]
    r = record(plans)
    assert (r.finished, r.targets, r.stopped, r.expired, r.never_entered, r.open) == (
        4,
        1,
        1,
        2,
        1,
        1,
    )
    assert r.average_result == D("0.4")


def test_the_record_checks_the_odds_against_what_happened() -> None:
    def odds(chance: int) -> dict[str, object]:
        return {"targets": [{"price": "130.00"}], "odds": {"targets": [{"chance": chance}]}}

    plans = [
        saved(status=PlanStatus.TARGET, entered_on=MADE, body=odds(40)),
        saved(status=PlanStatus.STOPPED, entered_on=MADE, body=odds(30)),
        saved(status=PlanStatus.EXPIRED, body=odds(90)),  # never bought: not a test of the odds
        saved(status=PlanStatus.TARGET, entered_on=MADE),  # made before odds
        saved(body=odds(50)),  # still open
    ]
    c = record(plans).calibration
    assert c is not None and (c.plans, c.said, c.happened) == (2, 35, 50)
    assert record(plans[3:]).calibration is None
