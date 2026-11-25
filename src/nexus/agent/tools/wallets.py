"""Tools for wallets, moves between them, the usual card and category rules."""

from typing import Literal

from pydantic import Field

from nexus.agent.tools.core import Args, IdArgs, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import (
    NO_CARD,
    _load,
    main_account,
    parse_day,
    parse_id,
    parse_money,
    resolve_category,
    resolve_paid_with,
    resolve_wallet,
    show,
    wallet_list,
)
from nexus.application import category_rules as rule_cases
from nexus.application import wallets as wallet_cases
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Direction,
    Source,
    Transaction,
    Wallet,
    WalletKind,
)
from nexus.domain.money import Money
from nexus.domain.rules import clean_pattern
from nexus.domain.wallets import LAST4_KEPT, clean_last4


class LogMoveArgs(Args):
    amount: str = Field(description="Amount that left, e.g. '800'. Never guess it.")
    currency: str | None = Field(
        None, description="ISO code of that amount; omit for the home currency"
    )
    to_wallet: str = Field(
        description="The wallet the money went to, by name, as the snapshot lists them "
        "(e.g. 'IBKR'). Never invent one."
    )
    from_wallet: str | None = Field(
        None,
        description="The wallet it came from; omit for the Main account unless the user says",
    )
    date: str | None = Field(None, description="YYYY-MM-DD, 'today' or 'yesterday'; omit for now")
    received_amount: str | None = Field(
        None, description="Only when what arrived differs from amount (another currency, a fee)"
    )
    received_currency: str | None = Field(
        None, description="ISO code of received_amount; omit for the same as amount"
    )
    note: str | None = Field(None, description="What it was for, if the user said")


async def _move_ends(ctx: ToolContext, a: LogMoveArgs) -> tuple[Wallet, Wallet]:
    if a.from_wallet is None:
        origin = await main_account(ctx)
    else:
        origin = await resolve_wallet(ctx, a.from_wallet)
    target = await resolve_wallet(ctx, a.to_wallet)
    if origin.id == target.id:
        raise InvalidInput("a transfer needs two different wallets")
    return origin, target


def _received(ctx: ToolContext, a: LogMoveArgs, sent: Money) -> Money | None:
    if a.received_amount is None:
        return None
    return parse_money(ctx, a.received_amount, a.received_currency or sent.currency)


async def _describe_move(ctx: ToolContext, a: LogMoveArgs) -> str:
    origin, target = await _move_ends(ctx, a)
    sent = parse_money(ctx, a.amount, a.currency)
    got = _received(ctx, a, sent)
    arrives = f" ({got} arrives)" if got else ""
    when = f" on {parse_day(ctx, a.date).astimezone(ctx.tz):%-d %b}" if a.date else ""
    if origin.kind is WalletKind.SPENDING:
        counts = "spending"
    elif target.kind is WalletKind.SPENDING:
        counts = "income"
    else:
        counts = "spending or income"
    return (
        f"Log a transfer of {sent} from {origin.name} to {target.name}{arrives}{when}? "
        f"It won't count as {counts}."
    )


async def _log_move(ctx: ToolContext, a: LogMoveArgs) -> ToolResult:
    origin, target = await _move_ends(ctx, a)
    sent = parse_money(ctx, a.amount, a.currency)
    tx = await wallet_cases.log_move(
        ctx.uow(),
        ctx.user.id,
        amount=sent,
        to_wallet_id=target.id,
        from_wallet_id=origin.id,
        occurred_at=parse_day(ctx, a.date),
        received_amount=_received(ctx, a, sent),
        notes=a.note,
        source=Source.TEXT,
    )
    return ToolResult(
        f"Logged a transfer (not spending or income): {await show(ctx, tx)}", wrote=True
    )


class MarkMoveArgs(Args):
    transaction_id: str = Field(description="From find_transactions")
    wallet: str = Field(
        description="The other wallet: where the money went (for an expense) or where it "
        "came from (for money in). Not the Main account."
    )


async def _mark_pair(ctx: ToolContext, a: MarkMoveArgs) -> tuple[Transaction, Wallet]:
    tx = await _load(ctx, a.transaction_id)
    if tx.is_move:
        raise InvalidInput("this is already a transfer")
    return tx, await resolve_wallet(ctx, a.wallet)


async def _describe_mark_move(ctx: ToolContext, a: MarkMoveArgs) -> str:
    tx, wallet = await _mark_pair(ctx, a)
    head = (await show(ctx, tx)).split(" [id")[0]
    main = (await main_account(ctx)).name
    if tx.direction is Direction.OUT:
        return (
            f"Turn {head} into a transfer from {main} to {wallet.name}? It will stop counting "
            "as spending, and it loses its category."
        )
    return (
        f"Turn {head} into a transfer from {wallet.name} to {main}? It will stop counting "
        "as income, and it loses its category."
    )


