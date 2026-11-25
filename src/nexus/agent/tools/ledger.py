"""Tools for recording, finding, changing and asking about transactions."""

from dataclasses import replace
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from nexus.agent.tools.core import Args, IdArgs, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import (
    NO_CARD,
    _load,
    ask_about,
    category_map,
    day_start,
    describe,
    guess_category,
    parse_day,
    parse_id,
    parse_money,
    resolve_category,
    resolve_paid_with,
    show,
    show_all,
)
from nexus.application import category_rules as rule_cases
from nexus.application import duplicates as duplicate_cases
from nexus.application import income as income_cases
from nexus.application import receipts as receipt_cases
from nexus.application import split_habits as habit_cases
from nexus.application import transactions as tx_cases
from nexus.application import undo as undo_cases
from nexus.application import voice as voice_cases
from nexus.application.ports import LedgerQuery
from nexus.domain.errors import InvalidInput, NexusError
from nexus.domain.ledger import (
    Direction,
    RevisionKind,
    Source,
    Transaction,
)
from nexus.domain.phrases import Phrase, phrase


class LogExpenseArgs(Args):
    amount: str = Field(description="Amount spent, e.g. '5.50'. Never guess it.")
    currency: str | None = Field(None, description="ISO code; omit for the home currency")
    merchant: str | None = Field(
        None,
        description="Where or who was paid. Always fill it or `notes` with what was bought "
        "or where, even a bare word ('ramen', 'taxi'); never drop it for the category",
    )
    category: str | None = Field(
        None, description="Only a category the user named; exact name from the list"
    )
    best_guess_category: str | None = Field(
        None,
        description="Always fill this: the closest category from the list for this "
        "expense (Other if nothing fits). The user's category rules take precedence.",
    )
    date: str | None = Field(None, description="YYYY-MM-DD, 'today' or 'yesterday'; omit for now")
    notes: str | None = None
    use_split_habit: bool = Field(
        True,
        description="false when the message says it isn't shared this time ('my treat', "
        "'just me', 'dinner with mum' when the habit is with Ann)",
    )
    paid_with: str | None = Field(
        None,
        description="Only when the user says what paid: the card or wallet, as they named "
        "it ('citi', 'my DBS card', 'cash', or a card's last 4 digits). Omit it otherwise; "
        "their usual card is used if they set one. An unknown card is an error to ask about.",
    )


async def _log_expense(ctx: ToolContext, a: LogExpenseArgs) -> ToolResult:
    # An unknown card is asked about before anything is logged. Without card tracking the
    # model's paid_with is ignored (and so is the usual card, in the use case).
    paid_with = (
        await resolve_paid_with(ctx, a.paid_with) if a.paid_with and ctx.user.track_cards else None
    )
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
            fallback_category_id=await guess_category(ctx, a.best_guess_category),
            paid_with_wallet_id=paid_with.id if paid_with else None,
            use_usual_card=True,
        ),
    )
    text = f"Logged: {await show(ctx, tx)}"
    if paid_with is None and tx.paid_with_wallet_id is not None:
        text += (
            "\nPaid with the user's usual card; if it wasn't, edit_transaction paid_with "
            "('none' clears it)."
        )
    if a.use_split_habit:
        text += await _apply_split_habits(ctx, tx)
    return ToolResult(text, wrote=True)


async def _apply_split_habits(ctx: ToolContext, tx: Transaction) -> str:
    """Splits an expense just logged the way the user's split habits say, and returns what
    happened for the model to word ("" when no habit holds for it)."""
    category = (await category_map(ctx)).get(tx.category_id) if tx.category_id else None
    try:
        split = await habit_cases.apply_to_expense(
            ctx.uow, ctx.user.id, tx, category.name if category else None
        )
    except NexusError as exc:  # the expense is logged either way
        return f"\nThe split habit wasn't applied ({exc}); the expense is logged unsplit."
    if split is None:
        return ""
    owed = ", ".join(f"{s.participant_name} owes {s.share}" for s in split.splits)
    people = " and ".join(s.participant_name for s in split.splits)
    return (
        f"\nSplit with {people} (a standing split): {owed}. If this one wasn't shared, "
        "undo_last_change removes the split."
    )


