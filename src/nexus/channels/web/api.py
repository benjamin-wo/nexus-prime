"""JSON API for the web cockpit. Thin: parse, call a use case, shape the result."""

import asyncio
import base64
import binascii
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from nexus.agent.service import Reply
from nexus.application import access, fx
from nexus.application import bills as bill_cases
from nexus.application import budgets as budget_cases
from nexus.application import cashflow as cashflow_cases
from nexus.application import categories as category_cases
from nexus.application import category_rules as rule_cases
from nexus.application import duplicates as duplicate_cases
from nexus.application import memory as memory_cases
from nexus.application import notifications as notify_cases
from nexus.application import receipts as receipt_cases
from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import statements as statement_cases
from nexus.application import subscriptions as subscription_cases
from nexus.application import transactions as tx_cases
from nexus.application.ports import LedgerQuery, SortField
from nexus.application.statements import Verdict
from nexus.application.users import RegisterUser
from nexus.channels.web.csv_export import to_csv
from nexus.channels.web.security import (
    Auth,
    Authed,
    Runtime,
    WebRuntime,
    check_origin,
    clear_session_cookie,
    limit,
    set_session_cookie,
)
from nexus.channels.web.telegram_login import (
    LoginRejected,
    TelegramIdentity,
    verify_login,
    verify_webapp,
)
from nexus.domain.errors import Forbidden, InvalidInput, NotFound
from nexus.domain.ledger import (
    Category,
    Direction,
    Lineage,
    Role,
    Source,
    Transaction,
    TransactionStatus,
    User,
)
from nexus.domain.money import Money
from nexus.domain.notifications import Frequency, NotificationSettings, label
from nexus.domain.planning import Cadence, PayRule, next_month_start
from nexus.domain.statements import AmountSign, DateOrder, Mapping, StatementImport
from nexus.infra.pdf.text import PasswordNeeded, pdf_lines

router = APIRouter(prefix="/api")
EXPORT_LIMIT = 10_000


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- shapes -----------------------------------------------------------------------


class MoneyOut(Model):
    amount: str
    currency: str


def money(value: Money) -> MoneyOut:
    return MoneyOut(amount=str(value.amount), currency=value.currency)


class HomeAmountOut(Model):
    """A foreign amount in the user's home currency; amount is None if no rate was available."""

    amount: MoneyOut | None
    rate: str | None  # one unit of the original currency in the home currency
    rate_date: date | None  # the day that rate was published


class ShareOut(Model):
    name: str
    share: MoneyOut
    repaid: MoneyOut


class SplitOut(Model):
    own_share: MoneyOut  # what the bill cost the user, if everyone pays back
    people: list[ShareOut]


class LinkOut(Model):
    """The transaction on the other side of a repayment: for a bill, the money in
    that paid part of it back; for money in, the bill it paid back."""

    transaction_id: UUID
    counterparty: str | None
    occurred_at: datetime
    name: str  # who paid back
    amount: MoneyOut


class TwinOut(Model):
    """Another transaction that looks like the same payment."""

    transaction_id: UUID
    counterparty: str | None
    occurred_at: datetime
    amount: MoneyOut


class TransactionOut(Model):
    id: UUID
    direction: str
    amount: MoneyOut
    home: HomeAmountOut | None = None  # set on listings for foreign-currency rows
    occurred_at: datetime
    counterparty: str | None
    category_id: UUID | None
    category_rule_id: UUID | None = None  # the rule that chose the category, if one did
    notes: str | None
    status: str
    source: str
    deleted: bool
    has_receipt: bool = False  # set on listings
    split: SplitOut | None = None  # a bill shared with others
    links: list[LinkOut] = []  # repayments to or from other transactions
    own: MoneyOut | None = None  # the user's own money in it, when friends paid part back
    duplicate: TwinOut | None = None  # set on listings: a possible second record of it


def home_out(conversion: fx.Conversion) -> HomeAmountOut:
    rate = conversion.rate
    return HomeAmountOut(
        amount=money(conversion.home) if conversion.home else None,
        rate=str(rate.value) if rate else None,
        rate_date=rate.effective if rate else None,
    )


