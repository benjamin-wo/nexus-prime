"""The words for ``month_outlook`` and ``calculate``: every figure comes from code, and the
text says which, so the model quotes them and does no sums of its own."""

from decimal import Decimal

from nexus.application.cashflow import ExpectedKind
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


def item_line(item: OutlookItem) -> str:
    if item.amount is None:
        amount = "amount not set, not counted"
    else:
        sign = "+" if item.direction is Direction.IN else "-"
        amount = f"{sign}{plain(item.amount)}"
        if item.original is not None:
            amount += f" ({item.original} at today's rate)"
    return f"- {item.day:%a %-d %b} {item.name} ({KIND_WORDS[item.kind]}) {amount}"


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
        out += [item_line(i) for i in o.items] or [
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
        out.append(
            f"Projected month-end net: {plain(o.projected_net, signed=True)} ({terms})"
            '. This is Home\'s "left to spend".'
        )
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
    if o.status != "past":
        if o.overall.is_positive or o.overall.is_zero:
            out.append(
                f"Headroom (the leeway): {plain(o.headroom)}. That much more everyday spending, "
                "beyond what is listed, still keeps the month at zero or above."
            )
        else:
            out.append(
                f"Shortfall: {plain(o.shortfall)} below zero. That much more would have to come "
                "in, or be left unspent, to reach zero."
            )
        out.append(
            "Everyday spending for the rest of the month (food, transport, shopping) is not "
            "forecast, and this is movement only, not an account balance."
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