class IncomeArgs(Args):
    amount: str = Field(description="Amount received, e.g. '6500'. Never guess it.")
    currency: str | None = Field(None, description="ISO code; omit for the home currency")
    kind: Literal["salary", "repayment", "other"] = Field(
        description="salary: pay from work; repayment: someone paying back money they owed "
        "the user; other: anything else (a gift, a refund, a bonus, a sale)"
    )
    from_whom: str | None = Field(
        None, description="Who paid it; required for a repayment. Omit for salary."
    )
    date: str | None = Field(None, description="YYYY-MM-DD, 'today' or 'yesterday'; omit for now")
    note: str | None = Field(None, description="What it was for, if the user said")


def _income_kind(a: IncomeArgs) -> income_cases.IncomeKind:
    if a.kind == "repayment" and not a.from_whom:
        raise InvalidInput("a repayment needs who paid it back")
    return income_cases.IncomeKind(a.kind)


async def _describe_income(ctx: ToolContext, a: IncomeArgs) -> str:
    kind = _income_kind(a)
    amount = parse_money(ctx, a.amount, a.currency)
    day = parse_day(ctx, a.date).astimezone(ctx.tz)
    what = {
        income_cases.IncomeKind.SALARY: f"{amount} salary",
        income_cases.IncomeKind.REPAYMENT: f"{amount} paid back by {a.from_whom}",
        income_cases.IncomeKind.OTHER: f"{amount} income"
        + (f" from {a.from_whom}" if a.from_whom else ""),
    }[kind]
    note = f" ({a.note})" if a.note else ""
    return f"Record {what}{note} on {day:%-d %b}?"


async def _record_income(ctx: ToolContext, a: IncomeArgs) -> ToolResult:
    recorded = await income_cases.record_income(
        ctx.uow,
        ctx.user,
        kind=_income_kind(a),
        amount=parse_money(ctx, a.amount, a.currency),
        occurred_at=parse_day(ctx, a.date),
        counterparty=a.from_whom,
        note=a.note,
    )
    return ToolResult(recorded.text, wrote=True, buttons=recorded.buttons or None)


class ReceiptExpenseArgs(Args):
    amount: str
    currency: str | None = None
    merchant: str | None = None
    date: str | None = None
    external_id: str
    receipt_id: str | None = None  # the stored photo, set by the kernel
    best_guess_category: str | None = None  # the receipt reader's guess
    # The currency the first look at the photo saw, when it differs from the reader's.
    seen_currency: str | None = None


async def _describe_receipt(ctx: ToolContext, a: ReceiptExpenseArgs) -> str:
    money = parse_money(ctx, a.amount, a.currency)
    when = parse_day(ctx, a.date).astimezone(ctx.tz).date().isoformat()
    ask = f"Log {money}{f' at {a.merchant}' if a.merchant else ''} on {when} from this receipt?"
    if a.seen_currency and a.seen_currency.upper() != money.currency:
        ask += (
            f" ⚠️ The receipt may be in {a.seen_currency.upper()}, not {money.currency}: "
            "if so, tap Cancel and tell me the amount and currency."
        )
    return ask


async def _log_receipt_expense(ctx: ToolContext, a: ReceiptExpenseArgs) -> ToolResult:
    tx = await receipt_cases.log_with_receipt(
        ctx.uow(),
        ctx.user.id,
        tx_cases.NewTransaction(
            direction=Direction.OUT,
            amount=parse_money(ctx, a.amount, a.currency),
            occurred_at=parse_day(ctx, a.date),
            counterparty=a.merchant,
            source=Source.PHOTO,
            external_id=a.external_id,
            fallback_category_id=await guess_category(ctx, a.best_guess_category),
            use_usual_card=True,
        ),
        UUID(a.receipt_id) if a.receipt_id else None,
        now=ctx.now,
    )
    # The user reads this line as it is (a receipt is logged without the model), so it is
    # worded for their voice.
    entry = await show(ctx, tx)
    return ToolResult(phrase(Phrase.RECEIPT_LOGGED, voice_cases.current(), entry=entry), wrote=True)


