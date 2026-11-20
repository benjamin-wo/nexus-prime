"""The words for ``month_outlook``, ``money_history`` and ``calculate``: every figure comes from
code, and the text says which, so the model quotes them and does no sums of its own."""

from decimal import ROUND_HALF_UP, Decimal

from nexus.application.cashflow import ExpectedKind
from nexus.application.money_history import BENCHMARK_RATE, MoneyHistory, MonthSaving
from nexus.application.month_outlook import MonthOutlook, OutlookItem, plain
from nexus.domain.calc import Calculation
from nexus.domain.ledger import Direction
from nexus.domain.money import Money


def abs_money(m: Money) -> Money:
    return -m if m < Money.zero(m.currency) else m


KIND_WORDS = {
    ExpectedKind.BILL: "bill",
    ExpectedKind.MOVE: "move to your own wallet",
    ExpectedKind.SUBSCRIPTION: "subscription",
    ExpectedKind.SALARY: "payday",
    ExpectedKind.TRIP: "set aside for a trip",
}


def item_line(item: OutlookItem, *, budget: bool = False) -> str:
    """With ``budget``, money out says whether it will count against the overall budget."""
    if item.amount is None:
        amount = "amount not set, not counted"
    else:
        sign = "+" if item.direction is Direction.IN else "-"
        amount = f"{sign}{plain(item.amount)}"
        if item.original is not None:
            amount += f" ({item.original} at today's rate)"
    line = f"- {item.day:%a %-d %b} {item.name} ({KIND_WORDS[item.kind]}) {amount}"
    if budget and item.amount is not None and item.direction is Direction.OUT:
        line += " [counts against the budget]" if item.spending else " [not counted in the budget]"
    return line


def over_by(amount: Money) -> str:
    return f" (over by {plain(abs_money(amount))})" if amount < Money.zero(amount.currency) else ""


def pay_phrase(o: MonthOutlook) -> str:
    """ "payday 4,798.00 on 25 Nov": the pay still to come (a total, with the first date, if
    there is more than one)."""
    pays = [
        i
        for i in o.items
        if i.kind is ExpectedKind.SALARY and i.direction is Direction.IN and i.amount is not None
    ]
    day = pay_day(o) if o.next_pay_day else "later this month"
    if len(pays) > 1:
        return f"pay {plain(o.pay_not_yet_in)} in all, the first on {day}"
    return f"payday {plain(o.pay_not_yet_in)} on {day}"


def pay_day(o: MonthOutlook) -> str:
    return f"{o.next_pay_day:%-d %b}" if o.next_pay_day else "payday"


def budget_answer(o: MonthOutlook) -> list[str]:
    """The line that answers how much can I spend, with a budget: the budget room, which never
    counts pay that hasn't come in. Empty without one, or for a month already over."""
    if o.budget_room is None or o.budget_adjustments is None:
        return []
    out = [
        "Answer for how much can I spend / can I afford / left to spend / budget left: the budget "
        f"left once what's due is paid, {plain(o.budget_room)}{over_by(o.budget_room)}."
    ]
    if o.pay_not_yet_in.is_positive:
        out[0] += (
            f" Pay not yet received ({pay_phrase(o)}) is not counted and is not money to spend."
        )
    if o.budget_adjustments < Money.zero(o.currency):
        out[0] += (
            f" What you asked about ({plain(abs_money(o.budget_adjustments))}) is already taken "
            "off it."
        )
    if any(a.amount.is_positive for a in o.adjustments):
        out[0] += " Money you mentioned as coming in is not added to a budget."
    if o.budget_room < Money.zero(o.currency) or o.budget_room.is_zero:
        out.append("The budget has no room: say so plainly, whatever the month-end net says.")
    elif o.overall < o.budget_room:
        out.append(
            f"The month-end net is lower still ({plain(o.overall, signed=True)}): say so too."
        )
    return out


def days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


COMPARISONS = {
    "far_below": "less than half your pace so far: tight",
    "below": "below your pace so far: tight",
    "about": "about your pace so far",
    "above": "above your pace so far",
    "far_above": "more than double your pace so far",
}


def pace_line(o: MonthOutlook) -> str | None:
    """How fast everyday spending has gone: leaves out the scheduled payments found in it."""
    if o.everyday_per_day is None or o.spent_per_day is None or o.days_elapsed is None:
        return None
    when = "over the whole month" if o.status == "past" else "so far"
    line = (
        f"Pace {when}, everyday spending: {plain(o.everyday_per_day)} a day "
        f"({plain(o.everyday_spent)} over {days(o.days_elapsed)}"
    )
    if o.scheduled_spent.is_positive:
        line += (
            f", leaving out {plain(o.scheduled_spent)} of scheduled payments: "
            f"{', '.join(o.scheduled_names)}. Counting those too it is {plain(o.spent_per_day)} "
            "a day, but that is not the figure to compare with"
        )
    return line + "). Compare only with this pace, never with a figure of your own."


