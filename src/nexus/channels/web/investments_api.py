"""The Investment department's API: holdings, and positions read from a broker
screenshot waiting to be saved. Research only: nothing here trades."""

import base64
import binascii
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import investments as investment_cases
from nexus.application import moves as move_cases
from nexus.application import plans as plan_cases
from nexus.application import quotes as quote_cases
from nexus.application import research as research_cases
from nexus.channels.web.api import MoneyOut, money
from nexus.channels.web.security import Auth, Runtime, limit
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.history import describe as describe_history
from nexus.domain.investments import (
    HoldingsDraft,
    Position,
    Trade,
    changes,
    clean_quantity,
    clean_symbol,
    plain,
)
from nexus.domain.levels import Levels
from nexus.domain.market import PriceKind, Session, percent
from nexus.domain.money import Money
from nexus.domain.news import EarningsDate, NewsItem
from nexus.domain.plans import FOLLOWED, SavedPlan

router = APIRouter(prefix="/api/investments")

# A phone screenshot, base64-encoded: well under this.
MAX_IMAGE_CHARS = 14_000_000
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PositionOut(Model):
    symbol: str
    quantity: Decimal
    average_cost: MoneyOut
    cost: MoneyOut


class EarningsOut(Model):
    day: date
    timing: str | None  # "before open", "after close", or not said


def _earnings(e: EarningsDate | None) -> EarningsOut | None:
    return EarningsOut(day=e.day, timing=e.timing) if e else None


class HoldingOut(PositionOut):
    updated_at: datetime
    # At the latest price (live while the market is open, else the last close); all
    # None until the stock has a price.
    price: MoneyOut | None = None
    price_day: date | None = None  # the trading day the price belongs to
    price_kind: PriceKind | None = None
    price_at: datetime | None = None  # when it was traded; None for an official close
    value: MoneyOut | None = None
    gain: MoneyOut | None = None
    gain_percent: Decimal | None = None
    day_change: MoneyOut | None = None
    day_percent: Decimal | None = None
    value_home: MoneyOut | None = None  # None also when there's no exchange rate yet
    earnings: EarningsOut | None = None  # the next earnings date, if known


class DraftOut(Model):
    id: str
    positions: list[PositionOut]
    changes: list[str]  # what saving it would change
    first: bool  # no holdings yet: it would be the whole portfolio


class TotalsOut(Model):
    """The portfolio in the home currency, at the latest prices."""

    value: MoneyOut | None
    cost: MoneyOut | None
    gain: MoneyOut | None
    gain_percent: Decimal | None
    day_change: MoneyOut | None
    day_percent: Decimal | None
    as_of: date | None  # the latest trading day used
    as_of_at: datetime | None  # when the newest live or provisional price was traded
    price_kind: PriceKind  # live if any holding's price is, else provisional_close, else close
    missing: list[str]  # stocks left out (no price or exchange rate yet)
    realised: MoneyOut | None  # locked in by sales
    dividends: MoneyOut | None  # received, after tax withheld
    total_return: MoneyOut | None  # held + sold + dividends


class PortfolioOut(Model):
    holdings: list[HoldingOut]
    totals: TotalsOut
    draft: DraftOut | None  # a screenshot waiting to be saved
    screenshots: bool  # reading screenshots is set up
    prices: bool  # daily prices are set up


def _position(p: Position) -> PositionOut:
    return PositionOut(
        symbol=p.symbol,
        quantity=p.quantity,
        average_cost=money(p.average_cost),
        cost=money(p.cost),
    )


def _optional(value: Money | None) -> MoneyOut | None:
    return money(value) if value is not None else None


def _holding(row: investment_cases.Row, earnings: EarningsDate | None) -> HoldingOut:
    h, v = row.holding, row.valued
    out = HoldingOut(
        **_position(h.position).model_dump(), updated_at=h.updated_at, earnings=_earnings(earnings)
    )
    if v is None:
        return out
    return out.model_copy(
        update={
            "price": money(v.price),
            "price_day": v.price_day,
            "price_kind": v.price_kind,
            "price_at": v.price_at,
            "value": money(v.value),
            "gain": money(v.gain),
            "gain_percent": v.gain_percent,
            "day_change": _optional(v.day_change),
            "day_percent": v.day_percent,
            "value_home": _optional(row.value_home),
        }
    )


