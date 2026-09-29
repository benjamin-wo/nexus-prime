"""Tools the agent can call. Each is a thin wrapper over one use case.

Tools never take a user id: the acting user comes from the authenticated
channel via ToolContext. Arguments the model sends that a tool doesn't
declare, including any attempt at ``user_id``, are dropped.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexus.application import bills as bill_cases
from nexus.application import budgets as budget_cases
from nexus.application import categories as category_cases
from nexus.application import category_rules as rule_cases
from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.fx import Rate, RateSource
from nexus.application.ports import LedgerQuery, UnitOfWork
from nexus.domain.errors import InvalidInput, NexusError, NotFound
from nexus.domain.ledger import (
    Category,
    Direction,
    ShareRequest,
    Source,
    Transaction,
    User,
    plan_split,
)
from nexus.domain.money import Money
from nexus.domain.planning import Cadence, PayRule
from nexus.domain.rules import clean_pattern

type UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class ToolContext:
    user: User
    uow: UowFactory
    now: datetime
    rates: RateSource | None = None  # for home-currency figures; None converts nothing

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.user.timezone)

    def today(self) -> date:
        return self.now.astimezone(self.tz).date()


class Args(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


@dataclass(frozen=True, slots=True)
class ToolResult:
    text: str
    wrote: bool = False
    # Extra reply buttons, rows of (label, data), shown under the agent's answer.
    buttons: list[list[tuple[str, str]]] | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    args: type[Args]
    run: Callable[[ToolContext, Any], Awaitable[ToolResult]]
    # When set, the call needs the user's confirmation; returns what to show them.
    confirm: Callable[[ToolContext, Any], Awaitable[str]] | None = None
    # Internal tools are created by the kernel only; the model never sees them.
    exposed: bool = True

    def schema(self) -> dict[str, Any]:
        params = inline_refs(self.args.model_json_schema())
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": params},
        }

    def parse(self, raw: dict[str, Any]) -> Any:
        try:
            return self.args.model_validate(raw)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in exc.errors()
            )
            raise InvalidInput(f"invalid arguments for {self.name}: {problems}") from exc


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve $ref/$defs and drop titles: some providers (Gemini) ignore $defs."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items() if k not in {"$defs", "title"}}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    result: dict[str, Any] = walk(schema)
    return result


# --- helpers --------------------------------------------------------------------


def parse_day(ctx: ToolContext, value: str | None) -> datetime:
    """A calendar day (or 'today'/'yesterday') at noon local time, or now."""
    if value is None or value.lower() == "today":
        if value is None:
            return ctx.now
        day = ctx.today()
    elif value.lower() == "yesterday":
        day = ctx.today() - timedelta(days=1)
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise InvalidInput(f"dates must look like 2026-09-28, not {value!r}") from exc
        if parsed.tzinfo is not None:
            return parsed
        if parsed.time() != time():
            return parsed.replace(tzinfo=ctx.tz)
        day = parsed.date()
    return datetime.combine(day, time(12), tzinfo=ctx.tz)


def day_start(ctx: ToolContext, value: str) -> datetime:
    return datetime.combine(parse_day(ctx, value).date(), time(), tzinfo=ctx.tz)


def parse_money(ctx: ToolContext, amount: str, currency: str | None) -> Money:
    return Money.of(amount.replace(",", ""), currency or ctx.user.home_currency)


def parse_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise NotFound("no transaction with that id") from exc


async def category_map(ctx: ToolContext) -> dict[UUID, Category]:
    cats = await category_cases.list_categories(ctx.uow(), ctx.user.id, include_inactive=True)
    return {c.id: c for c in cats}


async def resolve_category(ctx: ToolContext, name: str | None) -> UUID | None:
    if name is None:
        return None
    active = await category_cases.list_categories(ctx.uow(), ctx.user.id)
    for category in active:
        if category.name.casefold() == name.casefold():
            return category.id
    options = ", ".join(c.name for c in active)
    raise InvalidInput(f"unknown category {name!r}; choose one of: {options}")


def describe(tx: Transaction, cats: dict[UUID, Category], tz: ZoneInfo) -> str:
    sign = "-" if tx.direction is Direction.OUT else "+"
    parts = [tx.occurred_at.astimezone(tz).date().isoformat(), f"{sign}{tx.amount}"]
    if tx.counterparty:
        parts.append(tx.counterparty)
    if tx.category_id and tx.category_id in cats:
        parts.append(cats[tx.category_id].name)
    if tx.notes:
        parts.append(f"note: {tx.notes}")
    if tx.status.value == "pending":
        parts.append("pending")
    if tx.is_deleted:
        parts.append("deleted")
    return " · ".join(parts) + f" [id {tx.id}]"


async def _load(ctx: ToolContext, transaction_id: str) -> Transaction:
    return await tx_cases.get_transaction(ctx.uow(), ctx.user.id, parse_id(transaction_id))


# --- tools ------------------------------------------------------------------------


class LogExpenseArgs(Args):
    amount: str = Field(description="Amount spent, e.g. '5.50'. Never guess it.")
    currency: str | None = Field(None, description="ISO code; omit for the home currency")
    merchant: str | None = Field(None, description="Where or who was paid")
    category: str | None = Field(None, description="Exact category name from list_categories")
    date: str | None = Field(None, description="YYYY-MM-DD, 'today' or 'yesterday'; omit for now")
    notes: str | None = None


async def _log_expense(ctx: ToolContext, a: LogExpenseArgs) -> ToolResult:
    tx = await tx_cases.log_transaction(
        ctx.uow(),
        ctx.user.id,
        tx_cases.NewTransaction(
            direction=Direction.OUT,
            amount=parse_money(ctx, a.amount, a.currency),
            occurred_at=parse_day(ctx, a.date),
            counterparty=a.merchant,
            category_id=await resolve_category(ctx, a.category),
            notes=a.notes,
            source=Source.TEXT,
        ),
    )
    return ToolResult(f"Logged: {describe(tx, await category_map(ctx), ctx.tz)}", wrote=True)


class ReceiptExpenseArgs(Args):
    amount: str
    currency: str | None = None
    merchant: str | None = None
    date: str | None = None
    external_id: str


async def _describe_receipt(ctx: ToolContext, a: ReceiptExpenseArgs) -> str:
    money = parse_money(ctx, a.amount, a.currency)
    when = parse_day(ctx, a.date).astimezone(ctx.tz).date().isoformat()
    return f"Log {money}{f' at {a.merchant}' if a.merchant else ''} on {when} from this receipt?"


async def _log_receipt_expense(ctx: ToolContext, a: ReceiptExpenseArgs) -> ToolResult:
    tx = await tx_cases.log_transaction(
        ctx.uow(),
        ctx.user.id,
        tx_cases.NewTransaction(
            direction=Direction.OUT,
            amount=parse_money(ctx, a.amount, a.currency),
            occurred_at=parse_day(ctx, a.date),
            counterparty=a.merchant,
            source=Source.PHOTO,
            external_id=a.external_id,
        ),
    )
    return ToolResult(f"Logged from receipt: {describe(tx, {}, ctx.tz)}", wrote=True)


class FindArgs(Args):
    search: str | None = Field(None, description="Text to find in merchant or notes")
    direction: Literal["in", "out"] | None = None
    category: str | None = None
    start_date: str | None = Field(None, description="YYYY-MM-DD, inclusive")
    end_date: str | None = Field(None, description="YYYY-MM-DD, inclusive")
    include_deleted: bool = False
    limit: int = Field(10, ge=1, le=50)


async def _find(ctx: ToolContext, a: FindArgs) -> ToolResult:
    start = day_start(ctx, a.start_date) if a.start_date else None
    end = day_start(ctx, a.end_date) + timedelta(days=1) if a.end_date else None
    page = await tx_cases.list_ledger(
        ctx.uow(),
        ctx.user.id,
        LedgerQuery(
            direction=Direction(a.direction) if a.direction else None,
            category_id=await resolve_category(ctx, a.category),
            search=a.search,
            start=start,
            end=end,
            include_deleted=a.include_deleted,
            limit=a.limit,
        ),
    )
    if not page.items:
        return ToolResult("No matching transactions.")
    cats = await category_map(ctx)
    lines = [describe(tx, cats, ctx.tz) for tx in page.items]
    more = f"\n({page.total - len(lines)} more not shown)" if page.total > len(lines) else ""
    return ToolResult("\n".join(lines) + more)


class EditArgs(Args):
    transaction_id: str
    amount: str | None = None
    currency: str | None = None
    merchant: str | None = None
    category: str | None = None
    date: str | None = None
    notes: str | None = None


def _changes(ctx: ToolContext, a: EditArgs, current: Transaction) -> tx_cases.TransactionChanges:
    fields: dict[str, Any] = {}
    if a.amount is not None or a.currency is not None:
        fields["amount"] = parse_money(
            ctx, a.amount or str(current.amount.amount), a.currency or current.amount.currency
        )
    if a.merchant is not None:
        fields["counterparty"] = a.merchant
    if a.date is not None:
        fields["occurred_at"] = parse_day(ctx, a.date)
    if a.notes is not None:
        fields["notes"] = a.notes
    return tx_cases.TransactionChanges(**fields)


async def _describe_edit(ctx: ToolContext, a: EditArgs) -> str:
    tx = await _load(ctx, a.transaction_id)
    wanted = {
        "amount": f"{a.amount or tx.amount.amount} {a.currency or tx.amount.currency}"
        if a.amount or a.currency
        else None,
        "merchant": a.merchant,
        "category": a.category,
        "date": a.date,
        "notes": a.notes,
    }
    changes = ", ".join(f"{k} → {v}" for k, v in wanted.items() if v)
    return f"Change {describe(tx, await category_map(ctx), ctx.tz).split(' [id')[0]}: {changes}?"


async def _edit(ctx: ToolContext, a: EditArgs) -> ToolResult:
    current = await _load(ctx, a.transaction_id)
    changes = _changes(ctx, a, current)
    if a.category is not None:
        changes = replace(changes, category_id=await resolve_category(ctx, a.category))
    tx = await tx_cases.edit_transaction(ctx.uow(), ctx.user.id, current.id, changes)
    text = f"Updated: {describe(tx, await category_map(ctx), ctx.tz)}"
    if tx.category_id == current.category_id:
        return ToolResult(text, wrote=True)
    # A correction never changes a rule by itself: offer it, and let the user decide.
    offer = await rule_cases.suggest_rule(ctx.uow(), ctx.user.id, tx)
    if offer is None:
        return ToolResult(text, wrote=True)
    return ToolResult(
        f"{text}\nAsking the user with buttons: {offer.question} "
        "Mention the question in your reply; don't ask it any other way.",
        wrote=True,
        buttons=rule_buttons(offer),
    )


def rule_buttons(offer: rule_cases.RuleSuggestion) -> list[list[tuple[str, str]]]:
    save = "Change rule" if offer.replaces else "Save rule"
    return [[(save, f"rule:save:{offer.transaction_id}"), ("Just this once", "rule:skip")]]


class IdArgs(Args):
    transaction_id: str


async def _describe_delete(ctx: ToolContext, a: IdArgs) -> str:
    tx = await _load(ctx, a.transaction_id)
    return f"Delete {describe(tx, await category_map(ctx), ctx.tz).split(' [id')[0]}?"


async def _delete(ctx: ToolContext, a: IdArgs) -> ToolResult:
    tx = await tx_cases.delete_transaction(ctx.uow(), ctx.user.id, parse_id(a.transaction_id))
    return ToolResult(f"Deleted: {describe(tx, await category_map(ctx), ctx.tz)}", wrote=True)


async def _restore(ctx: ToolContext, a: IdArgs) -> ToolResult:
    tx = await tx_cases.restore_transaction(ctx.uow(), ctx.user.id, parse_id(a.transaction_id))
    return ToolResult(f"Restored: {describe(tx, await category_map(ctx), ctx.tz)}", wrote=True)


class NoArgs(Args):
    pass


async def _undo(ctx: ToolContext, _: NoArgs) -> ToolResult:
    result = await tx_cases.undo_last(ctx.uow(), ctx.user.id)
    tx = describe(result.transaction, await category_map(ctx), ctx.tz)
    return ToolResult(f"Undid the last {result.undone.value}: {tx}", wrote=True)


class SummaryArgs(Args):
    start_date: str | None = Field(None, description="YYYY-MM-DD; default: 1st of this month")
    end_date: str | None = Field(None, description="YYYY-MM-DD inclusive; default: today")


async def _summary(ctx: ToolContext, a: SummaryArgs) -> ToolResult:
    start = (
        day_start(ctx, a.start_date)
        if a.start_date
        else datetime.combine(ctx.today().replace(day=1), time(), tzinfo=ctx.tz)
    )
    end = day_start(ctx, a.end_date or ctx.today().isoformat()) + timedelta(days=1)
    summary = await tx_cases.summarize(ctx.uow(), ctx.user.id, start, end)
    period = f"{start.date().isoformat()} to {(end - timedelta(days=1)).date().isoformat()}"
    if not summary.totals:
        return ToolResult(f"Nothing recorded from {period}.")
    lines = [f"From {period}:"]
    lines += [f"money {t.direction.value}: {t.total} ({t.count})" for t in summary.totals]
    lines += [
        f"  {c.category_name or 'Uncategorised'}: {c.total}" for c in summary.spending_by_category
    ]
    return ToolResult("\n".join(lines))


async def _categories(ctx: ToolContext, _: NoArgs) -> ToolResult:
    cats = await category_cases.list_categories(ctx.uow(), ctx.user.id)
    return ToolResult(", ".join(c.name for c in cats) or "No categories.")


async def _rules(ctx: ToolContext, _: NoArgs) -> ToolResult:
    views = await rule_cases.list_rules(ctx.uow(), ctx.user.id)
    if not views:
        return ToolResult("No category rules yet.")
    return ToolResult(
        "\n".join(f"“{v.rule.pattern}” → {v.category.name}. {v.rule.explanation}" for v in views)
    )


class RuleArgs(Args):
    pattern: str = Field(description="Word or phrase in the merchant or notes, e.g. 'grab'")
    category: str = Field(description="Exact category name from list_categories")


async def _describe_rule(ctx: ToolContext, a: RuleArgs) -> str:
    category_id = await resolve_category(ctx, a.category)
    pattern = clean_pattern(a.pattern)
    for view in await rule_cases.list_rules(ctx.uow(), ctx.user.id):
        if view.rule.pattern == pattern and view.category.id != category_id:
            return (
                f"Change your rule for “{pattern}” from {view.category.name} to {a.category}? "
                "Expenses already logged stay as they are."
            )
    return f"File new expenses mentioning “{pattern}” under {a.category}?"


async def _set_rule(ctx: ToolContext, a: RuleArgs) -> ToolResult:
    category_id = await resolve_category(ctx, a.category)
    if category_id is None:
        raise InvalidInput("a rule needs a category")
    change = await rule_cases.set_rule(ctx.uow(), ctx.user, a.pattern, category_id, now=ctx.now)
    name, pattern = change.category.name, change.rule.pattern
    if not change.changed:
        return ToolResult(f"Your rule already files “{pattern}” under {name}.")
    if change.previous:
        return ToolResult(f"Changed: “{pattern}” now files under {name}.", wrote=True)
    return ToolResult(f"Saved: new expenses mentioning “{pattern}” go under {name}.", wrote=True)


class RulePatternArgs(Args):
    pattern: str = Field(description="The rule's word or phrase, as list_category_rules shows")


async def _describe_remove_rule(ctx: ToolContext, a: RulePatternArgs) -> str:
    view = await rule_cases.find_rule(ctx.uow(), ctx.user.id, a.pattern)
    return f"Remove your rule filing “{view.rule.pattern}” under {view.category.name}?"


async def _remove_rule(ctx: ToolContext, a: RulePatternArgs) -> ToolResult:
    view = await rule_cases.find_rule(ctx.uow(), ctx.user.id, a.pattern)
    await rule_cases.remove_rule(ctx.uow(), ctx.user.id, view.rule.id, now=ctx.now)
    return ToolResult(
        f"Removed the rule for “{view.rule.pattern}”. Expenses it filed keep their category.",
        wrote=True,
    )


async def _explain_category(ctx: ToolContext, a: IdArgs) -> ToolResult:
    result = await rule_cases.explain(ctx.uow(), ctx.user.id, parse_id(a.transaction_id))
    return ToolResult(result.text)


class Participant(Args):
    name: str
    amount: str | None = Field(
        None, description="Their share; omit on every entry to split equally"
    )


class SplitArgs(Args):
    transaction_id: str
    participants: list[Participant] = Field(min_length=1, description="Everyone except the user")
    include_me: bool = Field(True, description="Whether the user takes an equal share")


def _requests(ctx: ToolContext, a: SplitArgs, currency: str) -> list[ShareRequest]:
    return [
        ShareRequest(p.name, parse_money(ctx, p.amount, currency) if p.amount else None)
        for p in a.participants
    ]


async def _describe_split(ctx: ToolContext, a: SplitArgs) -> str:
    tx = await _load(ctx, a.transaction_id)
    plan = plan_split(tx.amount, _requests(ctx, a, tx.amount.currency), include_self=a.include_me)
    owed = ", ".join(f"{s.participant_name} owes {s.share}" for s in plan.shares)
    head = describe(tx, await category_map(ctx), ctx.tz).split(" [id")[0]
    return f"Split {head}: {owed}; your share {plan.own_share}?"


async def _split(ctx: ToolContext, a: SplitArgs) -> ToolResult:
    tx = await _load(ctx, a.transaction_id)
    result = await split_cases.split_bill(
        ctx.uow(),
        ctx.user.id,
        tx.id,
        _requests(ctx, a, tx.amount.currency),
        include_self=a.include_me,
    )
    owed = ", ".join(f"{s.participant_name} owes {s.share}" for s in result.splits)
    return ToolResult(f"Split recorded: {owed}; your share {result.own_share}.", wrote=True)


class IousArgs(Args):
    name: str | None = Field(None, description="Only this person")


async def _ious(ctx: ToolContext, a: IousArgs) -> ToolResult:
    ious = await split_cases.list_open_ious(ctx.uow(), ctx.user.id, participant_name=a.name)
    if not ious:
        return ToolResult("Nobody owes anything.")
    return ToolResult(
        "\n".join(
            f"{i.split.participant_name} owes {i.outstanding} "
            f"(from {i.expense_occurred_at.astimezone(ctx.tz).date().isoformat()})"
            for i in ious
        )
    )


class _NoRates:
    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        return None


def _rates(ctx: ToolContext) -> RateSource:
    return ctx.rates if ctx.rates is not None else _NoRates()


class BudgetArgs(Args):
    amount: str = Field(description="Monthly limit, in the user's home currency")
    category: str | None = Field(
        None, description="Category name; leave out for the overall budget"
    )


class BudgetTargetArgs(Args):
    category: str | None = Field(
        None, description="Category name; leave out for the overall budget"
    )


def _budget_name(category: str | None) -> str:
    return f"{category} budget" if category else "overall budget"


async def _set_budget(ctx: ToolContext, a: BudgetArgs) -> ToolResult:
    category_id = await resolve_category(ctx, a.category)
    limit = parse_money(ctx, a.amount, None)
    await budget_cases.set_budget(ctx.uow(), ctx.user, category_id, limit, now=ctx.now)
    return ToolResult(f"Your {_budget_name(a.category)} is now {limit} a month.", wrote=True)


async def _budgets(ctx: ToolContext, _: NoArgs) -> ToolResult:
    statuses = await budget_cases.budget_statuses(ctx.uow, _rates(ctx), ctx.user, now=ctx.now)
    if not statuses:
        return ToolResult("No budgets set.")
    lines = []
    for s in statuses:
        line = f"{s.name}: {s.spent} of {s.budget.limit} this month ({s.percent}%)"
        if s.unconverted:
            line += f"; not counted, no exchange rate: {', '.join(map(str, s.unconverted))}"
        lines.append(line)
    return ToolResult("\n".join(lines))


async def _find_budget(ctx: ToolContext, category: str | None) -> UUID:
    category_id = await resolve_category(ctx, category)
    async with ctx.uow() as tx:
        budgets = await tx.planning.list_budgets(ctx.user.id)
    for b in budgets:
        if b.category_id == category_id:
            return b.id
    raise NotFound(f"there is no {_budget_name(category)}")


async def _describe_remove_budget(ctx: ToolContext, a: BudgetTargetArgs) -> str:
    await _find_budget(ctx, a.category)
    return f"Remove your {_budget_name(a.category)}?"


async def _remove_budget(ctx: ToolContext, a: BudgetTargetArgs) -> ToolResult:
    await budget_cases.remove_budget(ctx.uow(), ctx.user.id, await _find_budget(ctx, a.category))
    return ToolResult(f"Removed your {_budget_name(a.category)}.", wrote=True)


class AddBillArgs(Args):
    name: str = Field(description="What the bill is for, e.g. 'Electricity' or 'Rent'")
    due_date: str = Field(description="Next due date, YYYY-MM-DD")
    repeats: Literal["once", "weekly", "monthly", "yearly"] = "monthly"
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


def _bill_line(view: bill_cases.BillView, now: datetime) -> str:
    bill = view.bill
    amount = f" {bill.amount}" if bill.amount else ""
    repeats = "" if bill.cadence is Cadence.ONCE else f", {bill.cadence.value}"
    snoozed = ", reminders snoozed" if view.snoozed(now) else ""
    return f"{bill.name}{amount}: {bill_cases.describe_due(view)}{repeats}{snoozed}"


async def _add_bill(ctx: ToolContext, a: AddBillArgs) -> ToolResult:
    due = parse_day(ctx, a.due_date).astimezone(ctx.tz).date()
    amount = parse_money(ctx, a.amount, a.currency) if a.amount else None
    bill = await bill_cases.add_bill(
        ctx.uow(), ctx.user, a.name, due, Cadence(a.repeats), amount, now=ctx.now
    )
    view = bill_cases.BillView(bill, due, None, ctx.today())
    return ToolResult(
        f"Added {_bill_line(view, ctx.now)}. I'll remind you 7, 3 and 1 days before.", wrote=True
    )


async def _bills(ctx: ToolContext, _: NoArgs) -> ToolResult:
    views = await bill_cases.list_bills(ctx.uow, ctx.user, now=ctx.now)
    if not views:
        return ToolResult("No bills yet.")
    return ToolResult("\n".join(_bill_line(v, ctx.now) for v in views))


async def _bill_paid(ctx: ToolContext, a: BillNameArgs) -> ToolResult:
    view = await _find_bill(ctx, a.name)
    await bill_cases.mark_paid(ctx.uow, ctx.user, view.bill.id, now=ctx.now)
    return ToolResult(
        f"Marked {view.bill.name} due {view.due.isoformat()} as paid (nothing was paid by me).",
        wrote=True,
    )


async def _snooze_bill(ctx: ToolContext, a: BillNameArgs) -> ToolResult:
    view = await _find_bill(ctx, a.name)
    await bill_cases.snooze(ctx.uow, ctx.user, view.bill.id, now=ctx.now)
    return ToolResult(f"Snoozed reminders for {view.bill.name} until tomorrow.", wrote=True)


async def _describe_remove_bill(ctx: ToolContext, a: BillNameArgs) -> str:
    view = await _find_bill(ctx, a.name)
    return f"Remove the bill {view.bill.name} and stop its reminders?"


async def _remove_bill(ctx: ToolContext, a: BillNameArgs) -> ToolResult:
    view = await _find_bill(ctx, a.name)
    await bill_cases.remove_bill(ctx.uow(), ctx.user.id, view.bill.id, now=ctx.now)
    return ToolResult(f"Removed {view.bill.name}.", wrote=True)


class PayScheduleArgs(Args):
    rule: Literal["day_of_month", "last_weekday", "every_two_weeks"]
    day: int | None = Field(None, description="1-31, for day_of_month")
    next_payday: str | None = Field(None, description="YYYY-MM-DD, for every_two_weeks")


class SalaryArgs(Args):
    amount: str = Field(description="The usual salary, as the user stated it")
    currency: str | None = None


_RULES = {
    "day_of_month": PayRule.MONTHLY_DAY,
    "last_weekday": PayRule.LAST_WEEKDAY,
    "every_two_weeks": PayRule.BIWEEKLY,
}


def _pay_line(view: salary_cases.PayView) -> str:
    s = view.schedule
    usual = f" Usual salary: {s.baseline}." if s.baseline else " No usual salary saved."
    when = "today" if view.days_until == 0 else f"{view.next_payday:%a %-d %b}"
    return (
        f"Paid on {salary_cases.describe_rule(s)} (weekend paydays move to Friday). "
        f"Next payday: {when}.{usual}"
    )


async def _set_pay_schedule(ctx: ToolContext, a: PayScheduleArgs) -> ToolResult:
    anchor = parse_day(ctx, a.next_payday).astimezone(ctx.tz).date() if a.next_payday else None
    await salary_cases.set_schedule(
        ctx.uow(), ctx.user, _RULES[a.rule], day=a.day, anchor=anchor, now=ctx.now
    )
    view = await salary_cases.view(ctx.uow(), ctx.user, now=ctx.now)
    return ToolResult(_pay_line(view) if view else "Saved.", wrote=True)


async def _pay_schedule(ctx: ToolContext, _: NoArgs) -> ToolResult:
    view = await salary_cases.view(ctx.uow(), ctx.user, now=ctx.now)
    return ToolResult(_pay_line(view) if view else "No pay schedule set.")


async def _describe_usual_salary(ctx: ToolContext, a: SalaryArgs) -> str:
    return f"Make {parse_money(ctx, a.amount, a.currency)} your usual salary?"


async def _set_usual_salary(ctx: ToolContext, a: SalaryArgs) -> ToolResult:
    amount = parse_money(ctx, a.amount, a.currency)
    await salary_cases.set_baseline(ctx.uow(), ctx.user, amount, now=ctx.now)
    return ToolResult(f"Your usual salary is now {amount}.", wrote=True)


async def _describe_remove_pay(ctx: ToolContext, _: NoArgs) -> str:
    return "Remove your pay schedule and usual salary? Payday check-ins will stop."


async def _remove_pay(ctx: ToolContext, _: NoArgs) -> ToolResult:
    await salary_cases.remove_schedule(ctx.uow(), ctx.user.id)
    return ToolResult("Removed your pay schedule.", wrote=True)


class SkillArgs(Args):
    name: str


def _skill_tool(load: Callable[[str], str]) -> ToolSpec:
    async def run(_: ToolContext, a: SkillArgs) -> ToolResult:
        return ToolResult(load(a.name))

    return ToolSpec("load_skill", "Read the full instructions for a skill by name.", SkillArgs, run)


def build_tools(load_skill: Callable[[str], str]) -> dict[str, ToolSpec]:
    specs = [
        ToolSpec(
            "log_expense",
            "Record money the user spent. Only when the amount is stated.",
            LogExpenseArgs,
            _log_expense,
        ),
        ToolSpec(
            "find_transactions",
            "Search the user's ledger. Use it to find ids before changing anything.",
            FindArgs,
            _find,
        ),
        ToolSpec(
            "edit_transaction",
            "Change fields of one transaction. Asks the user to confirm.",
            EditArgs,
            _edit,
            confirm=_describe_edit,
        ),
        ToolSpec(
            "delete_transaction",
            "Delete one transaction (it can be restored). Asks the user to confirm.",
            IdArgs,
            _delete,
            confirm=_describe_delete,
        ),
        ToolSpec("restore_transaction", "Bring back a deleted transaction.", IdArgs, _restore),
        ToolSpec("undo_last_change", "Undo the user's most recent change.", NoArgs, _undo),
        ToolSpec("spending_summary", "Totals for a period, by category.", SummaryArgs, _summary),
        ToolSpec("list_categories", "The user's active categories.", NoArgs, _categories),
        ToolSpec(
            "list_category_rules",
            "The user's category rules and why each exists.",
            NoArgs,
            _rules,
        ),
        ToolSpec(
            "set_category_rule",
            "File new expenses mentioning a word under a category, when the user asks. "
            "Asks the user to confirm.",
            RuleArgs,
            _set_rule,
            confirm=_describe_rule,
        ),
        ToolSpec(
            "remove_category_rule",
            "Remove a category rule. Asks the user to confirm.",
            RulePatternArgs,
            _remove_rule,
            confirm=_describe_remove_rule,
        ),
        ToolSpec(
            "explain_category",
            "Why a transaction is in its category.",
            IdArgs,
            _explain_category,
        ),
        ToolSpec(
            "split_bill",
            "Split an expense the user paid with other people. Asks the user to confirm.",
            SplitArgs,
            _split,
            confirm=_describe_split,
        ),
        ToolSpec("list_ious", "Who still owes the user money.", IousArgs, _ious),
        ToolSpec(
            "set_budget",
            "Set or change a monthly budget, overall or for one category.",
            BudgetArgs,
            _set_budget,
        ),
        ToolSpec(
            "list_budgets", "Budgets and how much of each is used this month.", NoArgs, _budgets
        ),
        ToolSpec(
            "add_bill",
            "Remember a bill and remind the user before it's due.",
            AddBillArgs,
            _add_bill,
        ),
        ToolSpec("list_bills", "The user's bills and when each is next due.", NoArgs, _bills),
        ToolSpec(
            "mark_bill_paid",
            "Record that the user has paid a bill's current due date. Pays nothing.",
            BillNameArgs,
            _bill_paid,
        ),
        ToolSpec(
            "snooze_bill", "Hold a bill's reminders until tomorrow.", BillNameArgs, _snooze_bill
        ),
        ToolSpec(
            "remove_bill",
            "Stop tracking a bill. Asks the user to confirm.",
            BillNameArgs,
            _remove_bill,
            confirm=_describe_remove_bill,
        ),
        ToolSpec(
            "set_pay_schedule",
            "Set when the user is paid, as they told you.",
            PayScheduleArgs,
            _set_pay_schedule,
        ),
        ToolSpec("show_pay_schedule", "When the user is paid next.", NoArgs, _pay_schedule),
        ToolSpec(
            "set_usual_salary",
            "Change the user's usual salary. Asks the user to confirm.",
            SalaryArgs,
            _set_usual_salary,
            confirm=_describe_usual_salary,
        ),
        ToolSpec(
            "remove_pay_schedule",
            "Stop tracking the user's pay. Asks the user to confirm.",
            NoArgs,
            _remove_pay,
            confirm=_describe_remove_pay,
        ),
        ToolSpec(
            "remove_budget",
            "Remove a budget. Asks the user to confirm.",
            BudgetTargetArgs,
            _remove_budget,
            confirm=_describe_remove_budget,
        ),
        _skill_tool(load_skill),
        ToolSpec(
            "log_receipt_expense",
            "Record an expense read from a receipt photo.",
            ReceiptExpenseArgs,
            _log_receipt_expense,
            confirm=_describe_receipt,
            exposed=False,
        ),
    ]
    return {spec.name: spec for spec in specs}


async def run_tool(spec: ToolSpec, ctx: ToolContext, raw_args: dict[str, Any]) -> ToolResult:
    """Validate and run one call. Expected failures come back as text for the model."""
    try:
        return await spec.run(ctx, spec.parse(raw_args))
    except NexusError as exc:
        return ToolResult(f"Error: {exc}")


def args_json(raw: dict[str, Any]) -> str:
    return json.dumps(raw, sort_keys=True, default=str)
