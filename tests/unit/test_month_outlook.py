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
    MonthOutlook,
    OutlookItem,
    Scheduled,
    Spend,
    build_outlook,
    compare_pace,
    parse_adjustment,
    parse_month,
    per_day,
    plain,
    room_per_day,
    scheduled_in,
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
    day: int,
    name: str,
    amount: str | None,
    kind: ExpectedKind,
    direction: Direction,
    *,
    spending: bool | None = None,
) -> OutlookItem:
    """``spending`` defaults to what is usual: money out counts as spending, money in doesn't."""
    counts = direction is Direction.OUT if spending is None else spending
    return OutlookItem(
        date(2026, 11, day), kind, name, direction, sgd(amount) if amount else None, None, counts
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
        sgd("27.00"), Money.of("20", "USD"), True,
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


# --- the budget, with what is still due ------------------------------------------------------


def with_budget(
    items: list[OutlookItem],
    *,
    limit: str | None = "4500",
    spent: str | None = "4126.56",
    received: str = "5000.00",
    month: date = date(2026, 11, 1),
) -> MonthOutlook:
    """The bug's case: a 4,500 budget, 4,126.56 spent against it."""
    return build_outlook(
        month=month, today=TODAY, currency="SGD",
        received=sgd(received), spent=sgd(spent or "0"), moved=sgd("0"), items=items,
        budget_limit=sgd(limit) if limit else None,
        budget_spent=sgd(spent) if spent else None,
    )  # fmt: skip


def bill(name: str, amount: str, *, spending: bool = True) -> OutlookItem:
    return item(20, name, amount, ExpectedKind.BILL, Direction.OUT, spending=spending)


def test_a_bill_still_due_comes_off_the_budget_left_because_paying_it_is_spending() -> None:
    o = with_budget([bill("Electricity", "515.95")])
    assert (o.budget_limit, o.budget_spent) == (sgd("4500"), sgd("4126.56"))
    assert o.budget_left == sgd("373.44")
    assert o.spending_due == sgd("515.95")
    assert o.budget_left_after_due == sgd("-142.51")  # over by 142.51 once it is paid


def test_the_same_bill_that_is_not_spending_leaves_the_budget_alone() -> None:
    o = with_budget([bill("Index fund", "515.95", spending=False)])
    assert o.budget_left == sgd("373.44")
    assert o.spending_due == sgd("0")
    assert o.budget_left_after_due == sgd("373.44")


def test_a_subscription_counts_but_a_move_a_set_aside_and_payday_do_not() -> None:
    o = with_budget(
        [
            item(21, "Netflix", "17.98", ExpectedKind.SUBSCRIPTION, Direction.OUT, spending=True),
            item(22, "Top-up → IBKR", "1000", ExpectedKind.MOVE, Direction.OUT, spending=False),
            item(
                23, "Set aside for Tokyo", "500", ExpectedKind.TRIP, Direction.OUT, spending=False
            ),
            item(25, "Salary", "4798", ExpectedKind.SALARY, Direction.IN, spending=False),
        ]
    )
    assert o.spending_due == sgd("17.98")
    assert o.budget_left_after_due == sgd("355.46")


def test_items_without_an_amount_are_not_in_what_is_due() -> None:
    o = with_budget([bill("Electricity", "515.95"), item(
        21, "Water", None, ExpectedKind.BILL, Direction.OUT, spending=True)])  # fmt: skip
    assert o.spending_due == sgd("515.95") and o.no_amount == ["Water"]


def test_it_says_which_is_tighter_the_budget_or_the_outlook_and_by_how_much() -> None:
    # Received 5,000 less 4,126.56 spent, less the bill: the outlook is +357.49; the budget -142.51.
    o = with_budget([bill("Electricity", "515.95")])
    assert o.overall == sgd("357.49")
    assert (o.tighter, o.tighter_by) == ("budget", sgd("500.00"))
    # With little coming in, the outlook is the lower of the two.
    low = with_budget([bill("Electricity", "100")], received="0.00")
    assert low.budget_left_after_due == sgd("273.44")
    assert low.overall == sgd("-4226.56")
    assert (low.tighter, low.tighter_by) == ("outlook", sgd("4500.00"))
    same = with_budget([bill("Electricity", "100")], received="4400.00")
    assert same.overall == sgd("173.44") and same.budget_left_after_due == sgd("273.44")
    assert (same.tighter, same.tighter_by) == ("outlook", sgd("100.00"))


def test_adjustments_move_the_outlook_side_of_the_comparison() -> None:
    o = build_outlook(
        month=date(2026, 11, 1), today=TODAY, currency="SGD",
        received=sgd("5000"), spent=sgd("4126.56"), moved=sgd("0"),
        items=[bill("Electricity", "515.95")],
        adjustments=[parse_adjustment("-800", "holiday", "SGD")],
        budget_limit=sgd("4500"), budget_spent=sgd("4126.56"),
    )  # fmt: skip
    assert o.overall == sgd("-442.51")
    assert (o.tighter, o.tighter_by) == ("outlook", sgd("300.00"))


def test_without_an_overall_budget_there_are_no_budget_figures() -> None:
    o = with_budget([bill("Electricity", "515.95")], limit=None, spent=None)
    assert (o.budget_limit, o.budget_spent, o.budget_left) == (None, None, None)
    assert (o.spending_due, o.budget_left_after_due) == (None, None)
    assert (o.tighter, o.tighter_by) == (None, None)


def test_a_future_month_has_nothing_spent_and_a_past_month_has_nothing_due() -> None:
    future = with_budget([bill("Rent", "1800")], spent="0", received="0", month=date(2026, 12, 1))
    assert future.status == "future"
    assert (future.budget_left, future.spending_due) == (sgd("4500"), sgd("1800"))
    assert future.budget_left_after_due == sgd("2700")
    past = with_budget([], month=date(2026, 10, 1))
    assert past.status == "past" and past.budget_left == sgd("373.44")
    assert (past.spending_due, past.budget_left_after_due) == (None, None)
    assert (past.tighter, past.tighter_by) == (None, None)


# --- the budget in the words -------------------------------------------------------------------


def test_the_words_for_the_bug_case_say_the_bill_is_in_both_figures() -> None:
    text = describe_outlook(with_budget([bill("Electricity", "515.95")]))
    for expected in (
        "Overall budget: 4,500.00; spent against it 4,126.56; budget left now 373.44.",
        "- Fri 20 Nov Electricity (bill) -515.95 [counts against the budget]",
        "Still due that counts as spending",
        "515.95 (Electricity)",
        "Budget left once they're paid: -142.51 (over by 142.51).",
        "Tighter: the budget, by 500.00",
        "A spending bill still due is in BOTH",
        "Never say it isn't in the budget",
    ):
        assert expected in text, expected


def test_a_bill_that_is_not_spending_is_marked_as_not_counting() -> None:
    text = describe_outlook(with_budget([bill("Index fund", "515.95", spending=False)]))
    assert "Index fund (bill) -515.95 [not counted in the budget]" in text
    assert "counts against the budget" not in text.replace("[not counted in the budget]", "")
    assert "Budget left once they're paid: 373.44." in text and "over by" not in text


def test_without_a_budget_the_words_have_no_budget_lines() -> None:
    text = describe_outlook(with_budget([bill("Electricity", "515.95")], limit=None, spent=None))
    assert "budget" not in text.lower()


def test_a_month_that_is_over_has_the_budget_figures_and_nothing_due() -> None:
    text = describe_outlook(with_budget([], month=date(2026, 10, 1)))
    assert "Overall budget: 4,500.00; spent against it 4,126.56; budget left 373.44." in text
    assert "Still due" not in text and "Tighter" not in text


# --- how much can I spend: the budget room, never the projection ----------------------------------


def payday(amount: str = "4798.00", day: int = 25) -> OutlookItem:
    return item(day, "Salary", amount, ExpectedKind.SALARY, Direction.IN, spending=False)


def budget_month(
    items: list[OutlookItem], adjustments: list[Adjustment] | None = None, **kw: str
) -> MonthOutlook:
    """The bug's case with payday ahead: 4,500 budget, 4,126.56 spent, 5,000 received."""
    return build_outlook(
        month=date(2026, 11, 1), today=TODAY, currency="SGD",
        received=sgd("5000"), spent=sgd("4126.56"), moved=sgd("0"), items=items,
        adjustments=adjustments or [],
        budget_limit=sgd(kw.get("limit", "4500")), budget_spent=sgd("4126.56"),
    )  # fmt: skip


def test_the_budget_room_is_the_budget_left_once_what_is_due_is_paid() -> None:
    o = budget_month([bill("Electricity", "515.95"), payday()])
    assert o.budget_room == o.budget_left_after_due == sgd("-142.51")
    assert o.budget_adjustments == sgd("0")
    # The projection has payday in it; the room does not.
    assert o.projected_net == sgd("5155.49")
    assert o.budget_room != o.projected_net


def test_a_purchase_comes_off_the_budget_room() -> None:
    o = budget_month([payday()], [parse_adjustment("-50", "dinner", "SGD")])
    assert o.budget_left_after_due == sgd("373.44")
    assert o.budget_adjustments == sgd("-50")
    assert o.budget_room == sgd("323.44")


def test_money_expected_in_never_adds_to_the_budget_room() -> None:
    o = budget_month(
        [payday()],
        [
            parse_adjustment("+2308.42", "carried over", "SGD"),
            parse_adjustment("150", "cousin paying back", "SGD"),
        ],
    )
    assert o.adjustments_total == sgd("2458.42")
    assert (o.budget_adjustments, o.budget_room) == (sgd("0"), sgd("373.44"))
    # Mixed: only the purchase counts against the budget.
    mixed = budget_month(
        [payday()],
        [parse_adjustment("+2308.42", "carried over", "SGD"), parse_adjustment("-500", "x", "SGD")],
    )
    assert mixed.adjustments_total == sgd("1808.42")
    assert (mixed.budget_adjustments, mixed.budget_room) == (sgd("-500"), sgd("-126.56"))


def test_without_a_budget_or_for_a_past_month_there_is_no_room() -> None:
    none = with_budget([bill("Electricity", "515.95")], limit=None, spent=None)
    assert (none.budget_room, none.budget_adjustments) == (None, None)
    past = with_budget([], month=date(2026, 10, 1))
    assert (past.budget_room, past.budget_adjustments) == (None, None)
    assert past.pay_not_yet_in == sgd("0") and past.next_pay_day is None
    future = with_budget([bill("Rent", "1800")], spent="0", received="0", month=date(2026, 12, 1))
    assert future.budget_room == sgd("2700")


def test_pay_not_yet_in_is_the_salary_still_expected_and_its_first_day() -> None:
    o = november()
    assert (o.pay_not_yet_in, o.next_pay_day) == (sgd("4798.00"), date(2026, 11, 25))
    two = build_outlook(
        month=date(2026, 11, 1), today=TODAY, currency="SGD",
        received=sgd("0"), spent=sgd("0"), moved=sgd("0"),
        items=[payday("1000", 27), payday("250.50", 21), bill("Rent", "100"),
               item(22, "Bonus", None, ExpectedKind.SALARY, Direction.IN)],
    )  # fmt: skip
    assert (two.pay_not_yet_in, two.next_pay_day) == (sgd("1250.50"), date(2026, 11, 21))
    nothing = with_budget([bill("Electricity", "100")])
    assert (nothing.pay_not_yet_in, nothing.next_pay_day) == (sgd("0"), None)


def test_the_reply_opens_with_the_budget_room_and_says_pay_is_not_counted() -> None:
    text = describe_outlook(budget_month([bill("Electricity", "515.95"), payday()]))
    lines = text.splitlines()
    assert lines[0].startswith("Outlook for November 2026")
    assert lines[1].startswith("Answer for how much can I spend / can I afford / left to spend")
    assert "the budget left once what's due is paid, -142.51 (over by 142.51)." in lines[1]
    assert (
        "Pay not yet received (payday 4,798.00 on 25 Nov) is not counted and is not money to "
        "spend." in lines[1]
    )
    assert lines[2].startswith("The budget has no room: say so plainly")
    assert "already taken off it" not in text
    # The month-end figures are relabelled, so they can't be read as spending room.
    assert "counts pay not yet received, so it is not spending room while a budget is set" in text
    assert "Headroom (month-end cash leeway): 5,155.49" in text
    assert "Headroom (the leeway)" not in text
    assert "Of that, pay not yet received" not in text  # the budget line says it


def test_a_purchase_is_said_to_be_taken_off_and_money_coming_in_not_added() -> None:
    dinner = describe_outlook(budget_month([payday()], [parse_adjustment("-50", "dinner", "SGD")]))
    assert "the budget left once what's due is paid, 323.44." in dinner
    assert "What you asked about (50.00) is already taken off it." in dinner
    assert "The budget has no room" not in dinner
    carry = describe_outlook(budget_month([payday()], [parse_adjustment("2000", "oct", "SGD")]))
    assert "once what's due is paid, 373.44." in carry
    assert "Money you mentioned as coming in is not added to a budget." in carry
    assert "taken off it" not in carry


def test_with_a_budget_and_no_pay_to_come_nothing_is_said_about_pay() -> None:
    text = describe_outlook(budget_month([bill("Electricity", "100")]))
    assert "Pay not yet received" not in text


def test_without_a_budget_the_projection_stays_the_answer_and_names_the_pay_in_it() -> None:
    text = describe_outlook(november())
    assert "Answer for how much can I spend" not in text
    assert "Projected month-end net: +2,992.22" in text
    assert "Headroom (the leeway): 2,992.22" in text
    assert "Of that, pay not yet received: payday 4,798.00 on 25 Nov. Say so in the reply" in text
    assert "this counts your 4,798.00 pay on 25 Nov, not in yet" in text
    assert "Without it" not in text


def test_without_a_budget_and_no_pay_to_come_nothing_extra_is_said() -> None:
    text = describe_outlook(with_budget([bill("Electricity", "100")], limit=None, spent=None))
    assert "pay not yet received" not in text.lower()
    assert "Headroom (the leeway)" in text


def test_a_past_month_reads_as_before() -> None:
    text = describe_outlook(with_budget([], month=date(2026, 10, 1)))
    assert "Answer for how much can I spend" not in text
    assert "pay not yet received" not in text.lower()
    assert "Headroom" not in text and "Projected month-end net" not in text
    assert text.startswith("Outlook for October 2026, which is over.")


# --- per day: days left, the room per day, the pace so far and how they compare ------------------


def pace_month(
    *,
    today: date = TODAY,
    month: date = date(2026, 11, 1),
    spent: str = "1922.78",
    scheduled: str | None = "1817.98",
    names: tuple[str, ...] = ("Rent", "Netflix"),
    limit: str | None = None,
    items: list[OutlookItem] | None = None,
    adjustments: list[Adjustment] | None = None,
) -> MonthOutlook:
    """The seed's November (250.00 in, 1,922.78 out, of which rent and Netflix are 1,817.98),
    with payday and Singtel ahead unless ``items`` says otherwise. A budget is spent as spent."""
    ahead = (
        [payday(), item(28, "Singtel", "45.00", ExpectedKind.BILL, Direction.OUT)]
        if items is None
        else items
    )
    return build_outlook(
        month=month, today=today, currency="SGD", received=sgd("250.00"), spent=sgd(spent),
        moved=sgd("0"), items=ahead, adjustments=adjustments or [],
        budget_limit=sgd(limit) if limit else None,
        budget_spent=sgd(spent) if limit else None,
        scheduled_spent=sgd(scheduled) if scheduled else None, scheduled_names=names,
    )  # fmt: skip


def production_month() -> MonthOutlook:
    """3,475 spent in 19 days and 1,033.79 of budget room over the 11 days left, nothing else."""
    return build_outlook(
        month=date(2026, 11, 1), today=date(2026, 11, 20), currency="SGD",
        received=sgd("0"), spent=sgd("3475"), moved=sgd("0"), items=[],
        budget_limit=sgd("4508.79"), budget_spent=sgd("3475"),
    )  # fmt: skip


def test_days_left_count_today_through_month_end_and_days_elapsed_the_1st_through_today() -> None:
    o = pace_month()
    assert (o.days_left, o.days_elapsed) == (18, 13)  # the 13th to the 30th; the 1st to the 13th
    assert pace_month(today=date(2026, 11, 30)).days_left == 1
    assert pace_month(today=date(2026, 11, 1)).days_elapsed == 1


def test_the_pace_is_everyday_spending_over_the_days_elapsed_leaving_out_scheduled_payments() -> (
    None
):
    o = pace_month()
    assert o.scheduled_spent == sgd("1817.98") and o.scheduled_names == ["Rent", "Netflix"]
    assert o.everyday_spent == sgd("104.80")  # 1,922.78 less rent and Netflix
    assert o.everyday_per_day == sgd("8.06")  # 104.80 / 13 = 8.0615...
    assert o.spent_per_day == sgd("147.91")  # everything: 1,922.78 / 13 = 147.9061...


def test_with_no_scheduled_payments_found_the_pace_is_everything_spent() -> None:
    o = pace_month(scheduled=None)
    assert o.scheduled_spent == sgd("0") and o.scheduled_names == []
    assert o.everyday_per_day == o.spent_per_day == sgd("147.91")
    # Never more than was spent.
    assert pace_month(scheduled="5000").everyday_spent == sgd("0")


def test_without_a_budget_the_headroom_is_the_room_per_day_over_both_counts_of_days() -> None:
    o = pace_month()
    assert o.headroom == sgd("3080.22")  # 250 + 4,798 - 1,922.78 - 45
    assert o.headroom_per_day == sgd("171.12")  # / 18 = 171.1233...
    assert o.headroom_per_day_from_tomorrow == sgd("181.19")  # / 17 = 181.1894...
    assert (o.budget_room_per_day, o.budget_room_per_day_from_tomorrow) == (None, None)


def test_the_seeds_november_gives_the_figures_the_evals_expect() -> None:
    """-1,672.78 so far, 4,798.00 payday and 133.00 of bills ahead: 2,992.22 over 18 or 17 days."""
    o = november()
    assert o.headroom == sgd("2992.22")
    assert (o.headroom_per_day, o.headroom_per_day_from_tomorrow) == (sgd("166.23"), sgd("176.01"))
    assert (o.days_left, o.days_elapsed) == (18, 13)


def test_with_a_budget_the_budget_room_is_the_room_per_day_and_there_is_no_headroom_figure() -> (
    None
):
    o = pace_month(limit="3000", items=[payday()])
    assert o.budget_room == sgd("1077.22")
    assert o.budget_room_per_day == sgd("59.85")  # 1,077.22 / 18 = 59.8455...
    assert o.budget_room_per_day_from_tomorrow == sgd("63.37")  # / 17 = 63.3659...
    assert (o.headroom_per_day, o.headroom_per_day_from_tomorrow) == (None, None)


def test_no_budget_room_is_zero_per_day_never_negative() -> None:
    insurance = item(26, "Insurance", "250", ExpectedKind.BILL, Direction.OUT)
    over = pace_month(limit="2000", items=[payday(), insurance])
    assert over.budget_room == sgd("-172.78")
    assert over.budget_room_per_day == over.budget_room_per_day_from_tomorrow == sgd("0")
    assert (over.room_vs_pace_percent, over.room_vs_pace) == (0, "far_below")
    exactly = pace_month(limit="1922.78", items=[payday()])
    assert exactly.budget_room == sgd("0") and exactly.budget_room_per_day == sgd("0")


def test_a_shortfall_is_no_headroom_and_zero_per_day() -> None:
    o = pace_month(spent="9000", scheduled=None, items=[])
    assert o.shortfall.is_positive and o.headroom == sgd("0")
    assert o.headroom_per_day == o.headroom_per_day_from_tomorrow == sgd("0")


def test_what_you_asked_about_comes_off_the_room_per_day() -> None:
    o = pace_month(
        limit="3000", items=[payday()], adjustments=[parse_adjustment("-180", "x", "SGD")]
    )
    assert o.budget_room == sgd("897.22") and o.budget_room_per_day == sgd("49.85")  # 49.8455...


def test_on_the_last_day_there_is_one_day_left_and_no_from_tomorrow_figure() -> None:
    o = pace_month(today=date(2026, 11, 30), limit="3000", items=[])
    assert o.days_left == 1
    assert o.budget_room_per_day == o.budget_room == sgd("1077.22")
    assert o.budget_room_per_day_from_tomorrow is None
    assert pace_month(today=date(2026, 11, 30), items=[]).headroom_per_day_from_tomorrow is None


def test_a_future_month_spreads_the_room_over_all_its_days_with_no_pace() -> None:
    o = pace_month(month=date(2026, 12, 1), spent="0", scheduled=None, items=[])
    assert (o.days_left, o.days_elapsed) == (31, None)
    assert o.headroom == sgd("250") and o.headroom_per_day == sgd("8.06")  # 250 / 31 = 8.0645...
    assert o.headroom_per_day_from_tomorrow is None  # the month has not begun
    assert (o.spent_per_day, o.everyday_per_day, o.room_vs_pace) == (None, None, None)


def test_a_past_month_has_only_the_pace_over_the_whole_month() -> None:
    o = pace_month(
        month=date(2026, 10, 1), spent="310", scheduled="62", names=("Netflix",), items=[]
    )
    assert (o.days_left, o.days_elapsed) == (None, 31)
    assert o.everyday_per_day == sgd("8.00")  # (310 - 62) / 31
    assert o.spent_per_day == sgd("10.00")
    assert o.scheduled_names == ["Netflix"]
    assert (o.budget_room_per_day, o.headroom_per_day, o.room_vs_pace) == (None, None, None)


def test_the_room_per_day_is_compared_with_the_pace_in_code() -> None:
    # Against a pace of 100.00 a day, the room per day is that many percent of it.
    bands = {"40": "far_below", "70": "below", "100": "about", "150": "above", "250": "far_above"}
    for room_day, band in bands.items():
        assert compare_pace(sgd(room_day), sgd("100")) == (int(room_day), band)
    assert compare_pace(sgd("0"), sgd("100")) == (0, "far_below")
    assert compare_pace(sgd("50"), sgd("0")) is None  # nothing spent: no pace to compare with
    # The edges: 49 is far below, 50 below, 90 and 110 about it, 111 above, 200 far above.
    assert compare_pace(sgd("49.4"), sgd("100")) == (49, "far_below")
    assert compare_pace(sgd("50"), sgd("100")) == (50, "below")
    assert compare_pace(sgd("90"), sgd("100")) == (90, "about")
    assert compare_pace(sgd("110"), sgd("100")) == (110, "about")
    assert compare_pace(sgd("111"), sgd("100")) == (111, "above")
    assert compare_pace(sgd("200"), sgd("100")) == (200, "far_above")


def test_the_production_case_94_a_day_against_a_pace_of_174_is_below_it() -> None:
    o = production_month()
    assert o.budget_room == sgd("1033.79") and o.days_left == 11
    assert o.budget_room_per_day == sgd("93.98")  # 1,033.79 / 11
    assert o.budget_room_per_day_from_tomorrow == sgd("103.38")  # / 10
    assert o.everyday_per_day == sgd("173.75")  # 3,475 / 20, the 1st to the 20th
    assert (o.room_vs_pace_percent, o.room_vs_pace) == (54, "below")


def test_per_day_rounds_to_the_currencys_minor_unit_halves_up() -> None:
    assert per_day(sgd("100"), 8) == sgd("12.50")
    assert per_day(sgd("0.05"), 2) == sgd("0.03")  # 0.025 up
    assert per_day(Money.of("1000", "JPY"), 3) == Money.of("333", "JPY")
    assert room_per_day(sgd("-5"), 3) == sgd("0")


# --- per day: the words -----------------------------------------------------------------------


def test_the_words_give_the_room_per_day_both_ways_the_pace_and_the_comparison() -> None:
    text = describe_outlook(november())
    assert "Per day, 13 Nov to 30 Nov: 18 days left counting today." in text
    assert (
        "Headroom per day: 166.23 (2,992.22 over 18 days), or 176.01 from tomorrow (17 days)."
    ) in text
    assert "This counts pay not yet received (payday 4,798.00 on 25 Nov)" in text
    # No scheduled payment found: the pace is everything spent over the 13 days.
    assert "Pace so far, everyday spending: 147.91 a day (1,922.78 over 13 days)." in text
    # Without a budget the room counts pay not yet in, so it is never set against the pace.
    assert "Room per day against that pace" not in text
    assert text.index("Headroom (the leeway)") < text.index("Per day, 13 Nov")


def test_the_pace_names_the_scheduled_payments_it_leaves_out() -> None:
    text = describe_outlook(pace_month())
    assert (
        "Pace so far, everyday spending: 8.06 a day (104.80 over 13 days, leaving out 1,817.98 of "
        "scheduled payments: Rent, Netflix. Counting those too it is 147.91 a day, but that is "
        "not the figure to compare with)."
    ) in text
    assert "Room per day against that pace" not in text  # no budget: see above


def test_a_budget_room_below_the_pace_is_said_to_be_tight() -> None:
    text = describe_outlook(production_month())
    assert "Per day, 20 Nov to 30 Nov: 11 days left counting today." in text
    assert (
        "Budget room per day: 93.98 (1,033.79 over 11 days), or 103.38 from tomorrow (10 days)."
    ) in text
    assert "Pace so far, everyday spending: 173.75 a day (3,475.00 over 20 days)." in text
    assert "Room per day against that pace: 54% of it, below your pace so far: tight." in text
    # With a budget the block follows the budget room line, before the month's figures.
    assert text.index("Answer for how much can I spend") < text.index("Per day,")
    assert text.index("Per day,") < text.index("So far (")


def test_with_no_budget_room_it_says_no_room_and_gives_no_per_day_figure() -> None:
    insurance = item(26, "Insurance", "250", ExpectedKind.BILL, Direction.OUT)
    text = describe_outlook(pace_month(limit="2000", items=[payday(), insurance]))
    assert "- No budget room (it is -172.78), so nothing to spend per day" in text
    assert "never a per-day figure, and none from the month-end net" in text
    assert "Budget room per day" not in text and "Room per day against that pace" not in text


def test_a_future_month_in_words_has_the_room_per_day_and_no_pace() -> None:
    text = describe_outlook(
        pace_month(month=date(2026, 12, 1), spent="0", scheduled=None, items=[])
    )
    assert "Per day, over the month's 31 days." in text
    assert "Headroom per day: 8.06 (250.00 over 31 days)." in text
    assert "Pace" not in text and "from tomorrow" not in text


def test_a_past_month_in_words_has_only_the_pace() -> None:
    text = describe_outlook(
        pace_month(
            month=date(2026, 10, 1), spent="310", scheduled="62", names=("Netflix",), items=[]
        )
    )
    assert (
        "Per day: Pace over the whole month, everyday spending: 8.00 a day (248.00 over 31 days, "
        "leaving out 62.00 of scheduled payments: Netflix."
    ) in text
    assert "days left" not in text and "Headroom" not in text and "Room per day" not in text


# --- finding scheduled payments in the month's spending ---------------------------------------


def spend(name: str | None, amount: str) -> Spend:
    return Spend(name, sgd(amount), sgd(amount))


def test_a_scheduled_payment_is_found_in_an_expense_of_the_same_amount_and_a_shared_name() -> None:
    planned = [Scheduled("Rent", sgd("1800"), 1), Scheduled("Netflix", sgd("17.98"), 1)]
    spends = [
        spend("NTUC FairPrice", "76.40"),
        spend("Rent", "1800.00"),
        spend("Netflix.com 8829", "17.98"),
    ]
    assert scheduled_in(planned, spends, "SGD") == (sgd("1817.98"), ["Rent", "Netflix"])


def test_a_different_amount_or_name_or_no_name_is_not_a_scheduled_payment() -> None:
    planned = [Scheduled("Rent", sgd("1800"), 1)]
    for other in (spend("Rent", "1750.00"), spend("Landlord", "1800.00"), spend(None, "1800.00")):
        assert scheduled_in(planned, [other], "SGD") == (sgd("0"), [])


def test_each_expense_is_used_once_and_a_payment_only_as_often_as_it_falls_due() -> None:
    gym = [Scheduled("Gym", sgd("88"), 1)]
    twice = [spend("Gym", "88.00"), spend("Gym", "88.00")]
    assert scheduled_in(gym, twice, "SGD") == (sgd("88"), ["Gym"])
    weekly = [Scheduled("Gym", sgd("88"), 2), Scheduled("Gym pass", sgd("88"), 1)]
    assert scheduled_in(weekly, [*twice, spend("Gym", "88.00")], "SGD")[0] == sgd("264")
    assert scheduled_in(weekly, twice, "SGD") == (sgd("176"), ["Gym"])


def test_a_found_payment_counts_at_its_home_currency_value() -> None:
    usd = Spend("OpenAI ChatGPT", Money.of("20", "USD"), sgd("27.00"))
    planned = [Scheduled("OpenAI ChatGPT", Money.of("20", "USD"), 1)]
    assert scheduled_in(planned, [usd], "SGD") == (sgd("27.00"), ["OpenAI ChatGPT"])
