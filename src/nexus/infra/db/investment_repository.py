"""PostgreSQL storage for holdings. Every query filters on user_id."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Row, delete, func, insert, select, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.investments import (
    Dividend,
    DraftStatus,
    Holding,
    HoldingsDraft,
    Position,
    Trade,
    TradeSide,
    plain,
)
from nexus.domain.ledger import UserId
from nexus.domain.market import Bar
from nexus.domain.money import Money
from nexus.domain.news import EarningsDate, NewsItem
from nexus.domain.plans import FOLLOWED, Followed, PlanStatus, SavedPlan, Verdict
from nexus.infra.db.tables import (
    dividends,
    holding_drafts,
    holdings,
    market_bars,
    market_earnings,
    market_news,
    market_symbols,
    news_fetches,
    plans,
    trades,
    watchlist,
)


def _holding(row: Row[Any]) -> Holding:
    return Holding(
        id=row.id,
        user_id=UserId(row.user_id),
        position=Position(row.symbol, plain(row.quantity), Money(row.average_cost, row.currency)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _draft(row: Row[Any]) -> HoldingsDraft:
    return HoldingsDraft(
        id=row.id,
        user_id=UserId(row.user_id),
        positions=[Position.from_dict(p) for p in row.positions],
        status=DraftStatus(row.status),
        created_at=row.created_at,
    )


def _plan(row: Row[Any]) -> SavedPlan:
    return SavedPlan(
        id=row.id,
        user_id=UserId(row.user_id),
        run_id=row.run_id,
        symbol=row.symbol,
        verdict=Verdict(row.verdict),
        as_of=row.as_of,
        valid_until=row.valid_until,
        close=row.close,
        entry_low=row.entry_low,
        entry_high=row.entry_high,
        stop=row.stop,
        body=row.body,
        status=PlanStatus(row.status),
        created_at=row.created_at,
        entered_on=row.entered_on,
        checked_through=row.checked_through,
        outcome_price=row.outcome_price,
        outcome_day=row.outcome_day,
        result_percent=row.result_percent,
        alerts=row.alerts,
    )


def _bar_row(r: Any) -> Bar:
    return Bar(r.symbol, r.day, r.open, r.high, r.low, r.close, r.adj_close, r.volume, r.div_cash)


class SqlInvestmentRepository:
    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    async def list_holdings(self, user_id: UserId) -> list[Holding]:
        h = holdings.c
        rows = await self._db.execute(
            select(holdings).where(h.user_id == user_id).order_by(h.symbol)
        )
        return [_holding(r) for r in rows]

    async def save_position(self, user_id: UserId, position: Position, at: datetime) -> None:
        """Insert or replace the user's position in this stock."""
        stmt = pg_insert(holdings).values(
            id=uuid4(),
            user_id=user_id,
            symbol=position.symbol,
            quantity=position.quantity,
            average_cost=position.average_cost.amount,
            currency=position.average_cost.currency,
            created_at=at,
            updated_at=at,
        )
        await self._db.execute(
            stmt.on_conflict_do_update(
                index_elements=[holdings.c.user_id, holdings.c.symbol],
                set_={
                    "quantity": stmt.excluded.quantity,
                    "average_cost": stmt.excluded.average_cost,
                    "currency": stmt.excluded.currency,
                    "updated_at": at,
                },
            )
        )

    async def remove_position(self, user_id: UserId, symbol: str) -> bool:
        h = holdings.c
        result = await self._db.execute(
            delete(holdings).where(h.user_id == user_id, h.symbol == symbol)
        )
        return bool(result.rowcount)

    async def insert_draft(self, draft: HoldingsDraft) -> None:
        await self._db.execute(
            insert(holding_drafts).values(
                id=draft.id,
                user_id=draft.user_id,
                positions=[p.as_dict() for p in draft.positions],
                status=draft.status.value,
                created_at=draft.created_at,
            )
        )

    async def get_draft(
        self, user_id: UserId, draft_id: UUID, *, for_update: bool = False
    ) -> HoldingsDraft | None:
        d = holding_drafts.c
        stmt = select(holding_drafts).where(d.user_id == user_id, d.id == draft_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._db.execute(stmt)).first()
        return _draft(row) if row else None

    async def latest_waiting_draft(self, user_id: UserId) -> HoldingsDraft | None:
        d = holding_drafts.c
        row = (
            await self._db.execute(
                select(holding_drafts)
                .where(d.user_id == user_id, d.status == DraftStatus.WAITING.value)
                .order_by(d.created_at.desc())
                .limit(1)
            )
        ).first()
        return _draft(row) if row else None

    async def set_draft_status(self, user_id: UserId, draft_id: UUID, status: DraftStatus) -> None:
        d = holding_drafts.c
        await self._db.execute(
            update(holding_drafts)
            .where(d.user_id == user_id, d.id == draft_id)
            .values(status=status.value)
        )

    # --- market data, shared by every user ---

    async def held_symbols(self) -> list[str]:
        """Across all users: every stock someone holds."""
        rows = await self._db.execute(select(holdings.c.symbol).distinct().order_by("symbol"))
        return [r.symbol for r in rows]

    async def tracked_symbols(self) -> list[str]:
        """Across all users: every stock someone holds or watches."""
        both = union(select(holdings.c.symbol), select(watchlist.c.symbol)).subquery()
        rows = await self._db.execute(select(both.c.symbol).order_by(both.c.symbol))
        return [r.symbol for r in rows]

    async def fetched(self, symbols: list[str]) -> dict[str, datetime]:
        m = market_symbols.c
        rows = await self._db.execute(select(m.symbol, m.fetched_at).where(m.symbol.in_(symbols)))
        return {r.symbol: r.fetched_at for r in rows}

    async def last_bar_day(self, symbol: str) -> date | None:
        b = market_bars.c
        day: date | None = (
            await self._db.execute(select(func.max(b.day)).where(b.symbol == symbol))
        ).scalar()
        return day

    # --- trades and dividends -----------------------------------------------------------

    async def insert_trade(self, trade: Trade) -> None:
        await self._db.execute(
            insert(trades).values(
                id=trade.id,
                user_id=trade.user_id,
                symbol=trade.symbol,
                side=trade.side.value,
                quantity=trade.quantity,
                price=trade.price.amount if trade.price else None,
                currency=(trade.price or trade.realised or Money.zero("USD")).currency,
                traded_on=trade.traded_on,
                realised=trade.realised.amount if trade.realised else None,
                created_at=trade.created_at,
            )
        )

    async def list_trades(self, user_id: UserId, symbol: str | None = None) -> list[Trade]:
        t = trades.c
        conditions: list[Any] = [t.user_id == user_id]
        if symbol is not None:
            conditions.append(t.symbol == symbol)
        rows = await self._db.execute(
            select(trades).where(*conditions).order_by(t.traded_on, t.created_at)
        )
        return [
            Trade(
                id=r.id,
                user_id=UserId(r.user_id),
                symbol=r.symbol,
                side=TradeSide(r.side),
                quantity=r.quantity,
                price=Money(r.price, r.currency) if r.price is not None else None,
                traded_on=r.traded_on,
                realised=Money(r.realised, r.currency) if r.realised is not None else None,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def insert_dividend(self, dividend: Dividend) -> bool:
        stmt = (
            pg_insert(dividends)
            .values(
                id=dividend.id,
                user_id=dividend.user_id,
                symbol=dividend.symbol,
                ex_date=dividend.ex_date,
                per_share=dividend.per_share.amount,
                currency=dividend.per_share.currency,
                shares=dividend.shares,
                created_at=dividend.created_at,
            )
            .on_conflict_do_nothing()
            .returning(dividends.c.id)
        )
        return (await self._db.execute(stmt)).first() is not None

    async def list_dividends(self, user_id: UserId) -> list[Dividend]:
        d = dividends.c
        rows = await self._db.execute(
            select(dividends).where(d.user_id == user_id).order_by(d.ex_date.desc(), d.symbol)
        )
        return [
            Dividend(
                id=r.id,
                user_id=UserId(r.user_id),
                symbol=r.symbol,
                ex_date=r.ex_date,
                per_share=Money(r.per_share.quantize(Decimal("0.0001")), r.currency),
                shares=r.shares,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def holders(self, symbol: str) -> list[Holding]:
        rows = await self._db.execute(select(holdings).where(holdings.c.symbol == symbol))
        return [_holding(r) for r in rows]

    async def has_dividend_history(self, symbol: str) -> bool:
        """Whether the stock's full history was fetched with its dividends."""
        m = market_symbols.c
        found = (await self._db.execute(select(m.dividends).where(m.symbol == symbol))).scalar()
        return bool(found)

    async def dividends_since(self, symbols: list[str], since: date) -> list[Bar]:
        """The days a dividend went ex for these stocks, since ``since``, oldest first."""
        if not symbols:
            return []
        b = market_bars.c
        rows = await self._db.execute(
            select(market_bars)
            .where(b.symbol.in_(symbols), b.day >= since, b.div_cash > 0)
            .order_by(b.day, b.symbol)
        )
        return [_bar_row(r) for r in rows]

    async def save_bars(
        self,
        symbol: str,
        bars: list[Bar],
        *,
        known: bool,
        at: datetime,
        full_history: bool = False,
    ) -> None:
        """Store a stock's daily prices (a day already stored is replaced: providers
        correct a close now and then) and when they were fetched."""
        if bars:
            stmt = pg_insert(market_bars).values(
                [
                    {
                        "symbol": symbol,
                        "day": b.day,
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "adj_close": b.adj_close,
                        "volume": b.volume,
                        "div_cash": b.div_cash,
                    }
                    for b in bars
                ]
            )
            await self._db.execute(
                stmt.on_conflict_do_update(
                    index_elements=[market_bars.c.symbol, market_bars.c.day],
                    set_={
                        c: stmt.excluded[c]
                        for c in ("open", "high", "low", "close", "adj_close", "volume", "div_cash")
                    },
                )
            )
        stmt2 = pg_insert(market_symbols).values(
            symbol=symbol, fetched_at=at, known=known, dividends=full_history
        )
        changes: dict[str, Any] = {"fetched_at": at, "known": known}
        if full_history:
            changes["dividends"] = True
        await self._db.execute(
            stmt2.on_conflict_do_update(index_elements=[market_symbols.c.symbol], set_=changes)
        )

    async def latest_bars(self, symbols: list[str], count: int = 2) -> dict[str, list[Bar]]:
        """Each stock's last ``count`` days of prices, newest first."""
        if not symbols:
            return {}
        b = market_bars.c
        ranked = (
            select(
                market_bars,
                func.row_number().over(partition_by=b.symbol, order_by=b.day.desc()).label("n"),
            )
            .where(b.symbol.in_(symbols))
            .subquery()
        )
        rows = await self._db.execute(
            select(ranked).where(ranked.c.n <= count).order_by(ranked.c.symbol, ranked.c.n)
        )
        found: dict[str, list[Bar]] = {}
        for r in rows:
            found.setdefault(r.symbol, []).append(_bar_row(r))
        return found

    async def bars(self, symbol: str, count: int) -> list[Bar]:
        """A stock's last ``count`` days of prices, oldest first."""
        b = market_bars.c
        rows = await self._db.execute(
            select(market_bars).where(b.symbol == symbol).order_by(b.day.desc()).limit(count)
        )
        found = [_bar_row(r) for r in rows]
        return found[::-1]

    # --- watchlist ---

    async def list_watch(self, user_id: UserId) -> list[str]:
        w = watchlist.c
        rows = await self._db.execute(
            select(w.symbol).where(w.user_id == user_id).order_by(w.symbol)
        )
        return [r.symbol for r in rows]

    async def add_watch(self, user_id: UserId, symbol: str, at: datetime) -> bool:
        """False when the user already watches it."""
        stmt = (
            pg_insert(watchlist)
            .values(id=uuid4(), user_id=user_id, symbol=symbol, created_at=at)
            .on_conflict_do_nothing(index_elements=[watchlist.c.user_id, watchlist.c.symbol])
            .returning(watchlist.c.id)
        )
        return (await self._db.execute(stmt)).first() is not None

    async def remove_watch(self, user_id: UserId, symbol: str) -> bool:
        w = watchlist.c
        result = await self._db.execute(
            delete(watchlist).where(w.user_id == user_id, w.symbol == symbol)
        )
        return bool(result.rowcount)

    # --- news and earnings dates, shared by every user ---

    async def news_fetched(self, symbols: list[str]) -> dict[str, datetime]:
        n = news_fetches.c
        rows = await self._db.execute(select(n.symbol, n.fetched_at).where(n.symbol.in_(symbols)))
        return {r.symbol: r.fetched_at for r in rows}

    async def save_news(
        self,
        symbol: str,
        items: list[NewsItem],
        earnings: list[EarningsDate],
        *,
        at: datetime,
    ) -> None:
        """Add news not seen before, replace the stock's upcoming earnings dates, and
        note when they were fetched."""
        if items:
            await self._db.execute(
                pg_insert(market_news)
                .values(
                    [
                        {
                            "symbol": symbol,
                            "external_id": i.external_id,
                            "headline": i.headline,
                            "source": i.source,
                            "url": i.url,
                            "summary": i.summary,
                            "published_at": i.published_at,
                        }
                        for i in items
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=[market_news.c.symbol, market_news.c.external_id]
                )
            )
        e = market_earnings.c
        await self._db.execute(
            delete(market_earnings).where(e.symbol == symbol, e.day >= at.date())
        )
        if earnings:
            await self._db.execute(
                pg_insert(market_earnings)
                .values([{"symbol": symbol, "day": d.day, "timing": d.timing} for d in earnings])
                .on_conflict_do_nothing(index_elements=[e.symbol, e.day])
            )
        stmt = pg_insert(news_fetches).values(symbol=symbol, fetched_at=at)
        await self._db.execute(
            stmt.on_conflict_do_update(
                index_elements=[news_fetches.c.symbol], set_={"fetched_at": at}
            )
        )

    async def purge_news(self, before: datetime) -> int:
        result = await self._db.execute(
            delete(market_news).where(market_news.c.published_at < before)
        )
        return int(result.rowcount or 0)

    async def recent_news(self, symbol: str, limit: int) -> list[NewsItem]:
        n = market_news.c
        rows = await self._db.execute(
            select(market_news)
            .where(n.symbol == symbol)
            .order_by(n.published_at.desc())
            .limit(limit)
        )
        return [
            NewsItem(
                r.symbol, r.external_id, r.headline, r.source, r.url, r.summary, r.published_at
            )
            for r in rows
        ]

    async def upcoming_earnings(self, symbols: list[str], since: date) -> dict[str, EarningsDate]:
        """Each stock's next earnings date on or after ``since``."""
        if not symbols:
            return {}
        e = market_earnings.c
        rows = await self._db.execute(
            select(market_earnings)
            .where(e.symbol.in_(symbols), e.day >= since)
            .order_by(e.symbol, e.day)
        )
        found: dict[str, EarningsDate] = {}
        for r in rows:
            found.setdefault(r.symbol, EarningsDate(r.symbol, r.day, r.timing))
        return found

    # --- research plans ---

    async def insert_plan(self, plan: SavedPlan) -> None:
        await self._db.execute(
            insert(plans).values(
                id=plan.id,
                user_id=plan.user_id,
                run_id=plan.run_id,
                symbol=plan.symbol,
                verdict=plan.verdict.value,
                as_of=plan.as_of,
                valid_until=plan.valid_until,
                close=plan.close,
                entry_low=plan.entry_low,
                entry_high=plan.entry_high,
                stop=plan.stop,
                body=plan.body,
                status=plan.status.value,
                created_at=plan.created_at,
            )
        )

    async def list_plans(
        self, user_id: UserId, *, symbol: str | None = None, limit: int = 50
    ) -> list[SavedPlan]:
        """Newest first."""
        p = plans.c
        stmt = select(plans).where(p.user_id == user_id)
        if symbol is not None:
            stmt = stmt.where(p.symbol == symbol)
        rows = await self._db.execute(stmt.order_by(p.created_at.desc()).limit(limit))
        return [_plan(r) for r in rows]

    async def get_plan(self, user_id: UserId, plan_id: UUID) -> SavedPlan | None:
        p = plans.c
        row = (
            await self._db.execute(select(plans).where(p.user_id == user_id, p.id == plan_id))
        ).first()
        return _plan(row) if row else None

    async def plans_to_follow(self) -> list[SavedPlan]:
        """Across all users: open plans that make a call worth following."""
        p = plans.c
        rows = await self._db.execute(
            select(plans)
            .where(p.status == PlanStatus.OPEN.value, p.verdict.in_([v.value for v in FOLLOWED]))
            .order_by(p.created_at)
        )
        return [_plan(r) for r in rows]

    async def save_followed(
        self, user_id: UserId, plan_id: UUID, followed: Followed, *, at: datetime
    ) -> None:
        p = plans.c
        finished = followed.status is not PlanStatus.OPEN
        await self._db.execute(
            update(plans)
            .where(p.user_id == user_id, p.id == plan_id)
            .values(
                status=followed.status.value,
                entered_on=followed.entered_on,
                checked_through=followed.checked_through,
                outcome_price=followed.outcome_price,
                outcome_day=followed.outcome_day,
                result_percent=followed.result_percent,
                closed_at=at if finished else None,
            )
        )

    async def set_plan_alerts(self, user_id: UserId, plan_id: UUID, on: bool) -> bool:
        p = plans.c
        result = await self._db.execute(
            update(plans).where(p.user_id == user_id, p.id == plan_id).values(alerts=on)
        )
        return bool(result.rowcount)
