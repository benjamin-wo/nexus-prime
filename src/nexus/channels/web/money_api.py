"""Web API: summary, spending, categories, wallets, rules, what Nexus remembers, IOUs."""

import re
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import Field

from nexus.application import categories as category_cases
from nexus.application import category_rules as rule_cases
from nexus.application import memory as memory_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application import wallet_figures as figure_cases
from nexus.application import wallets as wallet_cases
from nexus.channels.web.security import (
    Auth,
    Runtime,
)
from nexus.channels.web.shapes import Model, MoneyOut, TransactionOut, _day_start, _out, _tz, money
from nexus.domain import wallets as wallet_rules
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Category,
    User,
    Wallet,
)

router = APIRouter(prefix="/api")

# --- summary, categories, IOUs --------------------------------------------------------


class TotalOut(Model):
    direction: str
    total: MoneyOut  # home currency, foreign amounts converted at their day's rate
    count: int
    converted: list[MoneyOut]  # foreign originals included in total
    unconverted: list[MoneyOut]  # foreign amounts left out: no rate available


class CategoryTotalOut(Model):
    category_id: UUID | None
    category_name: str | None
    total: MoneyOut
    count: int


class SummaryOut(Model):
    start: date
    end: date
    currency: str
    totals: list[TotalOut]  # money out, then money in; moves between wallets are in neither
    by_category: list[CategoryTotalOut]
    # Over the same period, in the home currency (see ``application/wallet_figures.py``).
    put_away: MoneyOut  # net moved into savings and investment wallets
    saving_rate: float | None  # put_away / money in (0.24 is 24%); null without money in
    total_out: MoneyOut  # spending, plus moved from the main account to anything but a card


@router.get("/summary")
async def summary(
    auth: Auth, web: Runtime, start: date | None = None, end: date | None = None
) -> SummaryOut:
    user = auth.user
    today = web.clock().astimezone(_tz(user)).date()
    first = start or today.replace(day=1)
    last = end or today
    begins, ends = _day_start(user, first), _day_start(user, last) + timedelta(days=1)
    result = await tx_cases.summarize_in_home(web.uow(), web.rates, user, begins, ends)
    # Not only for whole months: the figures hold for any period, and the rate is simply
    # put away over the money in of that same period.
    figures = await figure_cases.wallet_figures(web.uow, web.rates, user, begins, ends)
    return SummaryOut(
        start=first,
        end=last,
        currency=result.currency,
        totals=[
            TotalOut(
                direction=t.direction.value,
                total=money(t.total),
                count=t.count,
                converted=[money(m) for m in t.converted],
                unconverted=[money(m) for m in t.unconverted],
            )
            for t in result.totals
        ],
        by_category=[
            CategoryTotalOut(
                category_id=c.category_id,
                category_name=c.category_name,
                total=money(c.total),
                count=c.count,
            )
            for c in result.spending_by_category
        ],
        put_away=money(figures.put_away),
        saving_rate=float(figures.saving_rate) if figures.saving_rate is not None else None,
        total_out=money(figures.total_out),
    )


class MonthSpendOut(Model):
    month: date  # its first day
    spent: MoneyOut
    to_date: bool  # the current month, so far


class SpendingOut(Model):
    currency: str
    months: list[MonthSpendOut]  # oldest first, ending with this month so far
    last_month_to_date: MoneyOut  # last month's spending up to the same day
    budget: MoneyOut | None  # the overall monthly budget, when one is set


def _month_start(day: date, back: int = 0) -> date:
    index = day.year * 12 + day.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


@router.get("/spending/months")
async def spending_months(
    auth: Auth, web: Runtime, count: Annotated[int, Query(ge=1, le=12)] = 6
) -> SpendingOut:
    """Money out per month in the home currency, for Home's chart: the last ``count``
    months ending with this one so far, last month to the same day, and the overall
    budget."""
    user = auth.user
    today = web.clock().astimezone(_tz(user)).date()
    months = []
    for back in range(count - 1, -1, -1):
        first = _month_start(today, back)
        end = _month_start(today, back - 1) if back else today + timedelta(days=1)
        result = await tx_cases.summarize_in_home(
            web.uow(), web.rates, user, _day_start(user, first), _day_start(user, end)
        )
        months.append(MonthSpendOut(month=first, spent=money(result.out.total), to_date=not back))
    previous = _month_start(today, 1)
    same_day = min(today.day, (_month_start(today) - timedelta(days=1)).day)
    last = await tx_cases.summarize_in_home(
        web.uow(),
        web.rates,
        user,
        _day_start(user, previous),
        _day_start(user, previous.replace(day=same_day) + timedelta(days=1)),
    )
    async with web.uow() as tx:
        budgets = await tx.planning.list_budgets(user.id)
    overall = next(
        (b for b in budgets if b.is_overall and b.limit.currency == user.home_currency), None
    )
    return SpendingOut(
        currency=user.home_currency,
        months=months,
        last_month_to_date=money(last.out.total),
        budget=money(overall.limit) if overall else None,
    )