def _totals(v: investment_cases.Valuation) -> TotalsOut:
    return TotalsOut(
        value=_optional(v.value),
        cost=_optional(v.cost),
        gain=_optional(v.gain),
        gain_percent=v.gain_percent,
        day_change=_optional(v.day_change),
        day_percent=v.day_percent,
        as_of=v.as_of,
        as_of_at=v.as_of_at,
        price_kind=v.price_kind,
        missing=v.missing,
        realised=_optional(v.realised),
        dividends=_optional(v.dividends),
        total_return=_optional(v.total_return),
    )


def _draft(draft: HoldingsDraft, held: list[Position]) -> DraftOut:
    return DraftOut(
        id=str(draft.id),
        positions=[_position(p) for p in draft.positions],
        changes=changes(held, draft.positions),
        first=not held,
    )


@router.get("")
async def portfolio(auth: Auth, web: Runtime) -> PortfolioOut:
    now = web.clock()
    # Fresh quotes for the user's own holdings first (when the market is open).
    status = await quote_cases.refresh_own(web.uow, web.quotes, auth.user.id, now=now, held=True)
    valued = await investment_cases.valuation(
        web.uow(), web.rates, auth.user, now=now, status=status
    )
    draft = await investment_cases.waiting_draft(web.uow(), auth.user.id)
    held = [row.holding.position for row in valued.rows]
    earnings = await research_cases.next_earnings(
        web.uow(), [p.symbol for p in held], today=web.clock().date()
    )
    return PortfolioOut(
        holdings=[_holding(row, earnings.get(row.holding.position.symbol)) for row in valued.rows],
        totals=_totals(valued),
        draft=_draft(draft, held) if draft else None,
        screenshots=web.service.reads_portfolios,
        prices=web.prices,
    )


# --- what moved today, and why --------------------------------------------------------------


class NewsOut(Model):
    headline: str
    source: str
    url: str
    summary: str
    published_at: datetime


def _news(n: NewsItem) -> NewsOut:
    return NewsOut(
        headline=n.headline,
        source=n.source,
        url=n.url,
        summary=n.summary,
        published_at=n.published_at,
    )


class MoverOut(Model):
    symbol: str
    held: bool  # false: a watched stock (shown when nothing is held)
    price: Decimal  # USD
    day_percent: Decimal
    price_kind: PriceKind
    price_at: datetime | None  # when it was traded; None for an official close
    price_day: date
    headline: NewsOut | None  # the day's newest, published since the session opened


class TodayOut(Model):
    session: Session  # "live", "closed_today" or "previous": for wording
    day: date  # the trading day (New York) the figures belong to
    change: MoneyOut | None  # the portfolio's change in the day, in the home currency
    percent: Decimal | None
    price_kind: PriceKind
    as_of_at: datetime | None
    holds: bool
    movers: list[MoverOut]  # the three biggest by percent: holdings, else watched stocks
    prices: bool


@router.get("/today")
async def today(auth: Auth, web: Runtime) -> TodayOut:
    """What moved today: the portfolio's change and its biggest movers, each with the
    day's newest headline."""
    now = web.clock()
    status = await quote_cases.refresh_own(
        web.uow, web.quotes, auth.user.id, now=now, held=True, watched=True
    )
    report = await move_cases.today(web.uow, web.rates, auth.user, now=now, status=status)
    return TodayOut(
        session=report.session,
        day=report.day,
        change=_optional(report.change),
        percent=report.percent,
        price_kind=report.kind,
        as_of_at=report.as_of_at,
        holds=report.holds,
        movers=[
            MoverOut(
                symbol=m.symbol,
                held=m.held,
                price=m.price,
                day_percent=m.percent,
                price_kind=m.kind,
                price_at=m.at,
                price_day=m.day,
                headline=_news(m.headline) if m.headline else None,
            )
            for m in report.movers
        ],
        prices=web.prices,
    )


class WhyOut(Model):
    symbol: str
    day: date
    day_percent: Decimal
    text: str  # two or three sentences; no advice
    headlines: list[NewsOut]  # what it was read from, newest first
    cached: bool


@router.post("/today/{symbol}/why")
async def why(symbol: str, auth: Auth, web: Runtime) -> WhyOut:
    """Why one of the user's held or watched stocks moved today, read from the day's
    headlines. Kept for 30 minutes per stock and day."""
    ticker = clean_symbol(symbol)
    limit(web, auth, "why")
    if web.explainer is None:
        raise InvalidInput("reading why a stock moved isn't set up")
    now = web.clock()
    status = await quote_cases.refresh_own(
        web.uow, web.quotes, auth.user.id, now=now, held=True, watched=True
    )
    found = await move_cases.why(web.uow, web.explainer, auth.user, ticker, now=now, status=status)
    return WhyOut(
        symbol=found.symbol,
        day=found.day,
        day_percent=found.percent,
        text=found.text,
        headlines=[_news(n) for n in found.headlines],
        cached=found.cached,
    )


