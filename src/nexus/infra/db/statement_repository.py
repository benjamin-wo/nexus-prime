"""PostgreSQL storage for statement import: saved layouts and confirmed imports.
Every query filters on user_id."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.ledger import Source, UserId
from nexus.domain.statements import SavedMapping, StatementImport, mapping_from_json
from nexus.infra.db.tables import statement_imports, statement_mappings, transaction_sources


def _saved(row: Row[Any]) -> SavedMapping:
    return SavedMapping(
        id=row.id,
        user_id=UserId(row.user_id),
        name=row.name,
        header_key=row.header_key,
        mapping=mapping_from_json(row.mapping),
        updated_at=row.updated_at,
    )


def _import(row: Row[Any]) -> StatementImport:
    return StatementImport(
        id=row.id,
        user_id=UserId(row.user_id),
        file_name=row.file_name,
        transaction_ids=[UUID(t) for t in row.transaction_ids],
        created_at=row.created_at,
        undone_at=row.undone_at,
    )


class SqlStatementRepository:
    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    async def claimed(self, user_id: UserId, source: Source, external_ids: list[str]) -> set[str]:
        """Which of these ids were already imported (deleted transactions included)."""
        if not external_ids:
            return set()
        s = transaction_sources.c
        rows = await self._db.execute(
            select(s.external_id).where(
                s.user_id == user_id, s.source == source.value, s.external_id.in_(external_ids)
            )
        )
        return {r.external_id for r in rows}

    async def mapping_for(self, user_id: UserId, header_key: str) -> SavedMapping | None:
        m = statement_mappings.c
        row = (
            await self._db.execute(
                select(statement_mappings).where(m.user_id == user_id, m.header_key == header_key)
            )
        ).first()
        return _saved(row) if row else None

    async def list_mappings(self, user_id: UserId) -> list[SavedMapping]:
        m = statement_mappings.c
        rows = await self._db.execute(
            select(statement_mappings).where(m.user_id == user_id).order_by(m.name)
        )
        return [_saved(r) for r in rows]

    async def save_mapping(self, saved: SavedMapping, mapping: dict[str, Any]) -> None:
        """One layout per header row: saving again renames and replaces it."""
        stmt = pg_insert(statement_mappings).values(
            id=saved.id,
            user_id=saved.user_id,
            name=saved.name,
            header_key=saved.header_key,
            mapping=mapping,
            created_at=saved.updated_at,
            updated_at=saved.updated_at,
        )
        await self._db.execute(
            stmt.on_conflict_do_update(
                index_elements=[statement_mappings.c.user_id, statement_mappings.c.header_key],
                set_={
                    "name": stmt.excluded.name,
                    "mapping": stmt.excluded.mapping,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )

    async def delete_mapping(self, user_id: UserId, mapping_id: UUID) -> bool:
        m = statement_mappings.c
        result = await self._db.execute(
            delete(statement_mappings).where(m.user_id == user_id, m.id == mapping_id)
        )
        return bool(result.rowcount)

    async def insert_import(self, record: StatementImport) -> None:
        await self._db.execute(
            statement_imports.insert().values(
                id=record.id,
                user_id=record.user_id,
                file_name=record.file_name,
                transaction_ids=[str(t) for t in record.transaction_ids],
                created_at=record.created_at,
                undone_at=record.undone_at,
            )
        )

    async def list_imports(self, user_id: UserId, limit: int = 20) -> list[StatementImport]:
        i = statement_imports.c
        rows = await self._db.execute(
            select(statement_imports)
            .where(i.user_id == user_id)
            .order_by(i.created_at.desc())
            .limit(limit)
        )
        return [_import(r) for r in rows]

    async def get_import(
        self, user_id: UserId, import_id: UUID, *, for_update: bool = False
    ) -> StatementImport | None:
        i = statement_imports.c
        query = select(statement_imports).where(i.user_id == user_id, i.id == import_id)
        if for_update:
            query = query.with_for_update()
        row = (await self._db.execute(query)).first()
        return _import(row) if row else None

    async def mark_undone(self, user_id: UserId, import_id: UUID, at: datetime) -> None:
        i = statement_imports.c
        await self._db.execute(
            update(statement_imports)
            .where(i.user_id == user_id, i.id == import_id)
            .values(undone_at=at)
        )
