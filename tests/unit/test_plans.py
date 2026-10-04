"""A plan's numbers from made-up levels, and the check that drops any price a model
made up. Every ticker and figure here is made up."""

from datetime import date
from decimal import Decimal

from nexus.domain.investments import Position
from nexus.domain.levels import Levels
from nexus.domain.money import Money
from nexus.domain.plans import Verdict, keep_supported, plan, unsupported

D = Decimal
TODAY = date(2026, 9, 28)


def levels(close: str, **changes: object) -> Levels:
    base: dict[str, object] = {
        "symbol": "ACME",
        "as_of": date(2026, 9, 25),
        "close": D(close),
        "averages": {20: D("124.00"), 50: D("110.00")},
        "rsi": D("55"),
        "atr": D("2.00"),
        "atr_percent": D("1.6"),
        "support": [D("120.00"), D("112.00")],
        "resistance": [D("130.00"), D("140.00")],
        "year_high": D("150.00"),
        "year_low": D("90.00"),
        "days": 300,
    }
    base.update(changes)
    return Levels(**base)  # type: ignore[arg-type]


def test_a_stock_above_its_entry_zone_waits_for_a_pullback() -> None:
    p = plan(levels("127.00"), today=TODAY)
    # The nearest support below 127 is the 20-day average at 124.
    assert (p.entry_low, p.entry_high, p.entry_why) == (D("124.00"), D("125.00"), "20-day average")
    assert p.stop == D("122.00")  # one ATR below the support
    assert p.risk == D("2.50")  # from mid-zone 124.50
    # 130 is only 2.2 times the risk... and kept; 140 is 6.2 times.
    assert [(t.price, t.reward_risk) for t in p.targets] == [
        (D("130.00"), D("2.20")),
        (D("140.00"), D("6.20")),
    ]
    assert p.verdict is Verdict.WAIT
    assert p.valid_until == date(2026, 10, 12)


def test_in_the_zone_and_earnings_inside_the_window() -> None:
    p = plan(levels("124.60"), today=TODAY, earnings=date(2026, 10, 8))
    assert p.verdict is Verdict.IN_ZONE
    assert p.entry_high == D("124.60")  # the zone stops at the close
    assert p.earnings_in_window == date(2026, 10, 8)
    later = plan(levels("124.60"), today=TODAY, earnings=date(2026, 11, 30))
    assert later.earnings_in_window is None


def test_no_trade_when_the_reward_is_too_small_or_theres_no_support() -> None:
    tight = plan(levels("127.00", resistance=[D("129.00")], year_high=D("129.20")), today=TODAY)
    assert tight.verdict is Verdict.NO_TRADE and tight.targets == []
    assert "2 times the risk" in tight.reason
    falling = plan(levels("80.00", averages={}, support=[]), today=TODAY)
    assert falling.verdict is Verdict.NO_TRADE and falling.stop is None
    assert "no support below" in falling.reason


def test_a_held_stock_holds_trims_or_exits_against_its_cost() -> None:
    held = Position("ACME", D("10"), Money(D("100.00"), "USD"))
    hold = plan(levels("127.00"), today=TODAY, held=held)
    assert hold.verdict is Verdict.HOLD and hold.held_gain_percent == D("27.00")
    # At 141 with support at the 20-day average (130): the 52-week high, 141, is the
    # first target, and the close has reached it.
    at_target = plan(
        levels("141.00", resistance=[], averages={20: D("130.00")}, year_high=D("141.00")),
        today=TODAY,
        held=held,
    )
    assert [t.price for t in at_target.targets] == [D("141.00")]
    assert at_target.verdict is Verdict.TRIM
    # Below the last plan's stop: exit, whatever today's levels say.
    broken = plan(levels("121.00"), today=TODAY, held=held, previous_stop=D("122.00"))
    assert broken.verdict is Verdict.EXIT and "122.00" in broken.reason
    # The last plan's stop only matters for a stock that's held.
    fresh = plan(levels("121.00"), today=TODAY, previous_stop=D("122.00"))
    assert fresh.verdict is not Verdict.EXIT
    loss = plan(
        levels("117.00"), today=TODAY, held=Position("ACME", D("1"), Money(D("130"), "USD"))
    )
    assert loss.held_gain_percent == D("-10.00")


def test_a_made_up_price_is_dropped_from_model_text() -> None:
    allowed = {D("124.00"), D("125.00"), D("122.00"), D("130.00")}
    assert unsupported("Buy near 124 to 125, stop at 122.", allowed) == []
    assert unsupported("It could reach $137.50 soon.", allowed) == ["$137.50"]
    assert unsupported("RSI is 55 and up 12% in 3 weeks.", allowed) == []
    assert unsupported("Revenue grew to 2,400 million.", allowed) == ["2,400"]
    text = "The trend is up. A move to 137.50 is likely. The stop at 122 limits risk."
    assert keep_supported(text, allowed) == "The trend is up. The stop at 122 limits risk."
