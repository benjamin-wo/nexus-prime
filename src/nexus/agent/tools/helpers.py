"""Parsers and resolvers shared by the tools."""

from dataclasses import replace
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.agent.confirmation import Ask, entry_text
from nexus.agent.tools.core import ToolContext
from nexus.application import categories as category_cases
from nexus.application import transactions as tx_cases
from nexus.application import wallets as wallet_cases
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import (
    Category,
    Direction,
    Transaction,
    Wallet,
    WalletKind,
)
from nexus.domain.money import Money


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
    cats = await category_cases.list_categories(ctx.uow(), ctx.user.id)
    return {c.id: c for c in cats}


async def resolve_category(ctx: ToolContext, name: str | None) -> UUID | None:
    if name is None:
        return None
    found = await category_cases.list_categories(ctx.uow(), ctx.user.id)
    for category in found:
        if category.name.casefold() == name.casefold():
            return category.id
    options = ", ".join(c.name for c in found)
    raise InvalidInput(f"unknown category {name!r}; choose one of: {options}")


async def guess_category(ctx: ToolContext, name: str | None) -> UUID | None:
    """A best-guess category by name; an unknown one is simply no guess."""
    try:
        return await resolve_category(ctx, name)
    except InvalidInput:
        return None


def describe(
    tx: Transaction,
    cats: dict[UUID, Category],
    tz: ZoneInfo,
    wallets: dict[UUID, Wallet] | None = None,
) -> str:
    """One line for the model. A transfer shows where the money went
    ("800.00 SGD → IBKR (transfer)"), with no sign, and where it came from unless that's the
    main account; pass ``wallets`` (see ``wallet_map``) to name them."""
    parts = [tx.occurred_at.astimezone(tz).date().isoformat()]
    if tx.is_move:
        parts.append(_move_text(tx, wallets or {}))
    else:
        parts.append(f"{'-' if tx.direction is Direction.OUT else '+'}{tx.amount}")
    if tx.counterparty:
        parts.append(tx.counterparty)
    if tx.category_id and tx.category_id in cats:
        parts.append(cats[tx.category_id].name)
    paid_with = (wallets or {}).get(tx.paid_with_wallet_id) if tx.paid_with_wallet_id else None
    if paid_with is not None:
        parts.append(f"paid with {paid_with.name}")
    if tx.notes:
        parts.append(f"note: {tx.notes}")
    if tx.status.value == "pending":
        parts.append("pending")
    if tx.is_deleted:
        parts.append("deleted")
    return " · ".join(parts) + f" [id {tx.id}]"


def _move_text(tx: Transaction, wallets: dict[UUID, Wallet]) -> str:
    origin = wallets.get(tx.from_wallet_id) if tx.from_wallet_id else None
    target = wallets.get(tx.to_wallet_id) if tx.to_wallet_id else None
    text = f"{tx.amount}"
    if origin is None or origin.kind is not WalletKind.SPENDING:
        text += f" {origin.name if origin else 'another wallet'}"
    text += f" → {target.name if target else 'another wallet'} (transfer)"
    if tx.received_amount is not None:
        text += f", {tx.received_amount} received"
    return text


async def wallet_map(ctx: ToolContext) -> dict[UUID, Wallet]:
    wallets = await wallet_cases.list_wallets(ctx.uow(), ctx.user.id)
    return {w.id: w for w in wallets}


def find_wallet(wallets: list[Wallet], name: str) -> Wallet | None:
    """A wallet by name in any case ("my" and "the" in front are ignored), else the one
    wallet that has the text among its match words."""
    wanted = name.strip().casefold()
    for prefix in ("my ", "the "):
        wanted = wanted.removeprefix(prefix)
    for w in wallets:
        if w.name.casefold() == wanted:
            return w
    tied = [w for w in wallets if wanted in {m.casefold() for m in w.match_words}]
    return tied[0] if len(tied) == 1 else None


def wallet_list(wallets: list[Wallet]) -> str:
    return ", ".join(
        w.name if w.kind is WalletKind.SPENDING else f"{w.name} ({w.kind.value})" for w in wallets
    )


async def resolve_wallet(ctx: ToolContext, name: str) -> Wallet:
    """One of the user's wallets by name. An unknown one is for the model to ask about:
    it never creates a wallet unasked."""
    wallets = await wallet_cases.list_wallets(ctx.uow(), ctx.user.id)
    found = find_wallet(wallets, name)
    if found is None:
        raise NotFound(
            f"there's no wallet called {name!r}. The user's wallets: {wallet_list(wallets)}. "
            "Ask which one they mean, or offer to add it as a new wallet (the wallets skill); "
            "don't add one unless they say yes."
        )
    return found


async def main_account(ctx: ToolContext) -> Wallet:
    """The user's main account, found by its kind: it keeps working if they renamed it."""
    wallets = await wallet_cases.list_wallets(ctx.uow(), ctx.user.id)
    return next(w for w in wallets if w.kind is WalletKind.SPENDING)


def _card_shown(ctx: ToolContext, tx: Transaction) -> Transaction:
    """The transaction as the model should see it: without which card paid while the user
    doesn't track cards (what is stored stays)."""
    if ctx.user.track_cards or tx.paid_with_wallet_id is None:
        return tx
    return replace(tx, paid_with_wallet_id=None)


async def show(ctx: ToolContext, tx: Transaction) -> str:
    """``describe`` for one transaction, naming the wallets if it's a move or was paid
    with one."""
    tx = _card_shown(ctx, tx)
    wallets = await wallet_map(ctx) if tx.is_move or tx.paid_with_wallet_id else None
    return describe(tx, await category_map(ctx), ctx.tz, wallets)


async def ask_about(ctx: ToolContext, tx: Transaction, action: str, detail: str = "") -> str:
    """What to ask the user about an entry: the readable form of ``show`` (no id, note or
    sign, a short date). A move keeps its own line."""
    if tx.is_move:
        return f"{action} {(await show(ctx, tx)).split(' [id')[0]}{detail}?"
    category = (await category_map(ctx)).get(tx.category_id) if tx.category_id else None
    day = tx.occurred_at.astimezone(ctx.tz).date()
    return Ask(
        action, entry_text(tx, day, ctx.today(), category.name if category else None), detail
    )


async def show_all(ctx: ToolContext, txs: list[Transaction]) -> list[str]:
    txs = [_card_shown(ctx, tx) for tx in txs]
    named = any(tx.is_move or tx.paid_with_wallet_id for tx in txs)
    wallets = await wallet_map(ctx) if named else None
    cats = await category_map(ctx)
    return [describe(tx, cats, ctx.tz, wallets) for tx in txs]


async def _load(ctx: ToolContext, transaction_id: str) -> Transaction:
    return await tx_cases.get_transaction(ctx.uow(), ctx.user.id, parse_id(transaction_id))


NO_CARD = frozenset({"none", "no card", "nothing", "clear"})


async def resolve_paid_with(ctx: ToolContext, name: str) -> Wallet:
    """The user's wallet an expense was paid with, by what they called it (a name, issuer,
    product or last four digits). An unknown or ambiguous one is for the model to ask
    about: it never creates a wallet unasked."""
    wallets = await wallet_cases.list_wallets(ctx.uow(), ctx.user.id)
    return wallet_cases.pick_paying_wallet(wallets, name)
