"""PostgreSQL storage for holdings. Every query filters on user_id."""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Row, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.investments import DraftStatus, Holding, HoldingsDraft, Position, plain
from nexus.domain.ledger import UserId
from nexus.domain.market import Bar
from nexus.domain.money import Money
from nexus.infra.db.tables import holding_drafts, holdings, market_bars, market_symbols


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

    async def save_bars(self, symbol: str, bars: list[Bar], *, known: bool, at: datetime) -> None:
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
                    }
                    for b in bars
                ]
            )
            await self._db.execute(
                stmt.on_conflict_do_update(
                    index_elements=[market_bars.c.symbol, market_bars.c.day],
                    set_={
                        c: stmt.excluded[c]
                        for c in ("open", "high", "low", "close", "adj_close", "volume")
                    },
                )
            )
        stmt2 = pg_insert(market_symbols).values(symbol=symbol, fetched_at=at, known=known)
        await self._db.execute(
            stmt2.on_conflict_do_update(
                index_elements=[market_symbols.c.symbol],
                set_={"fetched_at": at, "known": known},
            )
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
            found.setdefault(r.symbol, []).append(
                Bar(r.symbol, r.day, r.open, r.high, r.low, r.close, r.adj_close, r.volume)
            )
        return found
