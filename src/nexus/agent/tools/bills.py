"""Tools for recurring bills."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from nexus.agent.tools.core import Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import parse_day, parse_money, resolve_wallet, wallet_map
from nexus.application import bills as bill_cases
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import (
    Wallet,
)
from nexus.domain.planning import Cadence


class AddBillArgs(Args):
    name: str = Field(
        description="What it's for, e.g. 'Rent', 'Electricity', 'S&P 500 ETF' or 'To savings'"
    )
    due_date: str = Field(description="Next due date, YYYY-MM-DD")
    repeats: Literal["once", "weekly", "monthly", "yearly"] = "monthly"
    counts_as_spending: bool = Field(
        True,
        description="False for money the user transfers rather than spends: a regular "
        "investment, a transfer to savings, family or another account. True for bills "
        "(rent, utilities, insurance, phone). Set automatically to False with to_wallet.",
    )
    to_wallet: str | None = Field(
        None,
        description="A scheduled transfer: the user's wallet the money goes to from the Main "
        'account ("remind me to put 1,000 into IBKR every 25th"). It is never spending. A '
        "wallet the user doesn't have yet isn't made: ask, or offer to add it first.",
    )
    amount: str | None = Field(None, description="Only if the user gave one")
    currency: str | None = Field(None, description="Defaults to the home currency")


class BillNameArgs(Args):
    name: str = Field(description="The bill's name, as the user has it")


async def _find_bill(ctx: ToolContext, name: str) -> bill_cases.BillView:
    views = await bill_cases.list_bills(ctx.uow, ctx.user, now=ctx.now)
    wanted = name.casefold().strip()
    exact = [v for v in views if v.bill.name.casefold() == wanted]
    matches = exact or [v for v in views if wanted in v.bill.name.casefold()]
    if len(matches) == 1:
        return matches[0]
    names = ", ".join(v.bill.name for v in views) or "none yet"
    if not matches:
        raise NotFound(f"no bill called {name!r}; the user's bills: {names}")
    raise InvalidInput(f"{name!r} matches several bills: {', '.join(v.bill.name for v in matches)}")


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _bill_line(
    view: bill_cases.BillView, now: datetime, wallets: dict[UUID, Wallet] | None = None
) -> str:
    bill = view.bill
    amount = f" {bill.amount}" if bill.amount else ""
    wallet = (wallets or {}).get(bill.wallet_id) if bill.wallet_id else None
    if wallet is not None:
        # A scheduled move: say where it goes, and that it isn't spending.
        every = {
            Cadence.ONCE: "",
            Cadence.WEEKLY: f", every week on {bill.anchor:%A}s",
            Cadence.MONTHLY: f", every month on the {_ordinal(bill.anchor.day)}",
            Cadence.YEARLY: f", every year on {bill.anchor.day} {bill.anchor:%B}",
        }[bill.cadence]
        snoozed = ", reminders snoozed" if view.snoozed(now) else ""
        return (
            f"{bill.name}{amount}: {bill_cases.describe_due(view)}{every}, transfer to "
            f"{wallet.name} (not spending){snoozed}"
        )
    kind = "" if bill.spending else " (not spending)"
    repeats = "" if bill.cadence is Cadence.ONCE else f", {bill.cadence.value}"
    snoozed = ", reminders snoozed" if view.snoozed(now) else ""
    return f"{bill.name}{kind}{amount}: {bill_cases.describe_due(view)}{repeats}{snoozed}"


async def _add_bill(ctx: ToolContext, a: AddBillArgs) -> ToolResult:
    due = parse_day(ctx, a.due_date).astimezone(ctx.tz).date()
    amount = parse_money(ctx, a.amount, a.currency) if a.amount else None
    # An unknown wallet is for the model to ask about; nothing is created until it does.
    wallet = await resolve_wallet(ctx, a.to_wallet) if a.to_wallet else None
    bill = await bill_cases.add_bill(
        ctx.uow(),
        ctx.user,
        a.name,
        due,
        Cadence(a.repeats),
        amount,
        now=ctx.now,
        spending=a.counts_as_spending and wallet is None,
        wallet_id=wallet.id if wallet else None,
    )
    view = bill_cases.BillView(bill, due, None, ctx.today())
    wallets = {wallet.id: wallet} if wallet else None
    return ToolResult(
        f"Added {_bill_line(view, ctx.now, wallets)}. I'll remind you 7, 3 and 1 days before.",
        wrote=True,
    )


async def _bills(ctx: ToolContext, _: NoArgs) -> ToolResult:
    views = await bill_cases.list_bills(ctx.uow, ctx.user, now=ctx.now)
    if not views:
        return ToolResult("No scheduled payments yet.")
    wallets = await wallet_map(ctx) if any(v.bill.wallet_id for v in views) else None
    return ToolResult("\n".join(_bill_line(v, ctx.now, wallets) for v in views))


class BillPaidArgs(BillNameArgs):
    amount: str | None = Field(
        default=None,
        description="What the user paid, only if they said, or the bill has no set amount",
    )
    currency: str | None = Field(default=None, description="ISO code, if not the home one")


async def _bill_paid(ctx: ToolContext, a: BillPaidArgs) -> ToolResult:
    view = await _find_bill(ctx, a.name)
    amount = parse_money(ctx, a.amount, a.currency) if a.amount else None
    paid = await bill_cases.mark_paid(ctx.uow, ctx.user, view.bill.id, now=ctx.now, amount=amount)
    return ToolResult(paid.message(ctx.tz), wrote=True)


async def _snooze_bill(ctx: ToolContext, a: BillNameArgs) -> ToolResult:
    view = await _find_bill(ctx, a.name)
    await bill_cases.snooze(ctx.uow, ctx.user, view.bill.id, now=ctx.now)
    return ToolResult(f"Snoozed reminders for {view.bill.name} until tomorrow.", wrote=True)


async def _describe_remove_bill(ctx: ToolContext, a: BillNameArgs) -> str:
    view = await _find_bill(ctx, a.name)
    return f"Stop tracking {view.bill.name} and its reminders?"


async def _remove_bill(ctx: ToolContext, a: BillNameArgs) -> ToolResult:
    view = await _find_bill(ctx, a.name)
    await bill_cases.remove_bill(ctx.uow(), ctx.user.id, view.bill.id, now=ctx.now)
    return ToolResult(f"Removed {view.bill.name}.", wrote=True)


SPECS: list[ToolSpec] = [
    ToolSpec(
        "add_bill",
        "Remember a bill or another scheduled payment (a regular investment or a "
        "transfer to savings, family or another account) and remind the user before "
        "it's due. With to_wallet it is a scheduled transfer to one of the user's wallets. "
        "Nothing is paid or moved.",
        AddBillArgs,
        _add_bill,
    ),
    ToolSpec(
        "list_bills",
        "The user's bills, regular investments and transfers, and when each is next due.",
        NoArgs,
        _bills,
    ),
    ToolSpec(
        "mark_bill_paid",
        "Record that the user has paid a bill's current due date and log it as this "
        "month's expense (skipped if it's already in the ledger). One that doesn't "
        "count as spending (an investment, a transfer to savings) is marked done and "
        "nothing is logged, except a scheduled transfer to a wallet: that logs the transfer "
        "from the Main account to the wallet (once, and not if it's already there). "
        "Records only: nothing is paid or moved, so never say you paid it.",
        BillPaidArgs,
        _bill_paid,
    ),
    ToolSpec("snooze_bill", "Hold a bill's reminders until tomorrow.", BillNameArgs, _snooze_bill),
    ToolSpec(
        "remove_bill",
        "Stop tracking a bill, investment or transfer. Asks the user to confirm.",
        BillNameArgs,
        _remove_bill,
        confirm=_describe_remove_bill,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"list_bills"})