def per_day_lines(o: MonthOutlook) -> list[str]:
    """The Per day block: the room per day (with a budget, the budget room; without, the
    headroom), the pace so far and how they compare, every figure from code. Empty for a month
    already over without a pace to give."""
    pace = pace_line(o)
    if o.status == "past":
        return [f"Per day: {pace}"] if pace else []
    if o.days_left is None:
        return []
    budget = o.budget_room is not None
    room, day = (
        (o.budget_room, o.budget_room_per_day) if budget else (o.headroom, o.headroom_per_day)
    )
    tomorrow = o.budget_room_per_day_from_tomorrow if budget else o.headroom_per_day_from_tomorrow
    if room is None or day is None:
        return []
    if o.status == "current":
        left = f"{days(o.days_left)} left counting today"
        head = f"Per day, {o.today:%-d %b} to {o.last_day:%-d %b}: {left}."
    else:
        left = f"{days(o.days_left)}"
        head = f"Per day, over the month's {left}."
    what = "budget room" if budget else "headroom"
    if not day.is_positive:
        out = [
            head,
            f"- No {what} (it is {plain(room)}), so nothing to spend per day: say so plainly, "
            "never a per-day figure, and none from the month-end net.",
        ]
    else:
        text = (
            f"- {what.capitalize()} per day: {plain(day)} ({plain(room)} over {days(o.days_left)})"
        )
        if tomorrow is not None and o.days_left > 1:
            text += f", or {plain(tomorrow)} from tomorrow ({days(o.days_left - 1)})"
        out = [head, text + "."]
        if not budget and o.pay_not_yet_in.is_positive:
            out[1] += (
                f" This counts pay not yet received ({pay_phrase(o)}): say so, it is not money "
                "you have today."
            )
    if pace:
        out.append("- " + pace)
    if day.is_positive and o.room_vs_pace is not None and o.room_vs_pace_percent is not None:
        share = "" if o.room_vs_pace == "far_above" else f"{o.room_vs_pace_percent}% of it, "
        out.append(f"- Room per day against that pace: {share}{COMPARISONS[o.room_vs_pace]}.")
    return out


def describe_budget(o: MonthOutlook) -> list[str]:
    """The overall budget's lines; nothing without one. Every figure is a field of ``o``."""
    if o.budget_limit is None or o.budget_spent is None or o.budget_left is None:
        return []
    now = "left" if o.status == "past" else "left now"
    out = [
        f"Overall budget: {plain(o.budget_limit)}; spent against it {plain(o.budget_spent)}; "
        f"budget {now} {plain(o.budget_left)}{over_by(o.budget_left)}."
    ]
    if o.spending_due is None or o.budget_left_after_due is None or o.tighter_by is None:
        return out
    names = [
        i.name
        for i in o.items
        if i.spending and i.direction is Direction.OUT and i.amount is not None
    ]
    out.append(
        "Still due that counts as spending (bills that are spending and subscriptions; payday, "
        "moves to your own wallets and trip set-asides don't): "
        f"{plain(o.spending_due)}"
        + (f" ({', '.join(dict.fromkeys(names))})" if names else "")
        + f". Budget left once they're paid: {plain(o.budget_left_after_due)}"
        f"{over_by(o.budget_left_after_due)}."
    )
    if o.tighter_by.is_zero:
        out.append(f"Tighter: neither, both are {plain(o.overall, signed=True)}.")
    else:
        who = "the budget" if o.tighter == "budget" else "the month's money movement"
        out.append(
            f"Tighter: {who}, by {plain(o.tighter_by)} (budget left once they're paid "
            f"{plain(o.budget_left_after_due)} against {plain(o.overall, signed=True)} "
            "projected net)."
        )
    out.append(
        "These measure different things: the projected net (Home's left to spend) is cash "
        "movement for the month and counts pay not yet received; budget left once they're paid "
        "is what the budget allows after what is due, and is the one that says how much you can "
        "spend. A spending bill still due is in BOTH: in the projected net as expected "
        "out, and in the budget's spent once it is paid. Never say it isn't in the budget."
    )
    return out