async def _mark_as_move(ctx: ToolContext, a: MarkMoveArgs) -> ToolResult:
    tx, wallet = await _mark_pair(ctx, a)
    moved = await wallet_cases.mark_as_move(ctx.uow(), ctx.user.id, tx.id, wallet.id)
    return ToolResult(f"Now a transfer: {await show(ctx, moved)}", wrote=True)


async def _list_wallets(ctx: ToolContext, _: NoArgs) -> ToolResult:
    lines = []
    for w in await wallet_cases.list_wallets(ctx.uow(), ctx.user.id):
        what = (
            "the main account the budget watches" if w.kind is WalletKind.SPENDING else w.kind.value
        )
        card = _card_text(w)
        words = f"; match words: {', '.join(w.match_words)}" if w.match_words else ""
        is_usual = ctx.user.track_cards and w.id == ctx.user.usual_card_wallet_id
        usual = "; the usual card" if is_usual else ""
        lines.append(f"{w.name} ({what}{card}{words}{usual})")
    return ToolResult("\n".join(lines))


def _card_text(w: Wallet) -> str:
    """A card's details for the model: "; Citi PremierMiles, visa, ending 4321"."""
    bits = [
        " ".join(p for p in (w.issuer, w.product) if p),
        w.network.value if w.network else "",
        f"ending {w.last4}" if w.last4 else "",
    ]
    text = ", ".join(b for b in bits if b)
    return f"; {text}" if text else ""


async def _find_likely_moves(ctx: ToolContext, _: NoArgs) -> ToolResult:
    found = await wallet_cases.likely_moves(ctx.uow(), ctx.user.id, now=ctx.now)
    if not found:
        return ToolResult(
            "No entries from the last six months look like transfers between wallets."
        )
    lines = []
    for item in found:
        wallet = f" → {item.wallet.name}" if item.wallet else " (which wallet? ask the user)"
        lines.append(f"{await show(ctx, item.transaction)}{wallet}: {item.reason}")
    return ToolResult(
        f"{len(found)} entries that may really have been transfers (nothing has been changed):\n"
        + "\n".join(lines)
    )


type NewKind = Literal["investment", "savings", "card", "other"]


class AddWalletArgs(Args):
    name: str = Field(description="What to call it, e.g. 'IBKR' or 'Emergency fund'")
    kind: NewKind = Field(
        description="investment: a broker or fund; savings: savings or a fixed deposit; "
        "card: a credit card (paying its bill is a transfer); other: anything else"
    )
    match_words: list[str] | None = Field(
        None, description="Other names the user or their statements use for it"
    )
    issuer: str | None = Field(
        None, description="For a card: who issued it, e.g. 'Citi' (at most 40 characters)"
    )
    product: str | None = Field(
        None, description="For a card: its product, e.g. 'PremierMiles' (at most 60 characters)"
    )
    network: Literal["visa", "mastercard", "amex", "other"] | None = Field(
        None, description="For a card: its network"
    )
    last4: str | None = Field(
        None,
        description="For a card: the LAST 4 digits only, as digits. Never pass more than "
        "four; if the user gave a whole number, give just its last four.",
    )


def _kept_four(value: str | None) -> tuple[str | None, str]:
    """The last four digits of what the user gave, and a sentence for the reply when more
    than four were given (they are dropped, never kept)."""
    digits = clean_last4(value)
    return digits.digits, (f" {LAST4_KEPT}" if digits.longer else "")


async def _find_wallet(ctx: ToolContext, name: str) -> Wallet | None:
    wallets = await wallet_cases.list_wallets(ctx.uow(), ctx.user.id)
    return next((w for w in wallets if w.name.casefold() == name.strip().casefold()), None)


async def _add_wallet(ctx: ToolContext, a: AddWalletArgs) -> ToolResult:
    existing = await _find_wallet(ctx, a.name)
    if existing is not None:
        return ToolResult(f"There's already a wallet called {existing.name}.")
    last4, kept = _kept_four(a.last4)
    made = await wallet_cases.add_wallet(
        ctx.uow(),
        ctx.user.id,
        a.name,
        a.kind,
        a.match_words or (),
        issuer=a.issuer,
        product=a.product,
        network=a.network,
        last4=last4,
    )
    return ToolResult(
        f"Added the wallet {made.name} ({made.kind.value}{_card_text(made)}).{kept}", wrote=True
    )