def _moved(tx: Transaction, moved: Lineage | None) -> dict[str, Any]:
    if moved is None:
        return {}
    found: dict[str, Any] = {}
    if moved.shares:
        people = [
            ShareOut(
                name=s.participant_name,
                share=money(s.share),
                repaid=money(
                    sum(
                        (
                            link.amount
                            for link in moved.links
                            if link.bill_id == tx.id and link.participant_name == s.participant_name
                        ),
                        Money.zero(s.share.currency),
                    )
                ),
            )
            for s in moved.shares
        ]
        others = sum((s.share for s in moved.shares), Money.zero(tx.amount.currency))
        found["split"] = SplitOut(own_share=money(tx.amount - others), people=people)
    links = []
    for link in moved.links:
        mine_is_bill = link.bill_id == tx.id
        links.append(
            LinkOut(
                transaction_id=link.income_id if mine_is_bill else link.bill_id,
                counterparty=None if mine_is_bill else link.bill_counterparty,
                occurred_at=link.income_occurred_at if mine_is_bill else link.bill_occurred_at,
                name=link.participant_name,
                amount=money(link.amount),
            )
        )
    found["links"] = links
    repaid = moved.repaid(tx.id)
    if repaid:
        found["own"] = money(Money(tx.amount.amount - repaid, tx.amount.currency))
    return found


def tx_out(
    tx: Transaction,
    conversion: fx.Conversion | None = None,
    *,
    has_receipt: bool = False,
    moved: Lineage | None = None,
    twin: Transaction | None = None,
) -> TransactionOut:
    return TransactionOut(
        id=tx.id,
        direction=tx.direction.value,
        amount=money(tx.amount),
        home=home_out(conversion) if conversion else None,
        occurred_at=tx.occurred_at,
        counterparty=tx.counterparty,
        category_id=tx.category_id,
        category_rule_id=tx.category_rule_id,
        notes=tx.notes,
        status=tx.status.value,
        source=tx.source.value,
        deleted=tx.is_deleted,
        has_receipt=has_receipt,
        duplicate=TwinOut(
            transaction_id=twin.id,
            counterparty=twin.counterparty,
            occurred_at=twin.occurred_at,
            amount=money(twin.amount),
        )
        if twin
        else None,
        **_moved(tx, moved),
    )


class UserOut(Model):
    telegram_user_id: int
    role: str
    home_currency: str
    timezone: str


class MeOut(Model):
    user: UserOut
    csrf_token: str


def me_out(user: User, csrf: str) -> MeOut:
    return MeOut(
        user=UserOut(
            telegram_user_id=user.telegram_user_id,
            role=user.role.value,
            home_currency=user.home_currency,
            timezone=user.timezone,
        ),
        csrf_token=csrf,
    )


class ButtonOut(Model):
    label: str
    data: str


class ReplyOut(Model):
    text: str
    buttons: list[list[ButtonOut]]


def replies_out(replies: list[Reply]) -> list[ReplyOut]:
    return [
        ReplyOut(
            text=r.text,
            buttons=[[ButtonOut(label=b.label, data=b.data) for b in row] for row in r.buttons],
        )
        for r in replies
    ]


def _tz(user: User) -> ZoneInfo:
    return ZoneInfo(user.timezone)


async def _conversions(
    web: WebRuntime, user: User, txs: list[Transaction]
) -> dict[UUID, fx.Conversion]:
    """Home-currency views of the foreign-currency rows, each at its own day's rate."""
    home, tz = user.home_currency, _tz(user)
    foreign = [(t, t.occurred_at.astimezone(tz).date()) for t in txs if t.amount.currency != home]
    found = await fx.rates_for(web.rates, home, ((t.amount.currency, d) for t, d in foreign))
    return {t.id: fx.convert(t.amount, d, home, found) for t, d in foreign}


def _day_start(user: User, day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=_tz(user))


def _when(user: User, value: str | None, now: datetime) -> datetime:
    """A date (noon local) or full timestamp; now when absent."""
    if value is None:
        return now
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput("dates look like 2026-09-28") from exc
    if parsed.tzinfo is not None:
        return parsed
    if parsed.time() == time() and "T" not in value:
        return datetime.combine(parsed.date(), time(12), tzinfo=_tz(user))
    return parsed.replace(tzinfo=_tz(user))


class ConfigOut(Model):
    bot_username: str


@router.get("/config")
async def config(web: Runtime) -> ConfigOut:
    """What the sign-in page needs before anyone is signed in."""
    return ConfigOut(bot_username=await web.bot_username())


# --- auth ---------------------------------------------------------------------------


class LoginIn(Model):
    telegram: dict[str, Any]
    invite: str | None = None


def _bot_token(web: WebRuntime) -> str:
    token = web.settings.telegram_bot_token
    if token is None:  # pragma: no cover - web is only enabled with Telegram
        raise HTTPException(status_code=404)
    return token.get_secret_value()


async def _log_in(web: WebRuntime, telegram: dict[str, Any], invite: str | None) -> access.LoggedIn:
    now = web.clock()
    try:
        identity = verify_login(telegram, _bot_token(web), now=now)
    except LoginRejected as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return await _open_session(web, identity, invite, now)


