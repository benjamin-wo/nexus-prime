"""What the user saved, month by month: the arithmetic (net, saving rate, averages, best and
worst, the guide), which months are covered, and the words that report them. No database."""

from datetime import date
from decimal import Decimal

from nexus.agent.outlook_text import describe_money_history
from nexus.application.money_history import (
    MonthFigures,
    build_money_history,
    clamp_months,
    months_covered,
)
from nexus.domain.money import Money

TODAY = date(2026, 11, 13)
FIRST = date(2026, 8, 3)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def month(
    number: int, received: str, spent: str, moved: str = "0", *, year: int = 2026
) -> MonthFigures:
    return MonthFigures(date(year, number, 1), sgd(received), sgd(spent), sgd(moved), [])


def history(*figures: MonthFigures, salary: str | None = "4798.00", first: date | None = FIRST):  # type: ignore[no-untyped-def]
    return build_money_history(
        today=TODAY,
        currency="SGD",
        first_day=first,
        figures=figures,
        usual_salary=sgd(salary) if salary else None,
    )


# August and September in full, nothing in October, twelve days of November.
EVALS = (
    month(8, "5000.00", "246.78"),
    month(9, "5000.00", "460.03"),
    month(10, "0", "0"),
    month(11, "250.00", "1922.78"),
)


def test_each_month_is_received_less_spent_and_a_rate_of_what_was_received() -> None:
    h = history(*EVALS)
    august, september, _october, current = h.months
    assert (august.received, august.spent, august.net) == (
        sgd("5000"),
        sgd("246.78"),
        sgd("4753.22"),
    )
    assert august.savings_rate == Decimal("4753.22") / Decimal("5000.00")
    assert september.net == sgd("4539.97")
    assert [m.partial for m in h.months] == [False, False, False, True]
    assert (current.net, current.partial) == (sgd("-1672.78"), True)


def test_the_summary_is_over_full_months_with_entries_only() -> None:
    h = history(*EVALS)
    s = h.summary
    assert s is not None
    # October (nothing logged) and November (part-way) are not in it.
    assert s.months == 2
    assert s.average_net == sgd("4646.60")  # (4,753.22 + 4,539.97) / 2 = 4,646.595, half up
    assert (s.average_received, s.average_spent) == (sgd("5000.00"), sgd("353.41"))
    assert (s.best.month, s.worst.month) == (date(2026, 8, 1), date(2026, 9, 1))
    # Total net over total received: (4,753.22 + 4,539.97) / 10,000.00.
    assert s.average_savings_rate == Decimal("9293.19") / Decimal("10000.00")


def test_a_month_with_no_income_has_no_rate_but_counts_in_the_averages() -> None:
    h = history(month(8, "5000.00", "200.00"), month(9, "0", "300.00"), month(11, "0", "0"))
    september = h.months[1]
    assert september.savings_rate is None and september.net == sgd("-300.00")
    s = h.summary
    assert s is not None and s.months == 2
    assert s.average_net == sgd("2250.00")  # (4,800 - 300) / 2
    assert s.average_savings_rate == Decimal("4500") / Decimal("5000")  # the pooled rate
    assert (s.best.month, s.worst.month) == (date(2026, 8, 1), date(2026, 9, 1))


def test_a_year_of_months_without_income_has_no_average_rate() -> None:
    h = history(month(9, "0", "100.00"), month(10, "0", "50.00"), month(11, "0", "0"))
    s = h.summary
    assert s is not None and s.average_savings_rate is None and s.average_net == sgd("-75.00")


def test_moved_to_savings_is_shown_and_does_not_change_the_net() -> None:
    h = history(month(9, "5000.00", "460.03", "1000.00"), month(11, "0", "0"))
    september = h.months[0]
    assert september.moved == sgd("1000") and september.net == sgd("4539.97")
    assert "of that, 1,000.00 moved to your own wallets (savings or investments)" in (
        describe_money_history(h)
    )


def test_a_month_with_only_a_move_is_a_logged_month() -> None:
    h = history(month(9, "0", "0", "300.00"), month(11, "0", "0"))
    assert h.months[0].logged and h.summary is not None and h.summary.months == 1


def test_fewer_than_two_full_months_is_said_plainly() -> None:
    h = history(month(10, "4000.00", "1000.00"), month(11, "100.00", "50.00"))
    assert h.summary is not None and h.summary.months == 1
    text = describe_money_history(h)
    assert "Only 1 full month (Oct 2026), so there is no average or pattern" in text
    assert "net +3,000.00" in text
    assert "Best month" not in text