class CategoryOut(Model):
    id: UUID
    name: str


def category_out(c: Category) -> CategoryOut:
    return CategoryOut(id=c.id, name=c.name)


@router.get("/categories")
async def categories(auth: Auth, web: Runtime) -> list[CategoryOut]:
    cats = await category_cases.list_categories(web.uow(), auth.user.id)
    return [category_out(c) for c in cats]


class CategoryIn(Model):
    name: str = Field(min_length=1, max_length=100)


@router.post("/categories", status_code=201)
async def create_category(body: CategoryIn, auth: Auth, web: Runtime) -> CategoryOut:
    return category_out(await category_cases.create_category(web.uow(), auth.user.id, body.name))


@router.patch("/categories/{category_id}")
async def edit_category(
    category_id: UUID, body: CategoryIn, auth: Auth, web: Runtime
) -> CategoryOut:
    return category_out(
        await category_cases.rename_category(web.uow(), auth.user.id, category_id, body.name)
    )


class MergeIn(Model):
    into_id: UUID


class MergeOut(Model):
    moved: int
    into: CategoryOut


@router.post("/categories/{category_id}/merge")
async def merge_category(category_id: UUID, body: MergeIn, auth: Auth, web: Runtime) -> MergeOut:
    merged = await category_cases.merge_category(
        web.uow(), auth.user.id, category_id, body.into_id, now=web.clock()
    )
    return MergeOut(moved=merged.moved, into=category_out(merged.into))


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: UUID, auth: Auth, web: Runtime, move_to: UUID | None = None
) -> MergeOut:
    """Delete a category; its expenses and rules move to ``move_to`` (default: Other)."""
    deleted = await category_cases.delete_category(
        web.uow(), auth.user.id, category_id, move_to, now=web.clock()
    )
    return MergeOut(moved=deleted.moved, into=category_out(deleted.into))


class WalletOut(Model):
    id: UUID
    name: str
    kind: str
    match_words: list[str]
    # A card's details (all optional, null for other wallets); never more than four digits.
    issuer: str | None = None
    product: str | None = None
    network: str | None = None  # visa, mastercard, amex or other
    last4: str | None = None
    usual: bool = False  # the card new expenses are paid with when none is said


def wallet_out(w: Wallet, usual: UUID | None = None) -> WalletOut:
    """``usual`` is the user's usual card (``User.usual_card_wallet_id``)."""
    return WalletOut(
        id=w.id,
        name=w.name,
        kind=w.kind.value,
        match_words=list(w.match_words),
        issuer=w.issuer,
        product=w.product,
        network=w.network.value if w.network else None,
        last4=w.last4,
        usual=usual is not None and usual == w.id,
    )


class WalletSavedOut(WalletOut):
    # Only present when a card number longer than four digits was given: the rest was
    # dropped. (Left out otherwise: these routes set ``response_model_exclude_unset``.)
    note: str | None = None


def wallet_saved(w: Wallet, user: User, longer: bool) -> WalletSavedOut:
    extra = {"note": wallet_rules.LAST4_KEPT} if longer else {}
    return WalletSavedOut(**wallet_out(w, user.usual_card_wallet_id).model_dump(), **extra)


@router.get("/wallets")
async def wallets(auth: Auth, web: Runtime) -> list[WalletOut]:
    """The user's wallets, The main account first."""
    usual = auth.user.usual_card_wallet_id
    return [wallet_out(w, usual) for w in await wallet_cases.list_wallets(web.uow(), auth.user.id)]


class UsualCardIn(Model):
    wallet_id: UUID | None


@router.put("/wallets/usual-card", status_code=204)
async def set_usual_card(body: UsualCardIn, auth: Auth, web: Runtime) -> Response:
    """The card new expenses are paid with when none is said (``null`` for none). 422 if it
    isn't the user's wallet, or is an investment or savings wallet."""
    await wallet_cases.set_usual_card(web.uow(), auth.user.id, body.wallet_id)
    return Response(status_code=204)


class WalletSpendOut(Model):
    month: str  # YYYY-MM
    total: MoneyOut  # home currency
    count: int


@router.get("/wallets/{wallet_id}/spend")
async def wallet_spend(
    wallet_id: UUID, auth: Auth, web: Runtime, month: Annotated[str | None, Query()] = None
) -> WalletSpendOut:
    """Confirmed money out paid with the wallet in a month (this one by default, in the
    user's time zone), in the home currency, converted as in the summaries. A card's
    spending, as it was charged: what friends paid back on a split is not taken off."""
    user = auth.user
    today = web.clock().astimezone(_tz(user)).date()
    first = _month_of(month, today)
    spent = await wallet_cases.spend_with(
        web.uow(),
        web.rates,
        user,
        wallet_id,
        _day_start(user, first),
        _day_start(user, _month_start(first, -1)),
    )
    return WalletSpendOut(month=f"{first:%Y-%m}", total=money(spent.total), count=spent.count)