async def _open_session(
    web: WebRuntime, identity: TelegramIdentity, invite: str | None, now: datetime
) -> access.LoggedIn:
    return await access.log_in(
        web.uow(),
        identity.telegram_user_id,
        invite_token=invite,
        defaults=RegisterUser(
            telegram_user_id=identity.telegram_user_id,
            telegram_chat_id=identity.telegram_user_id,
            home_currency=web.settings.default_home_currency,
            timezone=web.settings.default_timezone,
            role=Role.MEMBER,
        ),
        owner_telegram_id=web.settings.admin_telegram_chat_id,
        now=now,
    )


@router.post("/auth/telegram")
async def login(body: LoginIn, request: Request, response: Response, web: Runtime) -> MeOut:
    check_origin(request, web)
    logged_in = await _log_in(web, body.telegram, body.invite)
    set_session_cookie(response, web, logged_in.token)
    return me_out(logged_in.user, logged_in.session.csrf_token)


class WebAppLoginIn(Model):
    init_data: str = Field(min_length=1, max_length=4096)


@router.post("/auth/webapp")
async def login_webapp(
    body: WebAppLoginIn, request: Request, response: Response, web: Runtime
) -> MeOut:
    """Sign in from inside Telegram (the Mini App), with no widget or phone number."""
    check_origin(request, web)
    now = web.clock()
    try:
        identity = verify_webapp(body.init_data, _bot_token(web), now=now)
    except LoginRejected as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    logged_in = await _open_session(web, identity, None, now)
    set_session_cookie(response, web, logged_in.token, embedded=True)
    return me_out(logged_in.user, logged_in.session.csrf_token)


@router.get("/auth/telegram/callback", include_in_schema=False)
async def login_callback(request: Request, web: Runtime) -> Response:
    """The Login Widget's redirect mode: Telegram sends the signed fields here.

    Redirect mode avoids the widget's JavaScript callback, which would need
    'unsafe-eval' in the Content-Security-Policy.
    """
    params = dict(request.query_params)
    invite = params.pop("invite", None)
    try:
        logged_in = await _log_in(web, params, invite)
    except HTTPException:
        return RedirectResponse("/login?error=signin", status_code=303)
    except Forbidden:
        return RedirectResponse("/login?error=access", status_code=303)
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, web, logged_in.token)
    return response


@router.post("/auth/logout", status_code=204)
async def logout(auth: Auth, response: Response, web: Runtime) -> None:
    await access.log_out(web.uow(), auth.token, now=web.clock())
    clear_session_cookie(response)


@router.get("/me")
async def me(auth: Auth) -> MeOut:
    return me_out(auth.user, auth.session.csrf_token)


class InviteOut(Model):
    url: str
    expires_at: datetime


@router.post("/invites")
async def invite(auth: Auth, web: Runtime) -> InviteOut:
    issued = await access.create_invite(web.uow(), auth.user.id, now=web.clock())
    return InviteOut(url=f"{web.origin}/invite/{issued.token}", expires_at=issued.invite.expires_at)


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
) -> LedgerQuery:
    user = auth.user
    return LedgerQuery(
        direction=direction,
        start=_day_start(user, start) if start else None,
        end=_day_start(user, end) + timedelta(days=1) if end else None,
        category_id=category_id,
        uncategorized=uncategorized,
        search=search or None,
        status=status,
        source=source,
        include_deleted=include_deleted,
        only_deleted=only_deleted,
        sort=sort,
        descending=descending,
        limit=limit,
        offset=offset,
    )


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
) -> PageOut:
    query = _query(
        auth, direction, start, end, category_id, uncategorized, search, status, source,
        include_deleted, only_deleted, sort, descending, limit, offset,
    )  # fmt: skip
    page = await tx_cases.list_ledger(web.uow(), auth.user.id, query)
    conversions = await _conversions(web, auth.user, page.items)
    ids = [t.id for t in page.items]
    kept = await receipt_cases.with_receipts(web.uow(), auth.user.id, ids)
    moved = await tx_cases.lineage(web.uow(), auth.user.id, ids)
    twins = await duplicate_cases.matches(web.uow(), auth.user, page.items)
    items = [
        tx_out(
            t,
            conversions.get(t.id),
            has_receipt=t.id in kept,
            moved=moved.get(t.id),
            twin=twins.get(t.id),
        )
        for t in page.items
    ]
    return PageOut(items=items, total=page.total)


@router.get("/transactions/{transaction_id}")
async def get_transaction(transaction_id: UUID, auth: Auth, web: Runtime) -> TransactionOut:
    """One transaction with how money moved around it, to follow a repayment's link."""
    tx = await tx_cases.get_transaction(web.uow(), auth.user.id, transaction_id)
    conversions = await _conversions(web, auth.user, [tx])
    kept = await receipt_cases.with_receipts(web.uow(), auth.user.id, [tx.id])
    moved = await tx_cases.lineage(web.uow(), auth.user.id, [tx.id])
    return tx_out(tx, conversions.get(tx.id), has_receipt=tx.id in kept, moved=moved.get(tx.id))


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