def describe_outlook(o: MonthOutlook) -> str:
    name = f"{o.month:%B %Y}"
    out: list[str] = []
    if o.status == "past":
        out.append(
            f"Outlook for {name}, which is over. All amounts in {o.currency}, worked out "
            "exactly in code: quote them, don't redo the sums."
        )
        out.append(f"What happened in {name}:")
    else:
        out.append(
            f"Outlook for {name}, as of {o.today:%a %-d %b}. All amounts in {o.currency}, "
            "worked out exactly in code: quote them, don't redo the sums."
        )
        out += budget_answer(o)
        if o.budget_room is not None:
            out += per_day_lines(o)
        if o.status == "current":
            out.append(f"So far ({o.month:%-d %b} to {o.today:%-d %b}):")
        else:
            out.append(f"{name} hasn't started; anything logged ahead of time:")
    out += [
        f"- Received: {plain(o.received)}",
        f"- Spent: {plain(o.spent)}",
        f"- Net so far: {plain(o.net_so_far, signed=True)} (received less spent)",
    ]
    if not o.moved.is_zero:
        out.append(
            f"- Moved to your own wallets (savings or investments; not spending): {plain(o.moved)}"
        )
    if o.unconverted:
        out.append("- Left out, no exchange rate: " + ", ".join(str(m) for m in o.unconverted))

    if o.status != "past":
        start = max(o.month, o.today)
        out.append(f"Still expected, {start:%-d %b} to {o.last_day:%-d %b}:")
        out += [item_line(i, budget=o.budget_left is not None) for i in o.items] or [
            "- nothing: no bills, tracked subscriptions or payday fall in it"
        ]
        out.append(f"Expected in {plain(o.expected_in)}, out {plain(o.expected_out)}.")
        if o.no_amount:
            out.append(
                "No amount set, so not counted (the totals are too low by what they cost): "
                + ", ".join(o.no_amount)
                + "."
            )
        terms = (
            f"net so far {plain(o.net_so_far, signed=True)} + expected in {plain(o.expected_in)} "
            f"- expected out {plain(o.expected_out)}"
        )
        if not o.moved.is_zero:
            terms += f" - moved to your wallets {plain(o.moved)}"
        label = "Projected month-end net"
        note = '. This is Home\'s "left to spend".'
        if o.budget_room is not None:
            note += (
                " It is month-end cash movement and counts pay not yet received, so it is not "
                "spending room while a budget is set."
            )
        out.append(f"{label}: {plain(o.projected_net, signed=True)} ({terms}){note}")
        if not o.moved.is_zero:
            out.append(
                "Before transfers to your own wallets it is "
                f"{plain(o.projected_net_before_moves, signed=True)}."
            )
    elif not o.moved.is_zero:
        out.append(
            f"Net after what was moved to your own wallets: {plain(o.projected_net, signed=True)}."
        )

    if o.adjustments:
        out.append(
            "Amounts you mentioned, added in code: "
            + "; ".join(f"{plain(a.amount, signed=True)} ({a.label})" for a in o.adjustments)
            + f"; together {plain(o.adjustments_total, signed=True)}."
        )
        joined = "-" if o.adjustments_total < Money.zero(o.currency) else "+"
        out.append(
            f"Overall with those: {plain(o.overall, signed=True)} "
            f"({plain(o.projected_net)} {joined} {plain(abs_money(o.adjustments_total))})."
        )
    out += describe_budget(o)
    if o.status != "past":
        if o.overall.is_positive or o.overall.is_zero:
            what = "the leeway" if o.budget_room is None else "month-end cash leeway"
            out.append(
                f"Headroom ({what}): {plain(o.headroom)}. That much more everyday spending, "
                "beyond what is listed, still keeps the month at zero or above."
                + (
                    ""
                    if o.budget_room is None
                    else " It counts pay not yet received and is not spending room while a "
                    "budget is set."
                )
            )
        else:
            out.append(
                f"Shortfall: {plain(o.shortfall)} below zero. That much more would have to come "
                "in, or be left unspent, to reach zero."
            )
        if o.budget_room is None and o.pay_not_yet_in.is_positive:
            out.append(
                f"Of that, pay not yet received: {pay_phrase(o)}. Say so in the reply (like "
                f'"this counts your {plain(o.pay_not_yet_in)} pay on {pay_day(o)}, not in '
                f'yet").'
            )
        if o.budget_room is None:
            out += per_day_lines(o)
        out.append(
            "Everyday spending for the rest of the month (food, transport, shopping) is not "
            "forecast, and this is movement only, not an account balance."
        )
    else:
        out += per_day_lines(o)
    return "\n".join(out)


GUIDE_LEAD = (
    "For how much could I save, ground any suggestion in these figures only (name no target "
    "that is not one of them): "
)


