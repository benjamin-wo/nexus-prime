"""The month outlook's arithmetic, with no database: net so far, the projection, the user's own
amounts, headroom and shortfall; the words that report them; and how the evals read a figure
out of a reply."""

from datetime import date
from decimal import Decimal

import pytest

from nexus.agent.outlook_text import describe_outlook
from nexus.agent.snapshot import MAX_CHARS, _fit
from nexus.application.cashflow import ExpectedKind
from nexus.application.month_outlook import (
    Adjustment,
    OutlookItem,
    build_outlook,
    parse_adjustment,
    parse_month,
    plain,
    sum_expected,
)
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction
from nexus.domain.money import Money
from nexus.evals.checks import mentions_amount

TODAY = date(2026, 11, 13)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def item(
    day: int, name: str, amount: str | None, kind: ExpectedKind, direction: Direction
) -> OutlookItem:
    return OutlookItem(
        date(2026, 11, day), kind, name, direction, sgd(amount) if amount else None, None
    )


def november(*, moved: str = "0", adjustments: list[Adjustment] | None = None):  # type: ignore[no-untyped-def]
    """The user's case: -1,672.78 so far, payday 4,798.00 ahead, 133.00 of bills."""
    return build_outlook(
        month=date(2026, 11, 1),
        today=TODAY,
        currency="SGD",
        received=sgd("250.00"),
        spent=sgd("1922.78"),
        moved=sgd(moved),
        items=[
            item(20, "Electricity", None, ExpectedKind.BILL, Direction.OUT),
            item(25, "Salary", "4798.00", ExpectedKind.SALARY, Direction.IN),
            item(28, "Singtel", "45.00", ExpectedKind.BILL, Direction.OUT),
            item(30, "Gym", "88.00", ExpectedKind.BILL, Direction.OUT),
        ],
        adjustments=adjustments or [],
    )


def test_the_projection_is_net_so_far_plus_what_is_expected_in_less_what_is_expected_out() -> None:
    o = november()
    assert o.status == "current"
    assert (o.received, o.spent, o.net_so_far) == (sgd("250"), sgd("1922.78"), sgd("-1672.78"))
    assert (o.expected_in, o.expected_out) == (sgd("4798"), sgd("133"))
    assert o.no_amount == ["Electricity"]  # listed, not counted
    assert o.projected_net == sgd("2992.22") == o.net_so_far + o.expected_in - o.expected_out
    assert o.overall == o.projected_net and o.adjustments_total == sgd("0")
    assert (o.headroom, o.shortfall) == (sgd("2992.22"), sgd("0"))


def test_what_the_user_mentions_is_added_by_code_to_the_overall_figure() -> None:
    # "+2308.42 (net from oct) how much leeway do i have to have positive net overall?"
    o = november(adjustments=[parse_adjustment("+2308.42", "net from October", "SGD")])
    assert o.projected_net == sgd("2992.22")
    assert o.adjustments_total == sgd("2308.42")
    assert o.overall == sgd("5300.64") and o.headroom == sgd("5300.64")


def test_several_amounts_and_a_purchase_as_a_negative() -> None:
    o = november(
        adjustments=[
            parse_adjustment("2,308.42", "carried over", "SGD"),
            parse_adjustment("150", "cousin paying back", "SGD"),
            parse_adjustment("-500", "dinner", "SGD"),
        ]
    )
    assert o.adjustments_total == sgd("1958.42")
    assert o.overall == sgd("4950.64")


def test_a_written_sum_is_worked_out_by_code_and_a_bad_one_is_refused() -> None:
    assert parse_adjustment("4000 + 798", "payday", "SGD").amount == sgd("4798")
    assert parse_adjustment("-1,000 / 3", "", "SGD") == Adjustment("adjustment", sgd("-333.33"))
    with pytest.raises(InvalidInput):
        parse_adjustment("about four thousand", "x", "SGD")
    with pytest.raises(InvalidInput):
        parse_adjustment("2 ** 9", "x", "SGD")


