"""PostgreSQL storage for the Health foundation: samples, the profile and consent scopes.
Every query filters on user_id."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Row, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.health import (
    ActivityLevel,
    ConsentScope,
    Goal,
    HealthProfile,
    Sample,
    SampleKind,
    SampleSource,
    SampleUnit,
    Sex,
    UnitSystem,
)
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import (
    health_consents,
    health_profiles,
    health_safety_events,
    health_samples,
)


def _sample(row: Row[Any]) -> Sample:
    return Sample(
        id=row.id,
        user_id=UserId(row.user_id),
        kind=SampleKind(row.kind),
        value=row.value,
        unit=SampleUnit(row.unit),
        start_at=row.start_at,
        end_at=row.end_at,
        source=SampleSource(row.source),
        created_at=row.created_at,
        source_name=row.source_name,
        external_id=row.external_id,
    )


def _profile(row: Row[Any]) -> HealthProfile:
    return HealthProfile(
        user_id=UserId(row.user_id),
        sex_for_equations=Sex(row.sex_for_equations),
        birth_year=row.birth_year,
        height_cm=row.height_cm,
        activity_level=ActivityLevel(row.activity_level) if row.activity_level else None,
        goal=Goal(row.goal),
        target_rate_pct_per_week=row.target_rate_pct_per_week,
        numbers_free=row.numbers_free,
        ed_history=row.ed_history,
        unit_system=UnitSystem(row.unit_system),
        updated_at=row.updated_at,
    )


def _values(sample: Sample) -> dict[str, Any]:
    return {
        "id": sample.id,
        "user_id": sample.user_id,
        "kind": sample.kind.value,
        "value": sample.value,
        "unit": sample.unit.value,
        "start_at": sample.start_at,
        "end_at": sample.end_at,
        "source": sample.source.value,
        "source_name": sample.source_name,
        "external_id": sample.external_id,
        "created_at": sample.created_at,
    }


class SqlHealthRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    # --- consent scopes ------------------------------------------------------------------

    async def active_scopes(self, user_id: UserId) -> frozenset[ConsentScope]:
        rows = await self._connection.execute(
            select(health_consents.c.scope).where(
                health_consents.c.user_id == user_id, health_consents.c.withdrawn_at.is_(None)
            )
        )
        return frozenset(ConsentScope(r.scope) for r in rows)

    async def scope_states(
        self, user_id: UserId
    ) -> dict[ConsentScope, tuple[datetime, datetime | None]]:
        rows = await self._connection.execute(
            select(health_consents).where(health_consents.c.user_id == user_id)
        )
        return {ConsentScope(r.scope): (r.granted_at, r.withdrawn_at) for r in rows}

    async def grant_scope(self, user_id: UserId, scope: ConsentScope, at: datetime) -> None:
        insert = pg_insert(health_consents).values(
            user_id=user_id, scope=scope.value, granted_at=at, withdrawn_at=None
        )
        # A scope that is active keeps its first date; a withdrawn one starts again.
        await self._connection.execute(
            insert.on_conflict_do_update(
                index_elements=["user_id", "scope"],
                set_={"granted_at": at, "withdrawn_at": None},
                where=health_consents.c.withdrawn_at.is_not(None),
            )
        )

    async def withdraw_scope(self, user_id: UserId, scope: ConsentScope, at: datetime) -> None:
        await self._connection.execute(
            update(health_consents)
            .where(
                health_consents.c.user_id == user_id,
                health_consents.c.scope == scope.value,
                health_consents.c.withdrawn_at.is_(None),
            )
            .values(withdrawn_at=at)
        )

    # --- samples -------------------------------------------------------------------------

    async def get_sample(self, user_id: UserId, sample_id: UUID) -> Sample | None:
        row = (
            await self._connection.execute(
                select(health_samples).where(
                    health_samples.c.id == sample_id, health_samples.c.user_id == user_id
                )
            )
        ).first()
        return _sample(row) if row else None

    async def find_manual(
        self, user_id: UserId, kind: SampleKind, start_at: datetime
    ) -> Sample | None:
        row = (
            await self._connection.execute(
                select(health_samples).where(
                    health_samples.c.user_id == user_id,
                    health_samples.c.kind == kind.value,
                    health_samples.c.start_at == start_at,
                    health_samples.c.source.in_([SampleSource.MANUAL, SampleSource.CHAT]),
                    health_samples.c.external_id.is_(None),
                )
            )
        ).first()
        return _sample(row) if row else None

    async def add_sample(self, sample: Sample) -> None:
        await self._connection.execute(health_samples.insert().values(**_values(sample)))

    async def upsert_imported(self, sample: Sample) -> Sample:
        insert = pg_insert(health_samples).values(**_values(sample))
        stored = await self._connection.execute(
            insert.on_conflict_do_update(
                index_elements=[
                    health_samples.c.user_id,
                    health_samples.c.source,
                    func.coalesce(health_samples.c.source_name, ""),
                    health_samples.c.external_id,
                ],
                index_where=health_samples.c.external_id.is_not(None),
                set_={
                    "kind": insert.excluded.kind,
                    "value": insert.excluded.value,
                    "unit": insert.excluded.unit,
                    "start_at": insert.excluded.start_at,
                    "end_at": insert.excluded.end_at,
                },
            ).returning(health_samples)
        )
        return _sample(stored.one())

    async def update_sample(self, sample: Sample) -> bool:
        result = await self._connection.execute(
            update(health_samples)
            .where(health_samples.c.id == sample.id, health_samples.c.user_id == sample.user_id)
            .values(
                value=sample.value,
                unit=sample.unit.value,
                start_at=sample.start_at,
                end_at=sample.end_at,
            )
        )
        return bool(result.rowcount)

    async def delete_sample(self, user_id: UserId, sample_id: UUID) -> bool:
        result = await self._connection.execute(
            delete(health_samples).where(
                health_samples.c.id == sample_id, health_samples.c.user_id == user_id
            )
        )
        return bool(result.rowcount)

    async def list_samples(
        self,
        user_id: UserId,
        *,
        kind: SampleKind | None,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[Sample]:
        query = select(health_samples).where(
            health_samples.c.user_id == user_id,
            health_samples.c.start_at >= start,
            health_samples.c.start_at < end,
        )
        if kind is not None:
            query = query.where(health_samples.c.kind == kind.value)
        query = query.order_by(health_samples.c.start_at.desc(), health_samples.c.id).limit(limit)
        return [_sample(r) for r in (await self._connection.execute(query)).all()]

    async def latest_sample(
        self, user_id: UserId, kind: SampleKind, *, until: datetime
    ) -> Sample | None:
        row = (
            await self._connection.execute(
                select(health_samples)
                .where(
                    health_samples.c.user_id == user_id,
                    health_samples.c.kind == kind.value,
                    health_samples.c.start_at <= until,
                )
                .order_by(health_samples.c.start_at.desc(), health_samples.c.created_at.desc())
                .limit(1)
            )
        ).first()
        return _sample(row) if row else None

    # --- the profile ---------------------------------------------------------------------

    async def get_profile(self, user_id: UserId) -> HealthProfile | None:
        row = (
            await self._connection.execute(
                select(health_profiles).where(health_profiles.c.user_id == user_id)
            )
        ).first()
        return _profile(row) if row else None

    async def save_profile(self, profile: HealthProfile) -> None:
        values = {
            "sex_for_equations": profile.sex_for_equations.value,
            "birth_year": profile.birth_year,
            "height_cm": profile.height_cm,
            "activity_level": profile.activity_level.value if profile.activity_level else None,
            "goal": profile.goal.value,
            "target_rate_pct_per_week": profile.target_rate_pct_per_week,
            "numbers_free": profile.numbers_free,
            "ed_history": profile.ed_history,
            "unit_system": profile.unit_system.value,
            "updated_at": profile.updated_at,
        }
        insert = pg_insert(health_profiles).values(user_id=profile.user_id, **values)
        await self._connection.execute(
            insert.on_conflict_do_update(index_elements=["user_id"], set_=values)
        )

    # --- safety events -------------------------------------------------------------------

    async def last_safety_event(self, user_id: UserId, kind: str) -> datetime | None:
        last: datetime | None = (
            await self._connection.execute(
                select(func.max(health_safety_events.c.created_at)).where(
                    health_safety_events.c.user_id == user_id,
                    health_safety_events.c.kind == kind,
                )
            )
        ).scalar_one()
        return last

    async def add_safety_event(self, user_id: UserId, kind: str, at: datetime) -> None:
        await self._connection.execute(
            health_safety_events.insert().values(
                id=uuid4(), user_id=user_id, kind=kind, created_at=at
            )
        )
