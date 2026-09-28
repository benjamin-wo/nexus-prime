"""JSON API for the web cockpit. Thin: parse, call a use case, shape the result."""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from nexus.agent.service import Reply
from nexus.application import access, fx
from nexus.application import budgets as budget_cases
from nexus.application import categories as category_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.ports import LedgerQuery, SortField
from nexus.application.users import RegisterUser
from nexus.channels.web.csv_export import to_csv
from nexus.channels.web.security import (
    Auth,
    Authed,
    Runtime,
    WebRuntime,
    check_origin,
    clear_session_cookie,
    set_session_cookie,
)
from nexus.channels.web.telegram_login import (
    LoginRejected,
    TelegramIdentity,
    verify_login,
    verify_webapp,
)
from nexus.domain.errors import Forbidden, InvalidInput
from nexus.domain.ledger import (
    Category,
    Direction,
    Role,
    Source,
    Transaction,
    TransactionStatus,
    User,
)
from nexus.domain.money import Money

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


class TransactionOut(Model):
    id: UUID
    direction: str
    amount: MoneyOut
    home: HomeAmountOut | None = None  # set on listings for foreign-currency rows
    occurred_at: datetime
    counterparty: str | None
    category_id: UUID | None
    notes: str | None
    status: str
    source: str
    deleted: bool


def home_out(conversion: fx.Conversion) -> HomeAmountOut:
    rate = conversion.rate
    return HomeAmountOut(
        amount=money(conversion.home) if conversion.home else None,
        rate=str(rate.value) if rate else None,
        rate_date=rate.effective if rate else None,
    )


def tx_out(tx: Transaction, conversion: fx.Conversion | None = None) -> TransactionOut:
    return TransactionOut(
        id=tx.id,
        direction=tx.direction.value,
        amount=money(tx.amount),
        home=home_out(conversion) if conversion else None,
        occurred_at=tx.occurred_at,
        counterparty=tx.counterparty,
        category_id=tx.category_id,
        notes=tx.notes,
        status=tx.status.value,
        source=tx.source.value,
        deleted=tx.is_deleted,
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
    return PageOut(items=[tx_out(t, conversions.get(t.id)) for t in page.items], total=page.total)


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


@router.patch("/transactions/{transaction_id}")
async def edit_transaction(
    transaction_id: UUID, body: TransactionPatch, auth: Auth, web: Runtime
) -> TransactionOut:
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
    return tx_out(tx)


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(transaction_id: UUID, auth: Auth, web: Runtime) -> TransactionOut:
    return tx_out(await tx_cases.delete_transaction(web.uow(), auth.user.id, transaction_id))


@router.post("/transactions/{transaction_id}/restore")
async def restore_transaction(transaction_id: UUID, auth: Auth, web: Runtime) -> TransactionOut:
    return tx_out(await tx_cases.restore_transaction(web.uow(), auth.user.id, transaction_id))


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
