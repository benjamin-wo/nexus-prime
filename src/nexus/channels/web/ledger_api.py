"""Web API: transactions, moves, bulk edits, undo and the CSV export."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import Field

from nexus.application import categories as category_cases
from nexus.application import category_rules as rule_cases
from nexus.application import duplicates as duplicate_cases
from nexus.application import receipts as receipt_cases
from nexus.application import transactions as tx_cases
from nexus.application import wallets as wallet_cases
from nexus.application.ports import LedgerQuery, SortField
from nexus.channels.web.csv_export import to_csv
from nexus.channels.web.security import (
    Auth,
    Authed,
    Runtime,
    WebRuntime,
)
from nexus.channels.web.shapes import (
    Model,
    MoneyOut,
    TransactionOut,
    _conversions,
    _day_start,
    _out,
    _tz,
    _wallets_of,
    _when,
    money,
    tx_out,
)
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import (
    Direction,
    Source,
    Transaction,
    TransactionStatus,
)
from nexus.domain.money import Money

router = APIRouter(prefix="/api")

EXPORT_LIMIT = 10_000


# --- ledger ---------------------------------------------------------------------------


class PageOut(Model):
    items: list[TransactionOut]
    total: int


def _query(
    auth: Authed,
    direction: Direction | None,
    start: date | None,
    end: date | None,
    category_id: UUID | None,
    uncategorized: bool,
    search: str | None,
    status: TransactionStatus | None,
    source: Source | None,
    include_deleted: bool,
    only_deleted: bool,
    sort: SortField,
    descending: bool,
    limit: int,
    offset: int,
    paid_with: str | None = None,
) -> LedgerQuery:
    user = auth.user
    paid_with_id, without = _paid_with_filter(paid_with)
    return LedgerQuery(
        direction=direction,
        start=_day_start(user, start) if start else None,
        end=_day_start(user, end) + timedelta(days=1) if end else None,
        category_id=category_id,
        uncategorized=uncategorized,
        search=search or None,
        status=status,
        source=source,
        paid_with_wallet_id=paid_with_id,
        without_paid_with=without,
        include_deleted=include_deleted,
        only_deleted=only_deleted,
        sort=sort,
        descending=descending,
        limit=limit,
        offset=offset,
    )


def _paid_with_filter(value: str | None) -> tuple[UUID | None, bool]:
    """``paid_with=<wallet id>`` or ``paid_with=none`` (expenses paid with nothing)."""
    if value is None:
        return None, False
    if value.casefold() == "none":
        return None, True
    try:
        return UUID(value), False
    except ValueError:
        raise InvalidInput("paid_with is a wallet id or none") from None


@router.get("/transactions")
async def list_transactions(
    auth: Auth,
    web: Runtime,
    direction: Direction | None = None,
    start: date | None = None,
    end: date | None = None,
    category_id: UUID | None = None,
    uncategorized: bool = False,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status: TransactionStatus | None = None,
    source: Source | None = None,
    include_deleted: bool = False,
    only_deleted: bool = False,
    sort: SortField = SortField.OCCURRED_AT,
    descending: bool = True,
    limit: Annotated[int, Query(ge=1, le=tx_cases.MAX_PAGE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    paid_with: Annotated[str | None, Query(max_length=36)] = None,
) -> PageOut:
    query = _query(
        auth, direction, start, end, category_id, uncategorized, search, status, source,
        include_deleted, only_deleted, sort, descending, limit, offset, paid_with,
    )  # fmt: skip
    page = await tx_cases.list_ledger(web.uow(), auth.user.id, query)
    conversions = await _conversions(web, auth.user, page.items)
    ids = [t.id for t in page.items]
    kept = await receipt_cases.with_receipts(web.uow(), auth.user.id, ids)
    moved = await tx_cases.lineage(web.uow(), auth.user.id, ids)
    twins = await duplicate_cases.matches(web.uow(), auth.user, page.items)
    wallets = await _wallets_of(web, auth.user, page.items)
    items = [
        tx_out(
            t,
            conversions.get(t.id),
            has_receipt=t.id in kept,
            moved=moved.get(t.id),
            twin=twins.get(t.id),
            wallets=wallets,
        )
        for t in page.items
    ]
    return PageOut(items=items, total=page.total)


class MerchantSuggestionOut(Model):
    name: str
    category_id: UUID | None  # None when the usual spend has no category
    category: str | None
    amount: MoneyOut  # the amount usually paid
    times: int
    last_on: date


@router.get("/transactions/suggestions")
async def merchant_suggestions(
    auth: Auth,
    web: Runtime,
    q: Annotated[str, Query(max_length=60)] = "",
    direction: Direction = Direction.OUT,
) -> list[MerchantSuggestionOut]:
    """Who the user has paid before that matches what they're typing (the most used
    when nothing is typed), with the usual amount and category, for the entry form."""
    found = await tx_cases.merchant_suggestions(
        web.uow(), auth.user.id, direction, q, now=web.clock()
    )
    names = {c.id: c.name for c in await category_cases.list_categories(web.uow(), auth.user.id)}
    tz = ZoneInfo(auth.user.timezone)
    return [
        MerchantSuggestionOut(
            name=f.name,
            category_id=f.category_id,
            category=names.get(f.category_id) if f.category_id else None,
            amount=money(f.amount),
            times=f.times,
            last_on=f.last.astimezone(tz).date(),
        )
        for f in found
    ]


@router.get("/transactions/{transaction_id}")
async def get_transaction(transaction_id: UUID, auth: Auth, web: Runtime) -> TransactionOut:
    """One transaction with how money moved around it, to follow a repayment's link."""
    tx = await tx_cases.get_transaction(web.uow(), auth.user.id, transaction_id)
    conversions = await _conversions(web, auth.user, [tx])
    kept = await receipt_cases.with_receipts(web.uow(), auth.user.id, [tx.id])
    moved = await tx_cases.lineage(web.uow(), auth.user.id, [tx.id])
    return tx_out(
        tx,
        conversions.get(tx.id),
        has_receipt=tx.id in kept,
        moved=moved.get(tx.id),
        wallets=await _wallets_of(web, auth.user, [tx]),
    )