def test_below_zero_there_is_a_shortfall_and_no_headroom() -> None:
    o = november(adjustments=[parse_adjustment("-3000", "a holiday", "SGD")])
    assert o.overall == sgd("-7.78")
    assert (o.headroom, o.shortfall) == (sgd("0"), sgd("7.78"))
    assert "Shortfall: 7.78" in describe_outlook(o)


def test_exactly_zero_is_still_positive_net() -> None:
    o = november(adjustments=[parse_adjustment("-2992.22", "all of it", "SGD")])
    assert o.overall == sgd("0") and (o.headroom, o.shortfall) == (sgd("0"), sgd("0"))
    assert "Headroom (the leeway): 0.00" in describe_outlook(o)


def test_money_moved_to_own_wallets_comes_off_the_projection_like_homes_left_to_spend() -> None:
    o = november(moved="1000")
    assert o.projected_net_before_moves == sgd("2992.22")
    assert o.projected_net == sgd("1992.22")
    text = describe_outlook(o)
    assert "Moved to your own wallets" in text and "1,000.00" in text
    assert "Before transfers to your own wallets it is +2,992.22" in text


def test_items_with_no_amount_are_named_once_and_never_counted() -> None:
    sums = sum_expected(
        [
            item(20, "Electricity", None, ExpectedKind.BILL, Direction.OUT),
            item(21, "Electricity", None, ExpectedKind.BILL, Direction.OUT),
            item(25, "Salary", "100", ExpectedKind.SALARY, Direction.IN),
        ],
        "SGD",
    )
    assert (sums.money_in, sums.money_out, sums.no_amount) == (
        sgd("100"),
        sgd("0"),
        ["Electricity"],
    )


def test_the_words_list_each_item_with_its_date_and_state_the_limits() -> None:
    text = describe_outlook(
        november(adjustments=[parse_adjustment("2308.42", "from October", "SGD")])
    )
    for expected in (
        "Outlook for November 2026, as of Fri 13 Nov",
        "- Received: 250.00",
        "- Spent: 1,922.78",
        "- Net so far: -1,672.78 (received less spent)",
        "- Wed 25 Nov Salary (payday) +4,798.00",
        "- Sat 28 Nov Singtel (bill) -45.00",
        "- Fri 20 Nov Electricity (bill) amount not set, not counted",
        "Expected in 4,798.00, out 133.00.",
        "No amount set, so not counted",
        "Projected month-end net: +2,992.22",
        "+2,308.42 (from October)",
        "Overall with those: +5,300.64",
        "Headroom (the leeway): 5,300.64",
        "not forecast",
        "not an account balance",
    ):
        assert expected in text, expected


def test_a_month_that_is_over_has_what_happened_and_no_projection() -> None:
    o = build_outlook(
        month=date(2026, 8, 1),
        today=date(2026, 9, 28),
        currency="SGD",
        received=sgd("5000"),
        spent=sgd("246.78"),
        moved=sgd("0"),
        items=[],
    )
    assert o.status == "past" and o.net_so_far == sgd("4753.22")
    text = describe_outlook(o)
    assert "August 2026, which is over" in text and "Net so far: +4,753.22" in text
    assert "Projected" not in text and "Headroom" not in text and "Still expected" not in text


def test_a_month_with_nothing_scheduled_says_so() -> None:
    o = build_outlook(
        month=date(2026, 11, 1), today=TODAY, currency="SGD",
        received=sgd("0"), spent=sgd("0"), moved=sgd("0"), items=[],
    )  # fmt: skip
    assert "nothing: no bills, tracked subscriptions or payday" in describe_outlook(o)
    assert o.projected_net == sgd("0")


def test_a_future_month_has_a_status_of_its_own() -> None:
    o = build_outlook(
        month=date(2026, 12, 1), today=TODAY, currency="SGD",
        received=sgd("0"), spent=sgd("0"), moved=sgd("0"), items=[],
    )  # fmt: skip
    assert o.status == "future" and o.last_day == date(2026, 12, 31)