class UpdateWalletArgs(Args):
    wallet: str = Field(description="The wallet's current name")
    new_name: str | None = Field(None, description="What to call it instead")
    kind: NewKind | None = Field(None, description="Change what kind of wallet it is")
    match_words: list[str] | None = Field(
        None, description="Replaces its other names; an empty list clears them"
    )
    issuer: str | None = Field(None, description="For a card: who issued it, e.g. 'Citi'")
    product: str | None = Field(None, description="For a card: its product, e.g. 'PremierMiles'")
    network: Literal["visa", "mastercard", "amex", "other"] | None = Field(
        None, description="For a card: its network"
    )
    last4: str | None = Field(
        None,
        description="For a card: the LAST 4 digits only, as digits. Never pass more than four.",
    )


async def _update_wallet(ctx: ToolContext, a: UpdateWalletArgs) -> ToolResult:
    details = {k: v for k, v in (("issuer", a.issuer), ("product", a.product),
                                 ("network", a.network)) if v is not None}  # fmt: skip
    last4, kept = _kept_four(a.last4)
    if last4 is not None:
        details["last4"] = last4
    if a.new_name is None and a.kind is None and a.match_words is None and not details:
        raise InvalidInput("say what to change: the name, the kind, the match words or the card")
    current = await resolve_wallet(ctx, a.wallet)
    if a.new_name is not None:
        clash = await _find_wallet(ctx, a.new_name)
        if clash is not None and clash.id != current.id:
            raise InvalidInput(f"there's already a wallet called {clash.name}")
    updated = await wallet_cases.update_wallet(
        ctx.uow(),
        ctx.user.id,
        current.id,
        name=a.new_name,
        kind=a.kind,
        match_words=a.match_words,
        **details,
    )
    changes = []
    if updated.name != current.name:
        changes.append(f"renamed to {updated.name}")
    if updated.kind is not current.kind:
        changes.append(f"its kind is now {updated.kind.value}")
    if updated.match_words != current.match_words:
        changes.append("match words: " + (", ".join(updated.match_words) or "none"))
    if _card_text(updated) != _card_text(current):
        changes.append("card" + (_card_text(updated) or ": no details"))
    done = ", ".join(changes) or "nothing to change"
    return ToolResult(f"Updated {current.name}: {done}.{kept}", wrote=bool(changes))


class UsualCardArgs(Args):
    wallet: str = Field(
        description="The card or wallet the user usually pays with, as they named it "
        "('citi', 'my DBS card'); 'none' to have no usual card"
    )


CARDS_OFF = (
    "The user isn't tracking which card paid (simple mode), so no usual card is saved. If they "
    'want to, they can turn on "Track which card paid" in Settings. Don\'t ask which card.'
)


async def _set_usual_card(ctx: ToolContext, a: UsualCardArgs) -> ToolResult:
    if not ctx.user.track_cards:
        return ToolResult(CARDS_OFF)
    if a.wallet.strip().casefold() in NO_CARD:
        await wallet_cases.set_usual_card(ctx.uow(), ctx.user.id, None)
        return ToolResult(
            "No usual card now: expenses aren't paid with a card unless said.", wrote=True
        )
    card = await resolve_paid_with(ctx, a.wallet)
    await wallet_cases.set_usual_card(ctx.uow(), ctx.user.id, card.id)
    return ToolResult(
        f"{card.name} is now the usual card: expenses logged in chat, on the web or from a "
        "photo are paid with it unless another is said. Imports and emails aren't.",
        wrote=True,
    )


class DeleteWalletArgs(Args):
    wallet: str = Field(description="The wallet to delete; not the Main account")
    move_to: str | None = Field(
        None,
        description="Another wallet that its transfers will point at instead; needed only "
        "if it has transfers",
    )


async def _delete_plan(ctx: ToolContext, a: DeleteWalletArgs) -> wallet_cases.WalletDeleted:
    """What deleting would do, or the reason it can't, for the model to act on."""
    wallet = await resolve_wallet(ctx, a.wallet)
    into = await resolve_wallet(ctx, a.move_to) if a.move_to else None
    try:
        return await wallet_cases.preview_delete_wallet(
            ctx.uow(), ctx.user.id, wallet.id, into.id if into else None
        )
    except InvalidInput as exc:
        if into is None and "has transfers" in str(exc):
            wallets = await wallet_cases.list_wallets(ctx.uow(), ctx.user.id)
            others = wallet_list([w for w in wallets if w.id != wallet.id])
            raise InvalidInput(
                f"{wallet.name} has transfers, so they need another wallet to point at "
                f"({others}). Ask the user which."
            ) from exc
        raise


def _moves(n: int) -> str:
    return f"{n} transfer{'' if n == 1 else 's'}"


def _scheduled(n: int) -> str:
    return f"{n} scheduled payment{'' if n == 1 else 's'}"