def _month_of(value: str | None, today: date) -> date:
    """The first day of the month ``value`` (YYYY-MM) names, this month if none; refused if
    it isn't a month or is still to come."""
    if value is None:
        return today.replace(day=1)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise InvalidInput("month looks like 2026-09")
    first = date(int(value[:4]), int(value[5:]), 1)
    if first > today.replace(day=1):
        raise InvalidInput("that month hasn't started yet")
    return first


class LikelyMoveOut(Model):
    transaction: TransactionOut
    wallet: WalletOut | None  # where it would go; null when only the pattern suggests a move
    reason: str


@router.get("/wallets/likely-moves")
async def likely_moves(auth: Auth, web: Runtime) -> list[LikelyMoveOut]:
    """Entries from the last six months that may really have been moves. Nothing is
    changed: convert one with ``POST /transactions/{id}/move``."""
    found = await wallet_cases.likely_moves(web.uow(), auth.user.id, now=web.clock())
    return [
        LikelyMoveOut(
            transaction=await _out(web, auth.user, f.transaction),
            wallet=wallet_out(f.wallet) if f.wallet else None,
            reason=f.reason,
        )
        for f in found
    ]


class WalletIn(Model):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(max_length=20)
    match_words: list[str] = Field(default=[], max_length=wallet_cases.MAX_MATCH_WORDS)
    # A card's details, all optional. More than four digits of a card number are cut to the
    # last four (and the response says so); anything but digits is refused.
    issuer: str | None = Field(None, max_length=wallet_rules.MAX_ISSUER)
    product: str | None = Field(None, max_length=wallet_rules.MAX_PRODUCT)
    network: str | None = Field(None, max_length=20)
    last4: str | None = Field(None, max_length=40)


@router.post("/wallets", status_code=201, response_model_exclude_unset=True)
async def create_wallet(body: WalletIn, auth: Auth, web: Runtime) -> WalletSavedOut:
    digits = wallet_rules.clean_last4(body.last4)
    made = await wallet_cases.add_wallet(
        web.uow(),
        auth.user.id,
        body.name,
        body.kind,
        body.match_words,
        issuer=body.issuer,
        product=body.product,
        network=body.network,
        last4=digits.digits,
    )
    return wallet_saved(made, auth.user, digits.longer)


class WalletPatch(Model):
    name: str | None = Field(None, min_length=1, max_length=100)
    kind: str | None = Field(None, max_length=20)
    match_words: list[str] | None = Field(None, max_length=wallet_cases.MAX_MATCH_WORDS)
    # Card details: null clears one, leaving it out keeps it.
    issuer: str | None = Field(None, max_length=wallet_rules.MAX_ISSUER)
    product: str | None = Field(None, max_length=wallet_rules.MAX_PRODUCT)
    network: str | None = Field(None, max_length=20)
    last4: str | None = Field(None, max_length=40)


@router.patch("/wallets/{wallet_id}", response_model_exclude_unset=True)
async def edit_wallet(
    wallet_id: UUID, body: WalletPatch, auth: Auth, web: Runtime
) -> WalletSavedOut:
    given = body.model_fields_set
    digits = wallet_rules.clean_last4(body.last4 if "last4" in given else None)
    details: dict[str, Any] = {
        field: getattr(body, field) for field in ("issuer", "product", "network") if field in given
    }
    if "last4" in given:
        details["last4"] = digits.digits
    updated = await wallet_cases.update_wallet(
        web.uow(),
        auth.user.id,
        wallet_id,
        name=body.name if "name" in given else None,
        kind=body.kind if "kind" in given else None,
        match_words=body.match_words if "match_words" in given else None,
        **details,
    )
    return wallet_saved(updated, auth.user, digits.longer)


class WalletDeletedOut(Model):
    moved: int  # moves now pointing at ``into``
    removed: int  # moves between the two wallets, dropped as they'd be from a wallet to itself
    bills: int  # scheduled payments to it, now pointing at ``into``
    into: WalletOut | None  # null when the wallet had no moves or scheduled payments


@router.delete("/wallets/{wallet_id}")
async def delete_wallet(
    wallet_id: UUID, auth: Auth, web: Runtime, move_to: UUID | None = None
) -> WalletDeletedOut:
    """Delete a wallet. Its moves, if any, need ``move_to``: another wallet to point at."""
    deleted = await wallet_cases.delete_wallet(
        web.uow(), auth.user.id, wallet_id, move_to, now=web.clock()
    )
    return WalletDeletedOut(
        moved=deleted.moved,
        removed=deleted.removed,
        bills=deleted.bills,
        into=wallet_out(deleted.into) if deleted.into else None,
    )


