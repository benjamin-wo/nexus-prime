"""PostgreSQL storage for exchange rates already looked up. Shared by all users: a
rate is public reference data, not anyone's own."""

from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.application.fx import Rate
from nexus.infra.db.tables import fx_rates


class SqlRateRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def stored_rate(self, base: str, quote: str, day: date) -> Rate | None:
        row = (
            await self._c.execute(
                select(fx_rates.c.value, fx_rates.c.effective).where(
                    and_(fx_rates.c.base == base, fx_rates.c.quote == quote, fx_rates.c.day == day)
                )
            )
        ).first()
        return Rate(base, quote, row.value, row.effective) if row else None

    async def save_rate(self, day: date, rate: Rate) -> None:
        await self._c.execute(
            pg_insert(fx_rates)
            .values(
                base=rate.base,
                quote=rate.quote,
                day=day,
                value=rate.value,
                effective=rate.effective,
            )
            .on_conflict_do_nothing()
        )