@router.post("/transactions", status_code=201)
async def create_transaction(body: TransactionIn, auth: Auth, web: Runtime) -> TransactionOut:
    user = auth.user
    tx = await tx_cases.log_transaction(
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
        ),
    )
    return tx_out(tx)


class TransactionPatch(Model):
    direction: Literal["in", "out"] | None = None
    amount: str | None = Field(None, max_length=32)
    currency: str | None = Field(None, max_length=3)
    date: str | None = None
    counterparty: str | None = None
    category_id: UUID | None = None
    notes: str | None = None
    status: Literal["confirmed", "pending"] | None = None


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
    for field in ("counterparty", "category_id", "notes"):
        if field in given:
            changes[field] = getattr(body, field)
    if "status" in given and body.status:
        changes["status"] = TransactionStatus(body.status)
    tx = await tx_cases.edit_transaction(
        web.uow(), user.id, transaction_id, tx_cases.TransactionChanges(**changes)
    )
    out = EditedTransactionOut(**tx_out(tx).model_dump())
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
    return tx_out(await tx_cases.delete_transaction(web.uow(), auth.user.id, transaction_id))


@router.post("/transactions/{transaction_id}/restore")
async def restore_transaction(transaction_id: UUID, auth: Auth, web: Runtime) -> TransactionOut:
    return tx_out(await tx_cases.restore_transaction(web.uow(), auth.user.id, transaction_id))


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
    return MergedOut(kept=tx_out(merged.kept), removed=tx_out(merged.removed))


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
    return UndoOut(undone=result.undone.value, transaction=tx_out(result.transaction))


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
) -> Response:
    user = auth.user
    rows: list[Transaction] = []
    offset = 0
    while len(rows) < EXPORT_LIMIT:
        query = _query(
            auth, direction, start, end, category_id, uncategorized, search, status, source,
            include_deleted, only_deleted, sort, descending, tx_cases.MAX_PAGE, offset,
        )  # fmt: skip
        page = await tx_cases.list_ledger(web.uow(), user.id, query)
        rows += page.items
        offset += len(page.items)
        if not page.items or offset >= page.total:
            break
    cats = await category_cases.list_categories(web.uow(), user.id, include_inactive=True)
    rows = rows[:EXPORT_LIMIT]
    conversions = await _conversions(web, user, rows)
    body = to_csv(rows, {c.id: c for c in cats}, _tz(user), user.home_currency, conversions)
    stamp = web.clock().astimezone(_tz(user)).strftime("%Y%m%d")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="nexus-ledger-{stamp}.csv"'},
    )


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
    totals: list[TotalOut]
    by_category: list[CategoryTotalOut]


@router.get("/summary")
async def summary(
    auth: Auth, web: Runtime, start: date | None = None, end: date | None = None
) -> SummaryOut:
    user = auth.user
    today = web.clock().astimezone(_tz(user)).date()
    first = start or today.replace(day=1)
    last = end or today
    result = await tx_cases.summarize_in_home(
        web.uow(),
        web.rates,
        user,
        _day_start(user, first),
        _day_start(user, last) + timedelta(days=1),
    )
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
    )


class CategoryOut(Model):
    id: UUID
    name: str
    active: bool


def category_out(c: Category) -> CategoryOut:
    return CategoryOut(id=c.id, name=c.name, active=c.active)


@router.get("/categories")
async def categories(auth: Auth, web: Runtime, include_inactive: bool = False) -> list[CategoryOut]:
    cats = await category_cases.list_categories(
        web.uow(), auth.user.id, include_inactive=include_inactive
    )
    return [category_out(c) for c in cats]


class CategoryIn(Model):
    name: str = Field(min_length=1, max_length=100)


@router.post("/categories", status_code=201)
async def create_category(body: CategoryIn, auth: Auth, web: Runtime) -> CategoryOut:
    return category_out(await category_cases.create_category(web.uow(), auth.user.id, body.name))


class CategoryPatch(Model):
    name: str | None = Field(None, min_length=1, max_length=100)
    active: bool | None = None


@router.patch("/categories/{category_id}")
async def edit_category(
    category_id: UUID, body: CategoryPatch, auth: Auth, web: Runtime
) -> CategoryOut:
    result: Category | None = None
    if body.name is not None:
        result = await category_cases.rename_category(
            web.uow(), auth.user.id, category_id, body.name
        )
    if body.active is not None:
        result = await category_cases.set_category_active(
            web.uow(), auth.user.id, category_id, body.active
        )
    if result is None:
        raise InvalidInput("nothing to change")
    return category_out(result)


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