def percent(share: Decimal) -> str:
    """ "94.9%" from 0.949 (to one decimal place, half up)."""
    return f"{(share * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def saving_line(m: MonthSaving) -> str:
    """One month of the history: received, spent, net and the saving rate."""
    name = f"{m.month:%b %Y}"
    if m.partial:
        name += " so far (this month is not over: left out of the averages)"
    if not m.logged:
        return f"- {name}: nothing logged" + (
            "" if m.partial else " (a gap in the ledger, not counted in the averages)"
        )
    line = (
        f"- {name}: received {plain(m.received)}, spent {plain(m.spent)}, "
        f"net {plain(m.net, signed=True)} (received less spent)"
    )
    if not m.partial:  # a rate on a part-month (pay not in yet) would mislead
        if m.savings_rate is not None:
            line += f", saving rate {percent(m.savings_rate)}"
        else:
            line += ", no income, so no saving rate"
    if not m.moved.is_zero:
        line += f"; of that, {plain(m.moved)} moved to your own wallets (savings or investments)"
    if m.unconverted:
        line += "; left out, no exchange rate: " + ", ".join(str(u) for u in m.unconverted)
    return line


def describe_money_history(h: MoneyHistory) -> str:
    """The months' figures, the summary over the full ones and the guide for "how much could I
    save": no advice, only figures and what each one is."""
    out = [
        f"Savings history as of {h.today:%a %-d %b %Y}. All amounts in {h.currency}, worked out "
        "exactly in code from the same month figures Home shows: quote them, don't redo the "
        'sums. "Saved" means net: received less spent (not an account balance).'
    ]
    if h.first_day is None:
        out.append("Nothing is logged yet, so there is no history to report.")
        return "\n".join(out)
    out.append(f"The ledger starts on {h.first_day:%-d %b %Y}; earlier months are not listed.")
    out.append("Months, oldest first:")
    out += [saving_line(m) for m in h.months]

    s, g = h.summary, h.guide
    if s is None or g is None:
        out.append(
            "No full month with entries yet, so there is no average or pattern to report: say "
            "so, and don't treat a part-month as one."
        )
        return "\n".join(out)

    used = [m for m in h.months if not m.partial and m.logged]
    span = f"{used[0].month:%b %Y}"
    if len(used) > 1:
        span += f" to {used[-1].month:%b %Y}"
    rate = (
        f"; saving rate {percent(s.average_savings_rate)} (their total net over total received)"
        if s.average_savings_rate is not None
        else "; no income in them, so no saving rate"
    )
    if s.months < 2:
        out.append(
            f"Only 1 full month ({span}), so there is no average or pattern: say it is one "
            f"month's figures, net {plain(s.average_net, signed=True)}{rate}."
        )
    else:
        out.append(
            f"Over the {s.months} full months with entries ({span}): average net "
            f"{plain(s.average_net, signed=True)} a month (received {plain(s.average_received)}, "
            f"spent {plain(s.average_spent)} on average){rate}. Best month "
            f"{s.best.month:%b %Y}, net {plain(s.best.net, signed=True)}; worst month "
            f"{s.worst.month:%b %Y}, net {plain(s.worst.net, signed=True)}."
        )

    parts = [f"average spent {plain(g.average_spent)} a month"]
    if g.usual_salary is not None and g.benchmark is not None:
        parts.append(f"usual salary {plain(g.usual_salary)}")
        parts.append(
            f"{percent(BENCHMARK_RATE)} of it {plain(g.benchmark)} "
            "(a common rule of thumb, to set beside their own figures)"
        )
        if g.average_net_share_of_salary is not None:
            parts.append(
                f"their average net is {percent(g.average_net_share_of_salary)} of the usual salary"
            )
        out.append(GUIDE_LEAD + "; ".join(parts) + ".")
    else:
        out.append(
            GUIDE_LEAD
            + parts[0]
            + "; no usual salary is set, so there is no salary-based figure (don't guess one)."
        )
    return "\n".join(out)


def describe_calculation(c: Calculation) -> str:
    """The result to 2 decimal places, and the exact value when that is different."""
    shown = f"{c.rounded:,.2f}"
    if not c.exact:
        more = f"{c.value.quantize(Decimal('1e-10')):f}"
        return (
            f"{c.expression} = {shown} (to 2 decimal places; it doesn't divide out evenly: "
            f"exactly {more}... Shares of a split can differ by a cent)"
        )
    if c.rounded == c.value:
        return f"{c.expression} = {shown}"
    return f"{c.expression} = {shown} (exactly {c.value:f})"