@router.get("/transactions/{transaction_id}/receipt", include_in_schema=False)
async def receipt(transaction_id: UUID, auth: Auth, web: Runtime) -> RedirectResponse:
    """Send the owner to a link to their receipt that expires in minutes."""
    if web.archive is None:
        raise NotFound("receipts aren't kept on this server")
    url = await receipt_cases.download_link(web.uow(), web.archive, auth.user.id, transaction_id)
    response = RedirectResponse(url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


class TransactionIn(Model):
    direction: Literal["in", "out"]
    amount: str = Field(max_length=32)
    currency: str | None = Field(None, max_length=3)
    date: str | None = None
    counterparty: str | None = None
    category_id: UUID | None = None
    notes: str | None = None
    # Money out: the wallet it was paid with. Left out, the user's usual card is used if they
    # have one; null means none.
    paid_with_wallet_id: UUID | None = None


IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="A client-made unique key for this entry. Sending the same key again "
        "returns the transaction already recorded (200) instead of recording another.",
    ),
]


@router.post("/transactions", status_code=201, responses={200: {"model": TransactionOut}})
async def create_transaction(
    body: TransactionIn,
    auth: Auth,
    web: Runtime,
    response: Response,
    idempotency_key: IdempotencyKey = None,
) -> TransactionOut:
    user = auth.user
    said = "paid_with_wallet_id" in body.model_fields_set
    tx, created = await tx_cases.log_transaction_once(
        web.uow(),
        user.id,
        tx_cases.NewTransaction(
            direction=Direction(body.direction),
            amount=Money.of(body.amount, body.currency or user.home_currency),
            occurred_at=_when(user, body.date, web.clock()),
            counterparty=body.counterparty,
            category_id=body.category_id,
            notes=body.notes,
            source=Source.MANUAL,
            paid_with_wallet_id=body.paid_with_wallet_id,
            use_usual_card=not said,
            client_ref=idempotency_key,
        ),
    )
    if not created:
        response.status_code = 200
    return await _out(web, user, tx)


class MoveIn(Model):
    amount: str = Field(max_length=32)
    currency: str | None = Field(None, max_length=3)  # default: the home currency
    to_wallet_id: UUID
    from_wallet_id: UUID | None = None  # default: the main account
    occurred_at: str | None = None  # a date or a full timestamp; default: now
    received_amount: str | None = Field(None, max_length=32)  # what arrived, if not ``amount``
    received_currency: str | None = Field(None, max_length=3)  # default: ``currency``
    notes: str | None = None


