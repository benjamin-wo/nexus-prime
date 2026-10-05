"""A plan's numbers and game plan from made-up levels, and the check that drops any
price a model made up. Every ticker and figure here is made up."""

from datetime import date
from decimal import Decimal

from nexus.domain.investments import Position
from nexus.domain.levels import Levels
from nexus.domain.money import Money
from nexus.domain.plans import StepKind, Verdict, keep_supported, plan, playbook, unsupported

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


def held(cost: str = "100.00") -> Position:
    return Position("ACME", D("10"), Money(D(cost), "USD"))


def test_a_stock_above_its_buy_zone_waits_for_a_dip() -> None:
    p = plan(levels("127.00"), today=TODAY)
    # The nearest support below 127 is the 20-day average at 124.
    assert (p.entry_low, p.entry_high, p.entry_why) == (D("124.00"), D("125.00"), "20-day average")
    assert p.stop == D("122.00")  # one typical day's move below the support
    assert p.risk == D("2.50")  # from mid-zone 124.50
    # 130 is 2.2 times the risk and 140 is 6.2 times: both worth it.
    assert [(t.price, t.reward_risk) for t in p.targets] == [
        (D("130.00"), D("2.20")),
        (D("140.00"), D("6.20")),
    ]
    assert p.verdict is Verdict.WAIT and p.trail_to == D("124.50")
    assert p.valid_until == date(2026, 10, 12)
    steps = playbook(p)
    assert [s.kind for s in steps] == [
        StepKind.BUY,
        StepKind.TAKE_PROFIT,
        StepKind.CUT_LOSS,
        StepKind.TRAIL,
        StepKind.REVIEW,
    ]
    assert steps[0].price == "124.00 to 125.00" and steps[0].change == ["-1.6%"]
    assert (
        steps[0].detail
        == "Buy at 124.00 to 125.00, on a dip to the 20-day average (1.6% below today)."
    )
    assert steps[1].detail == (
        "Sell part at 130.00 (+2.4%, resistance), and the rest at 140.00 (+10.2%)."
    )
    assert steps[1].change == ["+2.4%", "+10.2%"]
    assert steps[2].detail.startswith("Sell if a day closes below 122.00 (-3.9%), a typical day")
    assert steps[4].title == "Valid until 12 Oct"


def test_in_the_zone_and_earnings_inside_the_window() -> None:
    p = plan(levels("124.60"), today=TODAY, earnings=date(2026, 10, 8))
    assert p.verdict is Verdict.IN_ZONE
    assert p.entry_high == D("124.60")  # the zone stops at the close
    assert p.earnings_in_window == date(2026, 10, 8)
    assert "Earnings are on 08 Oct" in playbook(p)[-1].detail
    later = plan(levels("124.60"), today=TODAY, earnings=date(2026, 11, 30))
    assert later.earnings_in_window is None


def test_every_plan_has_a_stop_and_targets_even_without_a_trade() -> None:
    tight = plan(levels("127.00", resistance=[D("129.00")], year_high=D("129.20")), today=TODAY)
    assert tight.verdict is Verdict.NO_TRADE and "Resistance at 129.00" in tight.reason
    assert tight.stop == D("122.00")
    # Measured from the risk, since nothing overhead is far enough.
    assert [(t.price, t.why) for t in tight.targets] == [
        (D("129.50"), "2 times the risk"),
        (D("132.00"), "3 times the risk"),
    ]
    falling = plan(levels("80.00", averages={}, support=[], resistance=[]), today=TODAY)
    assert falling.verdict is Verdict.NO_TRADE and "no support below" in falling.reason
    assert falling.stop == D("76.00")  # two typical days' moves below the close
    assert [t.price for t in falling.targets] == [D("88.00"), D("92.00")]
    assert playbook(falling)[0].detail.startswith("Not yet: wait for it to stop falling")