class ScreenshotIn(Model):
    image: str = Field(min_length=1, max_length=MAX_IMAGE_CHARS)  # base64
    mime_type: str = Field(pattern="^image/(png|jpeg|webp)$")


@router.post("/screenshot")
async def read_screenshot(body: ScreenshotIn, auth: Auth, web: Runtime) -> DraftOut:
    """A broker screenshot read into positions, waiting for the user to save them.
    The image is only held for this request."""
    limit(web, auth, "import")
    try:
        image = base64.b64decode(body.image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidInput("that image didn't arrive whole; try again") from exc
    held = [h.position for h in await investment_cases.portfolio(web.uow(), auth.user.id)]
    proposal = await web.service.read_portfolio(auth.user.id, image, body.mime_type)
    if proposal is None:  # pragma: no cover - asked, so never None
        raise InvalidInput("I couldn't find any positions in that screenshot")
    return _draft(proposal.draft, held)


@router.post("/drafts/{draft_id}/save")
async def save_draft(draft_id: str, auth: Auth, web: Runtime) -> list[PositionOut]:
    saved = await investment_cases.save_draft(
        web.uow(), auth.user.id, _uuid(draft_id), now=web.clock()
    )
    return [_position(p) for p in saved]


@router.post("/drafts/{draft_id}/discard", status_code=204)
async def discard_draft(draft_id: str, auth: Auth, web: Runtime) -> None:
    await investment_cases.discard_draft(web.uow(), auth.user.id, _uuid(draft_id))


class PositionIn(Model):
    quantity: str = Field(min_length=1, max_length=32)
    average_cost: str = Field(min_length=1, max_length=32)
    currency: str = Field("USD", pattern="^[A-Za-z]{3}$")


@router.put("/holdings/{symbol}", status_code=204)
async def set_holding(symbol: str, body: PositionIn, auth: Auth, web: Runtime) -> None:
    position = Position(
        clean_symbol(symbol),
        clean_quantity(body.quantity),
        Money.of(body.average_cost.replace(",", ""), body.currency.upper()),
    )
    await investment_cases.set_position(web.uow(), auth.user.id, position, now=web.clock())


@router.delete("/holdings/{symbol}", status_code=204)
async def remove_holding(symbol: str, auth: Auth, web: Runtime) -> None:
    await investment_cases.remove(web.uow(), auth.user.id, clean_symbol(symbol))


# --- trades and dividends ---------------------------------------------------------------


class TradeOut(Model):
    id: UUID
    symbol: str
    side: str  # buy or sell
    quantity: Decimal
    price: MoneyOut | None
    traded_on: date
    realised: MoneyOut | None  # a sale's gain or loss against the average cost


class TradeIn(Model):
    side: str = Field(pattern="^(buy|sell)$")
    symbol: str = Field(min_length=1, max_length=12)
    quantity: str = Field(min_length=1, max_length=32)
    price: str | None = Field(None, max_length=32)
    currency: str = Field("USD", pattern="^[A-Za-z]{3}$")
    traded_on: date | None = None


def _trade_out(t: Trade) -> TradeOut:
    return TradeOut(
        id=t.id,
        symbol=t.symbol,
        side=t.side.value,
        quantity=plain(t.quantity),
        price=_optional(t.price),
        traded_on=t.traded_on,
        realised=_optional(t.realised),
    )


@router.get("/trades")
async def trades(auth: Auth, web: Runtime) -> list[TradeOut]:
    return [_trade_out(t) for t in await investment_cases.trade_history(web.uow(), auth.user.id)]


@router.post("/trades", status_code=201)
async def add_trade(body: TradeIn, auth: Auth, web: Runtime) -> TradeOut:
    price = (
        Money.of(body.price.replace(",", ""), body.currency.upper())
        if body.price and body.price.strip()
        else None
    )
    done = await investment_cases.record(
        web.uow(), auth.user.id, investment_cases.Side(body.side), clean_symbol(body.symbol),
        clean_quantity(body.quantity), price, now=web.clock(), traded_on=body.traded_on,
    )  # fmt: skip
    return _trade_out(done.trade)


class DividendOut(Model):
    symbol: str
    ex_date: date
    per_share: MoneyOut
    shares: Decimal
    gross: MoneyOut
    withheld: MoneyOut
    net: MoneyOut


class ExpectedOut(Model):
    symbol: str
    per_share: MoneyOut  # over the last 12 months
    payments: int
    net: MoneyOut  # the next 12 months on today's shares, after tax
    yield_on_value: Decimal | None
    yield_on_cost: Decimal | None


class DividendsOut(Model):
    received: list[DividendOut]
    received_home: MoneyOut | None
    this_year_home: MoneyOut | None
    expected: list[ExpectedOut]
    expected_home: MoneyOut | None


@router.get("/dividends")
async def dividends(auth: Auth, web: Runtime) -> DividendsOut:
    v = await investment_cases.dividend_view(web.uow, web.rates, auth.user, now=web.clock())
    return DividendsOut(
        received=[
            DividendOut(
                symbol=d.symbol, ex_date=d.ex_date, per_share=money(d.per_share),
                shares=plain(d.shares), gross=money(d.gross), withheld=money(d.withheld),
                net=money(d.net),
            )
            for d in v.received
        ],
        received_home=_optional(v.received_home),
        this_year_home=_optional(v.this_year_home),
        expected=[
            ExpectedOut(
                symbol=e.symbol, per_share=money(e.per_share), payments=e.payments,
                net=money(e.net), yield_on_value=e.yield_on_value, yield_on_cost=e.yield_on_cost,
            )
            for e in v.expected
        ],
        expected_home=_optional(v.expected_home),
    )  # fmt: skip


# --- watchlist and one stock's research -------------------------------------------------


class WatchedOut(Model):
    symbol: str
    price: Decimal | None  # live while the market is open, else the last close; USD
    price_day: date | None  # the trading day the price belongs to
    price_kind: PriceKind | None
    price_at: datetime | None  # when it was traded; None for an official close
    day_percent: Decimal | None
    earnings: EarningsOut | None


class WatchlistOut(Model):
    stocks: list[WatchedOut]
    prices: bool
    news: bool


@router.get("/watchlist")
async def watchlist(auth: Auth, web: Runtime) -> WatchlistOut:
    now = web.clock()
    status = await quote_cases.refresh_own(web.uow, web.quotes, auth.user.id, now=now, watched=True)
    rows = await research_cases.watched(
        web.uow(), auth.user.id, today=now.date(), now=now, status=status
    )
    return WatchlistOut(
        stocks=[
            WatchedOut(
                symbol=r.symbol,
                price=r.price.price.quantize(Decimal("0.01")) if r.price else None,
                price_day=r.price.day if r.price else None,
                price_kind=r.price.kind if r.price else None,
                price_at=r.price.at if r.price else None,
                day_percent=(
                    percent(r.price.price - r.price.previous, r.price.previous)
                    if r.price and r.price.previous
                    else None
                ),
                earnings=_earnings(r.earnings),
            )
            for r in rows
        ],
        prices=web.prices,
        news=web.news,
    )


class WatchIn(Model):
    symbol: str = Field(min_length=1, max_length=12)


class WatchedResult(Model):
    added: bool  # false: it was already on the list


@router.post("/watchlist")
async def watch(body: WatchIn, auth: Auth, web: Runtime) -> WatchedResult:
    added = await research_cases.watch(
        web.uow(), auth.user.id, clean_symbol(body.symbol), now=web.clock()
    )
    return WatchedResult(added=added)


@router.delete("/watchlist/{symbol}", status_code=204)
async def unwatch(symbol: str, auth: Auth, web: Runtime) -> None:
    await research_cases.unwatch(web.uow(), auth.user.id, clean_symbol(symbol))


class LevelsOut(Model):
    as_of: date
    close: Decimal
    averages: dict[str, Decimal]  # "20", "50", "200" → moving average
    trend: str | None
    rsi: Decimal | None
    atr: Decimal | None
    atr_percent: Decimal | None
    support: list[Decimal]
    resistance: list[Decimal]
    year_high: Decimal
    year_low: Decimal
    days: int


def _levels(levels: Levels) -> LevelsOut:
    return LevelsOut(
        as_of=levels.as_of,
        close=levels.close,
        averages={str(k): v for k, v in sorted(levels.averages.items())},
        trend=levels.trend,
        rsi=levels.rsi,
        atr=levels.atr,
        atr_percent=levels.atr_percent,
        support=levels.support,
        resistance=levels.resistance,
        year_high=levels.year_high,
        year_low=levels.year_low,
        days=levels.days,
    )


class RefreshedFromOut(Model):
    """The plan on the other end of a refresh: the one this replaced, or the one replacing it."""

    id: UUID
    created_at: datetime


class PlanBrief(Model):
    id: UUID
    symbol: str
    verdict: str
    verdict_text: str
    headline: str  # "NVDA: Keep holding"
    reason: str
    summary_line: str  # the headline and the game plan, as lines
    created_at: datetime
    valid_until: date
    expired: bool
    status: str  # "open", "target", "stopped", "expired" or "refreshed" (replaced by its refresh)
    entered_on: date | None  # the buy zone was reached (a held stock: always)
    outcome_day: date | None
    outcome_price: Decimal | None
    result_percent: Decimal | None
    alerts: bool
    followed: bool  # makes a call that's followed and scored
    # Made again by itself when it goes stale (open plans only).
    keep_fresh: bool = False
    refreshed_from: RefreshedFromOut | None = None  # the plan this one replaced
    # The price it was written with: live, provisional close or close (none on older plans).
    price: Decimal | None = None
    price_at: datetime | None = None  # when it was traded; none for a close
    price_kind: PriceKind | None = None


def _brief(p: SavedPlan, today: date) -> PlanBrief:
    result = plan_cases.PlanResult.model_validate(p.body)
    return PlanBrief(
        id=p.id,
        symbol=p.symbol,
        verdict=p.verdict.value,
        verdict_text=result.verdict_text,
        headline=plan_cases.headline(result),
        reason=result.reason,
        summary_line=plan_cases.summary_line(result),
        created_at=p.created_at,
        valid_until=p.valid_until,
        expired=p.valid_until < today,
        status=p.status.value,
        entered_on=p.entered_on or (p.created_at.date() if p.held else None),
        outcome_day=p.outcome_day,
        outcome_price=p.outcome_price,
        result_percent=p.result_percent,
        alerts=p.alerts,
        followed=p.verdict in FOLLOWED,
        keep_fresh=p.keep_fresh,
        refreshed_from=(
            RefreshedFromOut(id=p.refreshed_from, created_at=p.refreshed_from_at)
            if p.refreshed_from is not None and p.refreshed_from_at is not None
            else None
        ),
        price=p.price.quantize(Decimal("0.01")) if p.price is not None else None,
        price_at=p.price_at,
        price_kind=p.price_kind,
    )


class RangeOut(Model):
    days: int
    label: str
    low_68: Decimal
    high_68: Decimal
    low_90: Decimal
    high_90: Decimal


class StockOut(Model):
    symbol: str
    held: PositionOut | None
    watching: bool
    levels: LevelsOut | None  # None until there's a month of prices
    earnings: EarningsOut | None
    news: list[NewsOut]
    prices: bool
    news_enabled: bool
    plan: PlanBrief | None  # the latest research plan
    plans_enabled: bool
    ranges: list[RangeOut]  # likely closes in a week, a month and three months
    history: list[str] = []  # its last year in numbers, as lines
    # Live while the market is open, else the last close; None until it has any price.
    price: Decimal | None = None
    price_day: date | None = None
    price_kind: PriceKind | None = None
    price_at: datetime | None = None  # when it was traded; None for an official close
    now_vs_levels: list[str] = []  # how that price stands against the levels, as short facts


@router.get("/stocks/{symbol}")
async def stock(symbol: str, auth: Auth, web: Runtime) -> StockOut:
    now = web.clock()
    today = now.date()
    ticker = clean_symbol(symbol)  # checked before anything is asked of the quote provider
    # The one stock the page is about, whoever holds it; the limit keeps a member from
    # using up the provider's allowance on tickers they page through.
    status = await quote_cases.refresh_own(
        web.uow,
        web.quotes,
        auth.user.id,
        now=now,
        symbol=ticker if web.limits.allow("quote", auth.user.id) else None,
    )
    view = await research_cases.stock(
        web.uow(), auth.user, ticker, today=today, now=now, status=status
    )
    saved = await plan_cases.list_plans(web.uow(), auth.user.id, symbol=view.symbol)
    return StockOut(
        ranges=[
            RangeOut(
                days=r.days,
                label=r.label,
                low_68=r.low_68,
                high_68=r.high_68,
                low_90=r.low_90,
                high_90=r.high_90,
            )
            for r in view.ranges
        ],
        history=describe_history(view.history) if view.history else [],
        price=view.price.price.quantize(Decimal("0.01")) if view.price else None,
        price_day=view.price.day if view.price else None,
        price_kind=view.price.kind if view.price else None,
        price_at=view.price.at if view.price else None,
        now_vs_levels=view.now_vs_levels,
        symbol=view.symbol,
        held=_position(view.held) if view.held else None,
        watching=view.watching,
        levels=_levels(view.levels) if view.levels else None,
        earnings=_earnings(view.earnings),
        news=[_news(n) for n in view.news],
        prices=web.prices,
        news_enabled=web.news,
        plan=_brief(saved[0], today) if saved else None,
        plans_enabled=plan_cases.KIND in web.departments.kinds,
    )


class StartedOut(Model):
    run_id: UUID
    title: str


@router.post("/stocks/{symbol}/plan")
async def start_plan(symbol: str, auth: Auth, web: Runtime) -> StartedOut:
    """Start the research team on a plan; it runs in the background."""
    run = await plan_cases.start_plan(web.uow, web.departments, auth.user, symbol, now=web.clock())
    return StartedOut(run_id=run.id, title=run.title)


class RecordOut(Model):
    finished: int
    targets: int
    stopped: int
    expired: int
    never_entered: int
    average_result: Decimal | None
    open: int
    text: str
    odds_plans: int  # finished plans that had odds
    odds_said: int | None  # the average chance they gave the first target, %
    odds_happened: int | None  # how many reached it, %


@router.get("/plans/record")
async def plan_record(auth: Auth, web: Runtime) -> RecordOut:
    """How finished plans turned out, misses included."""
    r, _ = await plan_cases.track_record(web.uow(), auth.user.id)
    return RecordOut(
        finished=r.finished,
        targets=r.targets,
        stopped=r.stopped,
        expired=r.expired,
        never_entered=r.never_entered,
        average_result=r.average_result,
        open=r.open,
        text=plan_cases.describe_record(r),
        odds_plans=r.calibration.plans if r.calibration else 0,
        odds_said=r.calibration.said if r.calibration else None,
        odds_happened=r.calibration.happened if r.calibration else None,
    )


class AlertsIn(Model):
    on: bool


@router.post("/plans/{plan_id}/alerts", status_code=204)
async def plan_alerts(plan_id: str, body: AlertsIn, auth: Auth, web: Runtime) -> None:
    try:
        key = UUID(plan_id)
    except ValueError as exc:
        raise NotFound("that plan isn't in your list") from exc
    await plan_cases.set_alerts(web.uow(), auth.user.id, key, on=body.on)


class KeepFreshIn(Model):
    on: bool


@router.put("/plans/{plan_id}/keep-fresh", status_code=204)
async def plan_keep_fresh(plan_id: str, body: KeepFreshIn, auth: Auth, web: Runtime) -> None:
    """Make the plan again by itself when it goes stale. The user's own open plans only
    (404 for any other, 422 for one that has finished)."""
    try:
        key = UUID(plan_id)
    except ValueError as exc:
        raise NotFound("that plan isn't in your list") from exc
    await plan_cases.set_keep_fresh(web.uow(), auth.user.id, key, on=body.on)


@router.get("/plans")
async def plans(auth: Auth, web: Runtime) -> list[PlanBrief]:
    today = web.clock().date()
    return [_brief(p, today) for p in await plan_cases.list_plans(web.uow(), auth.user.id)]


class ClosePoint(Model):
    day: date
    close: Decimal


class PlanOut(Model):
    brief: PlanBrief
    plan: dict[str, Any]  # the full write-up, as the research team returned it
    closes: list[ClosePoint]  # recent daily closes, for the chart
    replaced_by: RefreshedFromOut | None = None  # the newest plan that replaced this one


CHART_DAYS = 90


@router.get("/plans/{plan_id}")
async def plan(plan_id: str, auth: Auth, web: Runtime) -> PlanOut:
    try:
        key = UUID(plan_id)
    except ValueError as exc:
        raise NotFound("that plan isn't in your list") from exc
    saved = await plan_cases.get_plan(web.uow(), auth.user.id, key)
    async with web.uow() as tx:
        bars = await tx.investments.bars(saved.symbol, CHART_DAYS)
        newer = await tx.investments.replaced_by(auth.user.id, saved.id)
    return PlanOut(
        brief=_brief(saved, web.clock().date()),
        plan=saved.body,
        closes=[ClosePoint(day=b.day, close=b.close.quantize(Decimal("0.01"))) for b in bars],
        replaced_by=RefreshedFromOut(id=newer.id, created_at=newer.created_at) if newer else None,
    )


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise NotFound("that screenshot isn't waiting any more") from exc