@router.post("/moves", status_code=201)
async def create_move(body: MoveIn, auth: Auth, web: Runtime) -> TransactionOut:
    """Record money moved between two of the user's wallets. Nothing is moved for real."""
    user = auth.user
    currency = body.currency or user.home_currency
    received = (
        Money.of(body.received_amount, body.received_currency or currency)
        if body.received_amount
        else None
    )
    tx = await wallet_cases.log_move(
        web.uow(),
        user.id,
        amount=Money.of(body.amount, currency),
        to_wallet_id=body.to_wallet_id,
        from_wallet_id=body.from_wallet_id,
        occurred_at=_when(user, body.occurred_at, web.clock()),
        received_amount=received,
        notes=body.notes,
    )
    return await _out(web, user, tx)


class MoveToIn(Model):
    wallet_id: UUID


@router.post("/transactions/{transaction_id}/move")
async def mark_transaction_as_move(
    transaction_id: UUID, body: MoveToIn, auth: Auth, web: Runtime
) -> TransactionOut:
    """ "This was a move": money out becomes a move from the main account to the wallet, money in a
    move from the wallet to the main account. The category goes; undo brings it back."""
    tx = await wallet_cases.mark_as_move(web.uow(), auth.user.id, transaction_id, body.wallet_id)
    return await _out(web, auth.user, tx)


class TransactionPatch(Model):
    direction: Literal["in", "out"] | None = None
    amount: str | None = Field(None, max_length=32)
    currency: str | None = Field(None, max_length=3)
    date: str | None = None
    counterparty: str | None = None
    category_id: UUID | None = None
    notes: str | None = None
    status: Literal["confirmed", "pending"] | None = None
    # Money out: the wallet it was paid with; null clears it, leaving it out keeps it.
    paid_with_wallet_id: UUID | None = None


class RuleSuggestionOut(Model):
    """Offered after a category correction; nothing changes unless the user accepts."""

    question: str
    pattern: str
    category_id: UUID
    replaces_category_id: UUID | None


class EditedTransactionOut(TransactionOut):
    rule_suggestion: RuleSuggestionOut | None = None


@router.patch("/transactions/{transaction_id}")
async def edit_transaction(
    transaction_id: UUID, body: TransactionPatch, auth: Auth, web: Runtime
) -> EditedTransactionOut:
    user = auth.user
    given = body.model_fields_set
    current = await tx_cases.get_transaction(web.uow(), user.id, transaction_id)
    changes: dict[str, Any] = {}
    if "direction" in given and body.direction:
        changes["direction"] = Direction(body.direction)
    if ("amount" in given and body.amount) or ("currency" in given and body.currency):
        changes["amount"] = Money.of(
            body.amount or str(current.amount.amount), body.currency or current.amount.currency
        )
    if "date" in given and body.date:
        changes["occurred_at"] = _when(user, body.date, web.clock())
    for field in ("counterparty", "category_id", "notes", "paid_with_wallet_id"):
        if field in given:
            changes[field] = getattr(body, field)
    if "status" in given and body.status:
        changes["status"] = TransactionStatus(body.status)
    tx = await tx_cases.edit_transaction(
        web.uow(), user.id, transaction_id, tx_cases.TransactionChanges(**changes)
    )
    out = EditedTransactionOut(**(await _out(web, user, tx)).model_dump())
    if tx.category_id != current.category_id:
        offer = await rule_cases.suggest_rule(web.uow(), user.id, tx)
        if offer is not None:
            out.rule_suggestion = RuleSuggestionOut(
                question=offer.question,
                pattern=offer.pattern,
                category_id=offer.category.id,
                replaces_category_id=offer.replaces.id if offer.replaces else None,
            )
    return out


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(transaction_id: UUID, auth: Auth, web: Runtime) -> TransactionOut:
    tx = await tx_cases.delete_transaction(web.uow(), auth.user.id, transaction_id)
    return await _out(web, auth.user, tx)


@router.post("/transactions/{transaction_id}/restore")
async def restore_transaction(transaction_id: UUID, auth: Auth, web: Runtime) -> TransactionOut:
    tx = await tx_cases.restore_transaction(web.uow(), auth.user.id, transaction_id)
    return await _out(web, auth.user, tx)


class OtherIn(Model):
    other_id: UUID


class MergedOut(Model):
    kept: TransactionOut
    removed: TransactionOut