class FindArgs(Args):
    search: str | None = Field(None, description="Text to find in merchant or notes")
    direction: Literal["in", "out", "move"] | None = Field(
        None, description="move: a transfer between the user's own wallets"
    )
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
    lines = await show_all(ctx, page.items)
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
    paid_with: str | None = Field(
        None,
        description="What paid for it, as the user named it ('my DBS card', 'cash', a card's "
        "last 4 digits); 'none' clears it. Only for money out.",
    )


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
        "paid with": a.paid_with if ctx.user.track_cards else None,
    }
    changes = ", ".join(f"{k} → {v}" for k, v in wanted.items() if v)
    return await ask_about(ctx, tx, "Change", f": {changes}")


async def _edit(ctx: ToolContext, a: EditArgs) -> ToolResult:
    current = await _load(ctx, a.transaction_id)
    changes = _changes(ctx, a, current)
    if a.category is not None:
        changes = replace(changes, category_id=await resolve_category(ctx, a.category))
    if a.paid_with is not None and ctx.user.track_cards:
        if a.paid_with.strip().casefold() in NO_CARD:
            changes = replace(changes, paid_with_wallet_id=None)
        else:
            card = await resolve_paid_with(ctx, a.paid_with)
            changes = replace(changes, paid_with_wallet_id=card.id)
    tx = await tx_cases.edit_transaction(ctx.uow(), ctx.user.id, current.id, changes)
    text = f"Updated: {await show(ctx, tx)}"
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


async def _describe_delete(ctx: ToolContext, a: IdArgs) -> str:
    return await ask_about(ctx, await _load(ctx, a.transaction_id), "Delete")


async def _delete(ctx: ToolContext, a: IdArgs) -> ToolResult:
    tx = await tx_cases.delete_transaction(ctx.uow(), ctx.user.id, parse_id(a.transaction_id))
    return ToolResult(f"Deleted: {await show(ctx, tx)}", wrote=True)


async def _restore(ctx: ToolContext, a: IdArgs) -> ToolResult:
    tx = await tx_cases.restore_transaction(ctx.uow(), ctx.user.id, parse_id(a.transaction_id))
    return ToolResult(f"Restored: {await show(ctx, tx)}", wrote=True)


async def _undo(ctx: ToolContext, _: NoArgs) -> ToolResult:
    result = await undo_cases.undo_latest(ctx.uow(), ctx.user.id)
    if isinstance(result, undo_cases.TripUndo):
        return ToolResult(result.message(), wrote=True)
    tx = await show(ctx, result.transaction)
    text = f"Undid the last {result.undone.value}: {tx}"
    if result.undone is RevisionKind.SPLIT:
        text += " The expense itself is unchanged."
    return ToolResult(text, wrote=True)


class DuplicatesArgs(Args):
    start_date: str | None = Field(None, description="YYYY-MM-DD; default: 30 days ago")
    end_date: str | None = Field(None, description="YYYY-MM-DD inclusive; default: today")


async def _duplicates(ctx: ToolContext, a: DuplicatesArgs) -> ToolResult:
    start = day_start(ctx, a.start_date or (ctx.today() - timedelta(days=30)).isoformat())
    end = day_start(ctx, a.end_date or ctx.today().isoformat()) + timedelta(days=1)
    pairs = await duplicate_cases.find_pairs(ctx.uow, ctx.user, start, end)
    if not pairs:
        return ToolResult("No possible duplicates in that period.")
    names = await category_map(ctx)
    lines = ["Possible duplicates (the same amount within a day, by a similar merchant):"]
    for n, p in enumerate(pairs[:10], 1):
        lines.append(f"{n}. {describe(p.first, names, ctx.tz)}")
        lines.append(f"   and {describe(p.second, names, ctx.tz)}")
    lines.append(
        "Merge a pair only when the user says they're the same payment. The Ledger shows "
        "each with Merge and Not a duplicate too."
    )
    return ToolResult("\n".join(lines))