# --- statement import ----------------------------------------------------------------


class LayoutIn(Model):
    """Which column holds what, by position in the header row."""

    date: int = Field(ge=0)
    description: list[int] = Field(min_length=1, max_length=3)
    amount: int | None = Field(None, ge=0)
    debit: int | None = Field(None, ge=0)
    credit: int | None = Field(None, ge=0)
    currency: int | None = Field(None, ge=0)
    date_order: DateOrder = DateOrder.DMY
    sign: AmountSign = AmountSign.NEGATIVE_IS_OUT

    def mapping(self) -> Mapping:
        return Mapping(
            date=self.date,
            description=tuple(self.description),
            amount=self.amount,
            debit=self.debit,
            credit=self.credit,
            currency=self.currency,
            date_order=self.date_order,
            sign=self.sign,
        )


def layout_out(m: Mapping) -> LayoutIn:
    return LayoutIn(
        date=m.date,
        description=list(m.description),
        amount=m.amount,
        debit=m.debit,
        credit=m.credit,
        currency=m.currency,
        date_order=m.date_order,
        sign=m.sign,
    )


CSV_CHARS = 2_100_000


class PreviewIn(Model):
    csv: str = Field(min_length=1, max_length=CSV_CHARS)
    layout: LayoutIn | None = None


class MatchOut(Model):
    date: date
    description: str | None
    amount: str


class PreviewRowOut(Model):
    index: int
    verdict: Verdict
    cells: list[str]
    date: date | None
    description: str
    amount: str | None
    currency: str | None
    direction: Direction | None
    category: str | None
    problem: str | None
    matches: MatchOut | None


class PreviewOut(Model):
    headers: list[str]
    layout: LayoutIn | None
    saved_as: str | None
    rows: list[PreviewRowOut]


@router.post("/imports/preview")
async def preview_import(body: PreviewIn, auth: Auth, web: Runtime) -> PreviewOut:
    limit(web, auth, "import")
    shown = await statement_cases.preview(
        web.uow, auth.user, body.csv, body.layout.mapping() if body.layout else None
    )
    tz = ZoneInfo(auth.user.timezone)
    return PreviewOut(
        headers=shown.table.headers,
        layout=layout_out(shown.mapping) if shown.mapping else None,
        saved_as=shown.saved_as,
        rows=[
            PreviewRowOut(
                index=p.row.index,
                verdict=p.verdict,
                cells=p.row.raw,
                date=p.row.day,
                description=p.row.description,
                amount=str(p.money.amount) if p.money else None,
                currency=p.money.currency if p.money else None,
                direction=p.row.direction,
                category=p.category,
                problem=p.row.problem,
                matches=MatchOut(
                    date=p.matches.occurred_at.astimezone(tz).date(),
                    description=p.matches.counterparty,
                    amount=str(p.matches.amount.amount),
                )
                if p.matches
                else None,
            )
            for p in shown.rows
        ],
    )


PDF_SECONDS = 30
PDF_BASE64_CHARS = 14_000_000  # a 10 MB PDF, base64-encoded


class PdfIn(Model):
    pdf: str = Field(min_length=1, max_length=PDF_BASE64_CHARS)  # base64
    password: str | None = Field(None, max_length=200)


class PdfOut(Model):
    needs_password: bool = False
    wrong_password: bool = False
    csv: str | None = None
    layout: LayoutIn | None = None
    kind: str | None = None
    statement_date: date | None = None
    rows: int = 0
    reconciles: bool | None = None