@router.post("/transactions/{transaction_id}/merge")
async def merge_duplicates(
    transaction_id: UUID, body: OtherIn, auth: Auth, web: Runtime
) -> MergedOut:
    """Two records of one payment become one: the other is deleted (and restorable)."""
    merged = await duplicate_cases.merge(web.uow, auth.user.id, transaction_id, body.other_id)
    return MergedOut(
        kept=await _out(web, auth.user, merged.kept),
        removed=await _out(web, auth.user, merged.removed),
    )


@router.post("/transactions/{transaction_id}/not-duplicate", status_code=204)
async def not_duplicate(transaction_id: UUID, body: OtherIn, auth: Auth, web: Runtime) -> None:
    """Two payments after all: never flag this pair again."""
    await duplicate_cases.dismiss(
        web.uow(), auth.user.id, transaction_id, body.other_id, now=web.clock()
    )


class IdsIn(Model):
    ids: list[UUID] = Field(min_length=1, max_length=tx_cases.MAX_BULK)


class IdsOut(Model):
    ids: list[UUID]


@router.post("/transactions/bulk-delete")
async def bulk_delete(body: IdsIn, auth: Auth, web: Runtime) -> IdsOut:
    changed = await tx_cases.bulk_delete(web.uow(), auth.user.id, body.ids)
    return IdsOut(ids=[t.id for t in changed])


@router.post("/transactions/bulk-restore")
async def bulk_restore(body: IdsIn, auth: Auth, web: Runtime) -> IdsOut:
    changed = await tx_cases.bulk_restore(web.uow(), auth.user.id, body.ids)
    return IdsOut(ids=[t.id for t in changed])


class UndoOut(Model):
    undone: str
    transaction: TransactionOut


@router.post("/undo")
async def undo(auth: Auth, web: Runtime) -> UndoOut:
    result = await tx_cases.undo_last(web.uow(), auth.user.id)
    return UndoOut(
        undone=result.undone.value, transaction=await _out(web, auth.user, result.transaction)
    )


async def ledger_csv(
    web: WebRuntime, auth: Authed, query_at: Callable[[int, int], LedgerQuery] | None = None
) -> str:
    """The ledger CSV for the transactions ``query_at(limit, offset)`` asks for (the latest
    ones, deleted left out, unless said), at most ``EXPORT_LIMIT`` of them. Also the
    ledger.csv in "Export all my data"."""
    user = auth.user

    def latest(limit: int, offset: int) -> LedgerQuery:
        return _query(
            auth, None, None, None, None, False, None, None, None, False, False,
            SortField.OCCURRED_AT, True, limit, offset,
        )  # fmt: skip

    ask = query_at or latest
    rows: list[Transaction] = []
    offset = 0
    while len(rows) < EXPORT_LIMIT:
        page = await tx_cases.list_ledger(web.uow(), user.id, ask(tx_cases.MAX_PAGE, offset))
        rows += page.items
        offset += len(page.items)
        if not page.items or offset >= page.total:
            break
    cats = await category_cases.list_categories(web.uow(), user.id)
    rows = rows[:EXPORT_LIMIT]
    conversions = await _conversions(web, user, rows)
    wallets_by_id = await _wallets_of(web, user, rows)
    return to_csv(
        rows, {c.id: c for c in cats}, _tz(user), user.home_currency, conversions, wallets_by_id
    )


@router.get("/export.csv")
async def export_csv(
    auth: Auth,
    web: Runtime,
    direction: Direction | None = None,
    start: date | None = None,
    end: date | None = None,
    category_id: UUID | None = None,
    uncategorized: bool = False,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status: TransactionStatus | None = None,
    source: Source | None = None,
    include_deleted: bool = False,
    only_deleted: bool = False,
    sort: SortField = SortField.OCCURRED_AT,
    descending: bool = True,
    paid_with: Annotated[str | None, Query(max_length=36)] = None,
) -> Response:
    body = await ledger_csv(
        web,
        auth,
        lambda limit, offset: _query(
            auth, direction, start, end, category_id, uncategorized, search, status, source,
            include_deleted, only_deleted, sort, descending, limit, offset, paid_with,
        ),
    )  # fmt: skip
    stamp = web.clock().astimezone(_tz(auth.user)).strftime("%Y%m%d")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="nexus-ledger-{stamp}.csv"'},
    )