def test_with_no_full_month_there_is_no_summary_and_no_guide() -> None:
    h = history(month(11, "100.00", "50.00"), first=date(2026, 11, 2))
    assert h.summary is None and h.guide is None
    text = describe_money_history(h)
    assert "No full month with entries yet" in text
    assert "- Nov 2026 so far" in text and "Over the" not in text


def test_the_guide_has_the_users_own_figures_and_the_benchmark() -> None:
    h = history(*EVALS)
    g = h.guide
    assert g is not None
    assert g.average_spent == sgd("353.41") and g.usual_salary == sgd("4798.00")
    assert g.benchmark == sgd("959.60")  # 20% of 4,798.00
    assert g.average_net_share_of_salary == Decimal("4646.60") / Decimal("4798.00")


def test_without_a_usual_salary_the_guide_has_no_salary_figures() -> None:
    h = history(*EVALS, salary=None)
    g = h.guide
    assert g is not None and (g.usual_salary, g.benchmark, g.average_net_share_of_salary) == (
        None,
        None,
        None,
    )
    text = describe_money_history(h)
    assert "average spent 353.41 a month; no usual salary is set" in text
    assert "20.0%" not in text


def test_the_text_lists_every_figure_and_says_the_sums_are_done() -> None:
    text = describe_money_history(history(*EVALS))
    for expected in (
        "Savings history as of Fri 13 Nov 2026. All amounts in SGD",
        "quote them, don't redo the sums",
        "The ledger starts on 3 Aug 2026",
        "- Aug 2026: received 5,000.00, spent 246.78, net +4,753.22 (received less spent), "
        "saving rate 95.1%",
        "- Sep 2026: received 5,000.00, spent 460.03, net +4,539.97 (received less spent), "
        "saving rate 90.8%",
        "- Oct 2026: nothing logged (a gap in the ledger, not counted in the averages)",
        # A part-month shows its figures, but no rate.
        "- Nov 2026 so far (this month is not over: left out of the averages): received "
        "250.00, spent 1,922.78, net -1,672.78 (received less spent)\n",
        "Over the 2 full months with entries (Aug 2026 to Sep 2026): average net +4,646.60 a "
        "month (received 5,000.00, spent 353.41 on average); saving rate 92.9% (their total "
        "net over total received). Best month Aug 2026, net +4,753.22; worst month Sep 2026, "
        "net +4,539.97.",
        "average spent 353.41 a month; usual salary 4,798.00; 20.0% of it 959.60 (a common rule "
        "of thumb, to set beside their own figures); their average net is 96.8% of the usual "
        "salary.",
    ):
        assert expected in text, expected
    assert "-669" not in text


def test_a_month_with_no_income_is_worded_so() -> None:
    text = describe_money_history(history(month(9, "0", "300.00"), month(10, "0", "50.00")))
    assert "net -300.00 (received less spent), no income, so no saving rate" in text
    assert "no income in them, so no saving rate" in text


def test_a_foreign_amount_with_no_rate_is_named_in_its_month() -> None:
    figures = MonthFigures(
        date(2026, 10, 1), sgd("1000"), sgd("13"), sgd("0"), [Money.of("20", "GBP")]
    )
    text = describe_money_history(history(figures, month(11, "0", "0")))
    assert "left out, no exchange rate: 20.00 GBP" in text


def test_with_nothing_logged_there_is_no_history() -> None:
    h = history(first=None)
    assert h.months == [] and h.summary is None
    assert "Nothing is logged yet" in describe_money_history(h)


def test_the_months_covered_start_at_the_first_entry_and_end_with_this_month() -> None:
    assert months_covered(TODAY, FIRST, 6) == [date(2026, m, 1) for m in (8, 9, 10, 11)]
    # The last 2 full months and this one.
    assert months_covered(TODAY, date(2020, 1, 1), 2) == [date(2026, m, 1) for m in (9, 10, 11)]
    # A first entry this month: just this month. None, or one ahead: nothing.
    assert months_covered(TODAY, date(2026, 11, 2), 6) == [date(2026, 11, 1)]
    assert months_covered(TODAY, None, 6) == []
    assert months_covered(TODAY, date(2026, 12, 2), 6) == []


def test_the_months_cross_a_year_end_and_are_capped_at_twelve() -> None:
    found = months_covered(date(2026, 2, 10), date(2020, 1, 1), 12)
    assert len(found) == 13 and found[0] == date(2025, 2, 1) and found[-1] == date(2026, 2, 1)
    assert len(months_covered(TODAY, date(2020, 1, 1), 99)) == 13
    assert (clamp_months(0), clamp_months(6), clamp_months(99)) == (1, 6, 12)