@router.post("/imports/pdf")
async def read_pdf_statement(body: PdfIn, auth: Auth, web: Runtime) -> PdfOut:
    """A PDF statement's transactions as CSV, previewed and imported like any CSV.
    The PDF and its password are only held for this request."""
    limit(web, auth, "import")
    try:
        data = base64.b64decode(body.pdf, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidInput("that file didn't arrive whole; try again") from exc
    try:
        # A crafted PDF can be slow to read; the request gives up rather than hang.
        lines = await asyncio.wait_for(
            asyncio.to_thread(pdf_lines, data, body.password), PDF_SECONDS
        )
    except TimeoutError as exc:
        raise InvalidInput("that PDF took too long to read") from exc
    except PasswordNeeded as locked:
        return PdfOut(needs_password=True, wrong_password=locked.wrong)
    found = statement_cases.read_pdf(lines)
    return PdfOut(
        csv=found.csv,
        layout=layout_out(statement_cases.PDF_LAYOUT),
        kind=found.kind.value,
        statement_date=found.statement_date,
        rows=found.rows,
        reconciles=found.reconciles,
    )


class ImportIn(Model):
    csv: str = Field(min_length=1, max_length=CSV_CHARS)
    layout: LayoutIn
    include: list[int] = Field(min_length=1, max_length=5000)
    file_name: str = Field(min_length=1, max_length=200)
    save_as: str | None = Field(None, min_length=1, max_length=60)


class ImportOut(Model):
    id: UUID
    file_name: str
    added: int
    created_at: datetime
    undone_at: datetime | None = None


class ImportedOut(ImportOut):
    skipped: int


def import_out(record: StatementImport) -> ImportOut:
    return ImportOut(
        id=record.id,
        file_name=record.file_name,
        added=len(record.transaction_ids),
        created_at=record.created_at,
        undone_at=record.undone_at,
    )


@router.post("/imports", status_code=201)
async def import_statement(body: ImportIn, auth: Auth, web: Runtime) -> ImportedOut:
    limit(web, auth, "import")
    done = await statement_cases.confirm(
        web.uow,
        auth.user,
        body.csv,
        body.layout.mapping(),
        set(body.include),
        file_name=body.file_name,
        save_as=body.save_as,
        now=web.clock(),
    )
    return ImportedOut(**import_out(done.record).model_dump(), skipped=done.skipped)


@router.get("/imports")
async def imports(auth: Auth, web: Runtime) -> list[ImportOut]:
    return [import_out(r) for r in await statement_cases.list_imports(web.uow(), auth.user.id)]


@router.post("/imports/{import_id}/undo")
async def undo_statement_import(import_id: UUID, auth: Auth, web: Runtime) -> dict[str, int]:
    removed = await statement_cases.undo_import(web.uow(), auth.user.id, import_id, now=web.clock())
    return {"removed": removed}


class LayoutOut(Model):
    id: UUID
    name: str


@router.get("/imports/layouts")
async def import_layouts(auth: Auth, web: Runtime) -> list[LayoutOut]:
    saved = await statement_cases.list_layouts(web.uow(), auth.user.id)
    return [LayoutOut(id=s.id, name=s.name) for s in saved]


@router.delete("/imports/layouts/{layout_id}", status_code=204)
async def forget_import_layout(layout_id: UUID, auth: Auth, web: Runtime) -> None:
    await statement_cases.forget_layout(web.uow(), auth.user.id, layout_id)


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


# --- budgets --------------------------------------------------------------------------


class BudgetOut(Model):
    id: UUID
    category_id: UUID | None
    name: str
    limit: MoneyOut
    spent: MoneyOut
    remaining: MoneyOut
    percent: int
    unconverted: list[MoneyOut]


@router.get("/budgets")
async def budgets(auth: Auth, web: Runtime) -> list[BudgetOut]:
    statuses = await budget_cases.budget_statuses(web.uow, web.rates, auth.user, now=web.clock())
    return [
        BudgetOut(
            id=s.budget.id,
            category_id=s.budget.category_id,
            name=s.name,
            limit=money(s.budget.limit),
            spent=money(s.spent),
            remaining=money(s.remaining),
            percent=s.percent,
            unconverted=[money(m) for m in s.unconverted],
        )
        for s in statuses
    ]


class BudgetIn(Model):
    category_id: UUID | None = None
    amount: str = Field(max_length=32)


@router.put("/budgets", status_code=204)
async def set_budget(body: BudgetIn, auth: Auth, web: Runtime) -> None:
    user = auth.user
    limit = Money.of(body.amount.replace(",", ""), user.home_currency)
    await budget_cases.set_budget(web.uow(), user, body.category_id, limit, now=web.clock())


@router.delete("/budgets/{budget_id}", status_code=204)
async def remove_budget(budget_id: UUID, auth: Auth, web: Runtime) -> None:
    await budget_cases.remove_budget(web.uow(), auth.user.id, budget_id)


# --- bills ----------------------------------------------------------------------------


class BillOut(Model):
    id: UUID
    name: str
    amount: MoneyOut | None
    cadence: str
    due: date
    days_until: int
    snoozed: bool


def bill_out(view: bill_cases.BillView, now: datetime) -> BillOut:
    bill = view.bill
    return BillOut(
        id=bill.id,
        name=bill.name,
        amount=money(bill.amount) if bill.amount else None,
        cadence=bill.cadence.value,
        due=view.due,
        days_until=view.days_until,
        snoozed=view.snoozed(now),
    )


@router.get("/bills")
async def bills(auth: Auth, web: Runtime) -> list[BillOut]:
    now = web.clock()
    return [bill_out(v, now) for v in await bill_cases.list_bills(web.uow, auth.user, now=now)]


class BillIn(Model):
    name: str = Field(min_length=1, max_length=100)
    due: date
    cadence: Literal["once", "weekly", "monthly", "yearly"] = "monthly"
    amount: str | None = Field(None, max_length=32)
    currency: str | None = Field(None, max_length=3)


@router.post("/bills", status_code=201)
async def add_bill(body: BillIn, auth: Auth, web: Runtime) -> BillOut:
    user, now = auth.user, web.clock()
    amount = (
        Money.of(body.amount.replace(",", ""), body.currency or user.home_currency)
        if body.amount and body.amount.strip()
        else None
    )
    bill = await bill_cases.add_bill(
        web.uow(), user, body.name, body.due, Cadence(body.cadence), amount, now=now
    )
    today = now.astimezone(_tz(user)).date()
    return bill_out(bill_cases.BillView(bill, body.due, None, today), now)


@router.post("/bills/{bill_id}/paid", status_code=204)
async def bill_paid(bill_id: UUID, auth: Auth, web: Runtime) -> None:
    await bill_cases.mark_paid(web.uow, auth.user, bill_id, now=web.clock())


@router.post("/bills/{bill_id}/snooze", status_code=204)
async def snooze_bill(bill_id: UUID, auth: Auth, web: Runtime) -> None:
    await bill_cases.snooze(web.uow, auth.user, bill_id, now=web.clock())


@router.delete("/bills/{bill_id}", status_code=204)
async def remove_bill(bill_id: UUID, auth: Auth, web: Runtime) -> None:
    await bill_cases.remove_bill(web.uow(), auth.user.id, bill_id, now=web.clock())


# --- salary ---------------------------------------------------------------------------


class SalaryOut(Model):
    rule: str
    day: int | None
    anchor: date | None
    description: str
    usual: MoneyOut | None
    next_payday: date
    days_until: int


@router.get("/salary")
async def salary(auth: Auth, web: Runtime) -> SalaryOut | None:
    view = await salary_cases.view(web.uow(), auth.user, now=web.clock())
    if view is None:
        return None
    s = view.schedule
    return SalaryOut(
        rule=s.rule.value,
        day=s.day,
        anchor=s.anchor,
        description=salary_cases.describe_rule(s),
        usual=money(s.baseline) if s.baseline else None,
        next_payday=view.next_payday,
        days_until=view.days_until,
    )


class SalaryIn(Model):
    rule: Literal["monthly_day", "last_weekday", "biweekly"]
    day: int | None = Field(None, ge=1, le=31)
    anchor: date | None = None


@router.put("/salary", status_code=204)
async def set_salary_schedule(body: SalaryIn, auth: Auth, web: Runtime) -> None:
    await salary_cases.set_schedule(
        web.uow(), auth.user, PayRule(body.rule), day=body.day, anchor=body.anchor, now=web.clock()
    )


class UsualSalaryIn(Model):
    amount: str = Field(max_length=32)


@router.put("/salary/usual", status_code=204)
async def set_usual_salary(body: UsualSalaryIn, auth: Auth, web: Runtime) -> None:
    """Saving the form is the user's confirmation."""
    user = auth.user
    amount = Money.of(body.amount.replace(",", ""), user.home_currency)
    await salary_cases.set_baseline(web.uow(), user, amount, now=web.clock())


@router.delete("/salary", status_code=204)
async def remove_salary(auth: Auth, web: Runtime) -> None:
    await salary_cases.remove_schedule(web.uow(), auth.user.id)


# --- cash flow --------------------------------------------------------------------------


class ExpectedOut(Model):
    kind: str
    name: str
    direction: str
    amount: MoneyOut | None
    home: MoneyOut | None


class CashDayOut(Model):
    day: date
    money_in: MoneyOut
    money_out: MoneyOut
    net: MoneyOut
    expected: list[ExpectedOut]
    expected_net: MoneyOut


class CashFlowOut(Model):
    start: date
    end: date
    today: date
    currency: str
    days: list[CashDayOut]
    logged_in: MoneyOut
    logged_out: MoneyOut
    expected_in: MoneyOut
    expected_out: MoneyOut
    unknown_amounts: int
    unconverted: list[MoneyOut]


@router.get("/cashflow")
async def cashflow(
    auth: Auth,
    web: Runtime,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> CashFlowOut:
    """One month, day by day: what was logged so far, and what's expected ahead."""
    user = auth.user
    now = web.clock()
    if month:
        try:
            first = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise InvalidInput("month must be a real month, like 2026-10") from exc
    else:
        first = now.astimezone(_tz(user)).date().replace(day=1)
    last = next_month_start(first) - timedelta(days=1)
    flow = await cashflow_cases.cash_flow(web.uow, web.rates, user, first, last, now=now)
    return CashFlowOut(
        start=flow.start,
        end=flow.end,
        today=flow.today,
        currency=flow.currency,
        days=[
            CashDayOut(
                day=d.day,
                money_in=money(d.money_in),
                money_out=money(d.money_out),
                net=money(d.net),
                expected=[
                    ExpectedOut(
                        kind=e.kind.value,
                        name=e.name,
                        direction=e.direction.value,
                        amount=money(e.amount) if e.amount else None,
                        home=money(e.home) if e.home else None,
                    )
                    for e in d.expected
                ],
                expected_net=money(d.expected_net),
            )
            for d in flow.days
        ],
        logged_in=money(flow.logged_in),
        logged_out=money(flow.logged_out),
        expected_in=money(flow.expected_in),
        expected_out=money(flow.expected_out),
        unknown_amounts=flow.unknown_amounts,
        unconverted=[money(m) for m in flow.unconverted],
    )


# --- subscriptions ----------------------------------------------------------------------


class SubscriptionOut(Model):
    id: UUID
    name: str
    cadence: str
    amount: MoneyOut
    monthly: MoneyOut
    last_charged_on: date
    next_charge: date
    previous_amount: MoneyOut | None
    price_changed_on: date | None


class SubscriptionsOut(Model):
    tracked: list[SubscriptionOut]
    proposed: list[SubscriptionOut]
    monthly_totals: list[MoneyOut]


def _subscription_out(view: subscription_cases.SubscriptionView) -> SubscriptionOut:
    s = view.subscription
    return SubscriptionOut(
        id=s.id,
        name=s.name,
        cadence=s.cadence.value,
        amount=money(s.amount),
        monthly=money(view.monthly),
        last_charged_on=s.last_charged_on,
        next_charge=view.next_charge,
        previous_amount=money(s.previous_amount) if s.previous_amount else None,
        price_changed_on=s.price_changed_on,
    )


@router.get("/subscriptions")
async def subscriptions(auth: Auth, web: Runtime) -> SubscriptionsOut:
    found = await subscription_cases.overview(web.uow(), auth.user.id)
    return SubscriptionsOut(
        tracked=[_subscription_out(v) for v in found.tracked],
        proposed=[_subscription_out(v) for v in found.proposed],
        monthly_totals=[money(m) for m in found.monthly_totals],
    )


@router.post("/subscriptions/{subscription_id}/track", status_code=204)
async def track_subscription(subscription_id: UUID, auth: Auth, web: Runtime) -> None:
    await subscription_cases.track(web.uow(), auth.user.id, subscription_id, now=web.clock())


@router.post("/subscriptions/{subscription_id}/dismiss", status_code=204)
async def dismiss_subscription(subscription_id: UUID, auth: Auth, web: Runtime) -> None:
    """Turn down a proposal, or stop tracking one. It isn't proposed again."""
    await subscription_cases.dismiss(web.uow(), auth.user.id, subscription_id, now=web.clock())


# --- transaction updates on Telegram ----------------------------------------------------


class UpdatesOut(Model):
    frequency: Frequency
    daily_at: str  # HH:MM, the daily summary's time
    description: str
    options: dict[Frequency, str]


def _updates_out(settings: NotificationSettings) -> UpdatesOut:
    return UpdatesOut(
        frequency=settings.frequency,
        daily_at=settings.daily_at.strftime("%H:%M"),
        description=notify_cases.describe(settings),
        options={f: label(f, settings.daily_at) for f in Frequency},
    )


@router.get("/notifications")
async def notifications(auth: Auth, web: Runtime) -> UpdatesOut:
    return _updates_out(await notify_cases.get_settings(web.uow(), auth.user.id))


class UpdatesIn(Model):
    frequency: Frequency
    daily_at: time | None = None  # only with daily


@router.put("/notifications")
async def set_notifications(body: UpdatesIn, auth: Auth, web: Runtime) -> UpdatesOut:
    updated = await notify_cases.set_frequency(
        web.uow(), auth.user.id, body.frequency, now=web.clock(), daily_at=body.daily_at
    )
    return _updates_out(updated)


# --- chat -----------------------------------------------------------------------------


class ChatIn(Model):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/chat")
async def chat(body: ChatIn, auth: Auth, web: Runtime) -> list[ReplyOut]:
    ref = f"web:{auth.session.token_hash[:16]}:{web.clock().timestamp()}"
    return replies_out(await web.service.handle_text(auth.user.id, body.message, ref))


class PressIn(Model):
    data: str = Field(min_length=1, max_length=64)


@router.post("/chat/press")
async def press(body: PressIn, auth: Auth, web: Runtime) -> list[ReplyOut]:
    """Confirm/Cancel, Undo and quick-action buttons, as on Telegram."""
    return replies_out(await web.service.press(auth.user.id, body.data))