async def _describe_delete_wallet(ctx: ToolContext, a: DeleteWalletArgs) -> str:
    plan = await _delete_plan(ctx, a)
    if plan.into is None:
        return f"Delete the wallet {plan.wallet.name}? It has no transfers. This can't be undone."
    into = plan.into.name
    text = (
        f"Delete the wallet {plan.wallet.name}? {_moves(plan.moved)} will point at {into} instead"
    )
    if plan.bills:
        text += f", and {_scheduled(plan.bills)} to it will transfer money to {into} instead"
    if plan.removed:
        text += (
            f", and {_moves(plan.removed)} between the two will be removed, since both "
            f"ends would be {into}"
        )
    return text + ". This can't be undone."


async def _delete_wallet(ctx: ToolContext, a: DeleteWalletArgs) -> ToolResult:
    await _delete_plan(ctx, a)  # the same checks, with the same messages
    wallet = await resolve_wallet(ctx, a.wallet)
    into = await resolve_wallet(ctx, a.move_to) if a.move_to else None
    done = await wallet_cases.delete_wallet(
        ctx.uow(), ctx.user.id, wallet.id, into.id if into else None, now=ctx.now
    )
    if done.into is None:
        return ToolResult(f"Deleted the wallet {wallet.name}.", wrote=True)
    verb = "points" if done.moved == 1 else "point"
    text = f"Deleted the wallet {wallet.name}. {_moves(done.moved)} now {verb} at {done.into.name}"
    if done.bills:
        text += f"; {_scheduled(done.bills)} to it now transfer money to {done.into.name}"
    if done.removed:
        text += f"; {_moves(done.removed)} between the two removed"
    return ToolResult(text + ".", wrote=True)


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


SPECS: list[ToolSpec] = [
    ToolSpec(
        "log_move",
        "Record a transfer the user made between their own wallets: into an investment or "
        "savings wallet, a credit card bill paid from the Main account, or back out to it. "
        "Never spending and never income. Only when the amount is stated and both "
        "wallets are the user's own (an unknown one: ask, don't invent). Nexus only "
        "records; it never moves money. Asks the user to confirm.",
        LogMoveArgs,
        _log_move,
        confirm=_describe_move,
    ),
    ToolSpec(
        "mark_as_move",
        "Turn an entry already logged into a transfer between wallets: an expense that was "
        "money put into savings or an investment, or money in that was a withdrawal from "
        "one. Find its id with find_transactions first. Asks the user to confirm.",
        MarkMoveArgs,
        _mark_as_move,
        confirm=_describe_mark_move,
    ),
    ToolSpec(
        "list_wallets",
        "The user's wallets (Main account, Cash, investment, savings, card, other), a card's "
        "details, their match words and the usual card. Read-only.",
        NoArgs,
        _list_wallets,
    ),
    ToolSpec(
        "find_likely_moves",
        "Finds spending that was really a transfer between the user's own wallets (savings, "
        "IBKR, a card payment, top-ups): entries from the last six months that name a "
        "wallet's match words, or are the same amount to the same payee every month. Use "
        "it for 'did I log transfers to my own accounts as spending?', 'which expenses are "
        "really transfers or top-ups?' and 'anything that should be a transfer?'. Do not hunt "
        "with find_transactions keywords for this. Read-only; offer mark_as_move for each, "
        "which asks the user to confirm.",
        NoArgs,
        _find_likely_moves,
    ),
    ToolSpec(
        "add_wallet",
        "Add a wallet: a place the user keeps money, such as a broker, savings or a credit "
        "card. Only when the user says to add one. A wallet is a label; no balance is kept. "
        "A card can have its issuer, product, network and last 4 digits ('add my Citi "
        "PremierMiles card ending 1234'); never more than 4 digits are kept.",
        AddWalletArgs,
        _add_wallet,
    ),
    ToolSpec(
        "update_wallet",
        "Rename a wallet, change its kind, replace its match words or change a card's "
        "issuer, product, network or last 4 digits.",
        UpdateWalletArgs,
        _update_wallet,
    ),
    ToolSpec(
        "set_usual_card",
        "Set the card or wallet the user usually pays with ('I usually pay with my Citi "
        "card'), so new expenses are paid with it unless another is said; 'none' clears "
        "it. Saves at once.",
        UsualCardArgs,
        _set_usual_card,
    ),
    ToolSpec(
        "delete_wallet",
        "Delete a wallet (never the Main account). Its transfers point at another wallet "
        "instead; transfers between the two are removed. Can't be undone. Asks the user "
        "to confirm.",
        DeleteWalletArgs,
        _delete_wallet,
        confirm=_describe_delete_wallet,
    ),
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
]

READ_ONLY: frozenset[str] = frozenset(
    {"explain_category", "find_likely_moves", "list_category_rules", "list_wallets"}
)