def test_a_held_stock_below_all_its_supports_still_gets_a_full_game_plan() -> None:
    # Fallen under its swing lows and both averages: before, this came back as a bare
    # "hold" with no stop or target.
    p = plan(levels("100.00"), today=TODAY, held=held("90.00"))
    assert p.verdict is Verdict.HOLD and "fallen below its recent supports" in p.reason
    assert p.stop == D("96.00") and p.entry_low is None
    # The averages it fell through are where it may stall on the way back up.
    assert [(t.price, t.why) for t in p.targets] == [
        (D("110.00"), "50-day average"),
        (D("124.00"), "20-day average"),
    ]
    steps = playbook(p)
    assert [s.kind for s in steps] == [
        StepKind.TAKE_PROFIT,
        StepKind.CUT_LOSS,
        StepKind.TRAIL,
        StepKind.REVIEW,
    ]
    assert steps[0].detail == (
        "Sell part at 110.00 (+10.0%, 50-day average), and the rest at 124.00 (+24.0%). "
        "That's +22.2% on what you paid."
    )
    assert steps[1].detail.endswith("Against what you paid that's +6.7%.")
    assert steps[2].detail.startswith("Once it closes above 110.00, raise your stop to 100.00")
    assert steps[3].title == "Hold until 12 Oct"


def test_a_held_stock_holds_adds_trims_or_exits() -> None:
    hold = plan(levels("127.00"), today=TODAY, held=held())
    assert hold.verdict is Verdict.HOLD and hold.held_gain_percent == D("27.00")
    assert "above support at the 20-day average" in hold.reason
    # For a holder the nearest ceiling is where to sell part, however close.
    assert [t.price for t in hold.targets] == [D("130.00"), D("140.00")]
    steps = playbook(hold)
    assert steps[-2].kind is StepKind.BUY and steps[-2].title == "Add more"
    assert steps[-2].detail.startswith("Add more at 124.00 to 125.00, on a dip to the 20-day")
    trim = plan(levels("131.00"), today=TODAY, held=held(), previous_target=D("130.00"))
    assert trim.verdict is Verdict.TRIM and "130.00" in trim.reason
    # Below the last plan's stop: exit, whatever today's levels say.
    broken = plan(levels("121.00"), today=TODAY, held=held(), previous_stop=D("122.00"))
    assert broken.verdict is Verdict.EXIT and "122.00" in broken.reason
    # The last plan only matters for a stock that's held.
    fresh = plan(levels("121.00"), today=TODAY, previous_stop=D("122.00"))
    assert fresh.verdict is not Verdict.EXIT
    loss = plan(levels("117.00"), today=TODAY, held=held("130"))
    assert loss.held_gain_percent == D("-10.00")


def test_a_made_up_price_is_dropped_from_model_text() -> None:
    allowed = {D("124.00"), D("125.00"), D("122.00"), D("130.00")}
    assert unsupported("Buy near 124 to 125, stop at 122.", allowed) == []
    assert unsupported("It could reach $137.50 soon.", allowed) == ["$137.50"]
    assert unsupported("RSI is 55 and up 12% in 3 weeks.", allowed) == []
    assert unsupported("Revenue grew to 2,400 million.", allowed) == ["2,400"]
    text = "The trend is up. A move to 137.50 is likely. The stop at 122 limits risk."
    assert keep_supported(text, allowed) == "The trend is up. The stop at 122 limits risk."
    # Names with numbers in them aren't prices.
    assert unsupported("It beat the S&P 500 and sits above its 200-day average.", allowed) == []
    assert unsupported("Earnings are on 27 Oct 2026, or October 27, 2026.", allowed) == []
    assert unsupported("It could hit 2026 by Oct.", allowed) == ["2026"]  # a price, not a date


def test_a_stock_far_above_its_zone_still_gets_targets_above_today() -> None:
    # At its 52-week high, well above the 20-day average it should dip to. Before, the
    # targets were 2 and 3 times the risk from the buy zone: below today's close.
    p = plan(
        levels("172.15", averages={20: D("163.00"), 50: D("150.00")}, support=[],
               resistance=[], year_high=D("172.15")),
        today=TODAY,
    )  # fmt: skip
    assert p.verdict is Verdict.WAIT and p.entry_high is not None
    assert p.entry_high < D("172.15")
    assert p.targets and all(t.price > D("172.15") for t in p.targets)
    # Still multiples of the risk from the buy zone, the nearest ones above today.
    assert [t.why for t in p.targets] == [f"{t.reward_risk:g} times the risk" for t in p.targets]
    assert all(t.reward_risk >= 2 for t in p.targets)