class WalletPreviewOut(Model):
    moved: int  # moves that would point at ``move_to``
    removed: int  # moves between the two wallets, which would be dropped
    bills: int  # scheduled payments to it that would point at ``move_to``


@router.get("/wallets/{wallet_id}/delete-preview")
async def delete_wallet_preview(
    wallet_id: UUID, auth: Auth, web: Runtime, move_to: UUID | None = None
) -> WalletPreviewOut:
    """What deleting the wallet (with the same ``move_to``) would do, without doing it."""
    preview = await wallet_cases.preview_delete_wallet(web.uow(), auth.user.id, wallet_id, move_to)
    return WalletPreviewOut(moved=preview.moved, removed=preview.removed, bills=preview.bills)


class RuleOut(Model):
    id: UUID
    pattern: str
    category_id: UUID
    category_name: str
    explanation: str


def rule_out(view: rule_cases.RuleView) -> RuleOut:
    return RuleOut(
        id=view.rule.id,
        pattern=view.rule.pattern,
        category_id=view.category.id,
        category_name=view.category.name,
        explanation=view.rule.explanation,
    )


@router.get("/category-rules")
async def category_rules(auth: Auth, web: Runtime) -> list[RuleOut]:
    return [rule_out(v) for v in await rule_cases.list_rules(web.uow(), auth.user.id)]


class RuleIn(Model):
    pattern: str = Field(min_length=1, max_length=100)
    category_id: UUID


@router.put("/category-rules", status_code=204)
async def set_category_rule(body: RuleIn, auth: Auth, web: Runtime) -> None:
    """Add a rule, or change the category of the rule for this pattern."""
    await rule_cases.set_rule(web.uow(), auth.user, body.pattern, body.category_id, now=web.clock())


class AcceptRuleIn(Model):
    transaction_id: UUID


@router.post("/category-rules/accept", status_code=204)
async def accept_rule(body: AcceptRuleIn, auth: Auth, web: Runtime) -> None:
    """The user accepted the rule offered after correcting this transaction."""
    await rule_cases.accept_suggestion(web.uow(), auth.user, body.transaction_id, now=web.clock())


@router.delete("/category-rules/{rule_id}", status_code=204)
async def remove_category_rule(rule_id: UUID, auth: Auth, web: Runtime) -> None:
    await rule_cases.remove_rule(web.uow(), auth.user.id, rule_id, now=web.clock())


# --- what Nexus remembers ------------------------------------------------------------


class MemoryOut(Model):
    id: UUID
    kind: str
    text: str
    happened_on: date | None
    updated_at: datetime


@router.get("/memories")
async def memories(auth: Auth, web: Runtime) -> list[MemoryOut]:
    found = await memory_cases.list_memories(web.uow(), auth.user.id)
    return [
        MemoryOut(
            id=m.id,
            kind=m.kind.value,
            text=m.text,
            happened_on=m.happened_on,
            updated_at=m.updated_at,
        )
        for m in found
    ]


@router.delete("/memories/{memory_id}", status_code=204)
async def forget_memory(memory_id: UUID, auth: Auth, web: Runtime) -> None:
    await memory_cases.forget(web.uow(), auth.user.id, memory_id)


@router.delete("/memories", status_code=204)
async def forget_everything(auth: Auth, web: Runtime) -> None:
    await memory_cases.forget_all(web.uow(), auth.user.id)


@router.get("/transactions/{transaction_id}/category-explanation")
async def category_explanation(transaction_id: UUID, auth: Auth, web: Runtime) -> dict[str, str]:
    result = await rule_cases.explain(web.uow(), auth.user.id, transaction_id)
    return {"text": result.text}


class IouOut(Model):
    split_id: UUID
    transaction_id: UUID
    participant_name: str
    share: MoneyOut
    outstanding: MoneyOut
    expense_occurred_at: datetime


@router.get("/ious")
async def ious(auth: Auth, web: Runtime) -> list[IouOut]:
    open_ious = await split_cases.list_open_ious(web.uow(), auth.user.id)
    return [
        IouOut(
            split_id=i.split.id,
            transaction_id=i.split.transaction_id,
            participant_name=i.split.participant_name,
            share=money(i.split.share),
            outstanding=money(i.outstanding),
            expense_occurred_at=i.expense_occurred_at,
        )
        for i in open_ious
    ]


@router.post("/ious/{split_id}/repaid", status_code=204)
async def iou_repaid(split_id: UUID, auth: Auth, web: Runtime) -> None:
    """Paid back in full, today; deleting the money-in transaction undoes it."""
    await split_cases.mark_repaid(web.uow, auth.user.id, split_id, now=web.clock())