def test_a_foreign_item_shows_what_it_costs_in_its_own_currency() -> None:
    usd = OutlookItem(
        date(2026, 11, 20), ExpectedKind.SUBSCRIPTION, "ChatGPT", Direction.OUT,
        sgd("27.00"), Money.of("20", "USD"),
    )  # fmt: skip
    o = build_outlook(
        month=date(2026, 11, 1), today=TODAY, currency="SGD",
        received=sgd("0"), spent=sgd("0"), moved=sgd("0"), items=[usd],
    )  # fmt: skip
    assert "-27.00 (20.00 USD at today's rate)" in describe_outlook(o)
    assert o.expected_out == sgd("27")


def test_amounts_are_shown_as_people_read_them() -> None:
    assert plain(sgd("4798")) == "4,798.00"
    assert plain(sgd("4798"), signed=True) == "+4,798.00"
    assert plain(sgd("-1672.78"), signed=True) == "-1,672.78"
    assert plain(Money.of("1500", "JPY")) == "1,500"


def test_the_month_asked_about() -> None:
    assert parse_month(None, TODAY) == date(2026, 11, 1)
    assert parse_month("2026-08", TODAY) == date(2026, 8, 1)
    assert parse_month("2026-8", TODAY) == date(2026, 8, 1)
    assert parse_month("2027-06", TODAY) == date(2027, 6, 1)
    for bad in ("august", "2026-13", "2026", "2030-01"):
        with pytest.raises(InvalidInput):
            parse_month(bad, TODAY)


@pytest.mark.parametrize(
    "reply",
    [
        "Overall you'd end at +5,300.64.",
        "about 5300.64 in the green",
        "SGD 5,300.64",
        "5300.64.",  # a full stop after it
        "(5,300.64)",
        "short by -5,300.64",  # the sign is ignored
    ],
)
def test_a_figure_is_found_however_the_reply_writes_it(reply: str) -> None:
    assert mentions_amount(reply, "5300.64")


@pytest.mark.parametrize(
    "reply",
    [
        "you have 5,300.65",
        "5,300.6",
        "about 5,301",  # rounded: not the figure
        "about 5,300",
        "15,300.64",  # a different, bigger number
        "2,992.22 and 2,308.42",
        "no figure here",
    ],
)
def test_a_different_figure_is_not_the_one_asked_for(reply: str) -> None:
    assert not mentions_amount(reply, "5300.64")


def test_whole_numbers_and_the_edges_of_the_matching() -> None:
    assert mentions_amount("payday is 4,798", Decimal("4798.00"))
    assert mentions_amount("4798.00", "4,798")
    assert mentions_amount("SGD 4,798.00 on the 25th", "4798.00")
    assert not mentions_amount("on the 25th", "4798.00")
    assert not mentions_amount("14,798.00", "4798.00")
    assert not mentions_amount("4,798.00", "not a number")
    assert not mentions_amount("1.5", "62.13")


def test_the_snapshot_cap_never_cuts_a_part_that_is_kept() -> None:
    month_end = "Expected by month end: in 4,798.00, out 133.00 (payday 25 Nov +4,798.00)."
    parts = [("a" * 900, False), ("b" * 900, False), (month_end, True), ("c" * 900, False)]
    text = _fit(parts)
    assert len(text) <= MAX_CHARS and month_end in text
    assert text.startswith("a" * 900)  # what comes first survives; the tail is cut
    assert not text.endswith("c" * 900)


def test_under_the_cap_nothing_is_cut() -> None:
    assert _fit([("one", False), ("two", True), ("three", False)]) == "one\ntwo\nthree"
    assert _fit([]) == ""
    exact = [("x" * 999, False), ("y" * 1000, False)]  # 999 + 1 + 1000 = the cap
    assert len(_fit(exact)) == MAX_CHARS
    assert _fit([("x" * 999, False), ("y" * 1001, False)]).endswith("…")