class MergeDuplicatesArgs(Args):
    transaction_id: str = Field(description="One of the pair (from find_duplicates)")
    other_id: str = Field(description="The other one")


async def _describe_combine_duplicates(ctx: ToolContext, a: MergeDuplicatesArgs) -> str:
    first, second = await _load(ctx, a.transaction_id), await _load(ctx, a.other_id)
    names = await category_map(ctx)
    one = describe(first, names, ctx.tz).split(" [id")[0]
    other = describe(second, names, ctx.tz).split(" [id")[0]
    return f"Merge these into one, deleting the extra (it can be restored)? {one} / {other}"


async def _combine_duplicates(ctx: ToolContext, a: MergeDuplicatesArgs) -> ToolResult:
    merged = await duplicate_cases.merge(
        ctx.uow, ctx.user.id, parse_id(a.transaction_id), parse_id(a.other_id)
    )
    names = await category_map(ctx)
    return ToolResult(
        f"Kept {describe(merged.kept, names, ctx.tz)}; deleted the extra "
        f"{describe(merged.removed, names, ctx.tz)}.",
        wrote=True,
    )


SPECS: list[ToolSpec] = [
    ToolSpec(
        "log_expense",
        "Record money the user spent. Only when the amount is stated. Keep what was "
        "bought or where as the merchant or a note ('¥1200 ramen in tokyo' is merchant or "
        "notes 'ramen'). A city named in an expense says nothing about where the user is. "
        "If they say what paid ('on my citi card', 'with cash'), give paid_with; an "
        "unknown card comes back as an error: ask whether to add it, don't log yet.",
        LogExpenseArgs,
        _log_expense,
    ),
    ToolSpec(
        "record_income",
        "Record money the user received: salary, someone paying back what they owed, "
        "or other income. Only when the amount and kind are clear; otherwise ask. "
        "Asks the user to confirm.",
        IncomeArgs,
        _record_income,
        confirm=_describe_income,
    ),
    ToolSpec(
        "find_transactions",
        "Search the user's ledger. Use it to find ids before changing anything. To find "
        "spending that's really a transfer between the user's own accounts, use "
        "find_likely_moves instead.",
        FindArgs,
        _find,
    ),
    ToolSpec(
        "edit_transaction",
        "Change fields of one transaction, including which card paid for it (paid_with: "
        "'that was on my DBS card'; 'none' clears it). Asks the user to confirm.",
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
    ToolSpec(
        "find_duplicates",
        "Possible duplicates: one payment recorded twice (a card alert and a receipt, "
        "or a typed entry and an email). Read-only.",
        DuplicatesArgs,
        _duplicates,
    ),
    ToolSpec(
        "combine_duplicate_transactions",
        "Two transactions that are one payment recorded twice: keep one, under the more "
        "readable name, and delete the extra. Only when the user says they're the same "
        "payment; not for categories. Asks the user to confirm.",
        MergeDuplicatesArgs,
        _combine_duplicates,
        confirm=_describe_combine_duplicates,
    ),
    ToolSpec("restore_transaction", "Bring back a deleted transaction.", IdArgs, _restore),
    ToolSpec("undo_last_change", "Undo the user's most recent change.", NoArgs, _undo),
    ToolSpec(
        "log_receipt_expense",
        "Record an expense read from a receipt photo.",
        ReceiptExpenseArgs,
        _log_receipt_expense,
        confirm=_describe_receipt,
        exposed=False,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"find_duplicates", "find_transactions"})
