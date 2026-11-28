"""PostgreSQL storage for the Health foundation: samples, the profile and consent scopes.
Every query filters on user_id."""

from datetime import datetime, timedelta
from decimal import Decimal
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
    profile_undo,
)

UNDO_WINDOW = timedelta(minutes=30)


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


def _profile_json(profile: HealthProfile) -> dict[str, Any]:
    """A profile as JSON, for a profile_undo row: everything but the user and when."""
    return {
        "sex_for_equations": profile.sex_for_equations.value,
        "birth_year": profile.birth_year,
        "height_cm": None if profile.height_cm is None else str(profile.height_cm),
        "activity_level": profile.activity_level.value if profile.activity_level else None,
        "goal": profile.goal.value,
        "target_rate_pct_per_week": (
            None
            if profile.target_rate_pct_per_week is None
            else str(profile.target_rate_pct_per_week)
        ),
        "numbers_free": profile.numbers_free,
        "ed_history": profile.ed_history,
        "unit_system": profile.unit_system.value,
    }


def _profile_from_json(
    user_id: UserId, data: dict[str, Any], updated_at: datetime
) -> HealthProfile:
    height, rate = data["height_cm"], data["target_rate_pct_per_week"]
    return HealthProfile(
        user_id=user_id,
        sex_for_equations=Sex(data["sex_for_equations"]),
        birth_year=data["birth_year"],
        height_cm=None if height is None else Decimal(height),
        activity_level=ActivityLevel(data["activity_level"]) if data["activity_level"] else None,
        goal=Goal(data["goal"]),
        target_rate_pct_per_week=None if rate is None else Decimal(rate),
        numbers_free=data["numbers_free"],
        ed_history=data["ed_history"],
        unit_system=UnitSystem(data["unit_system"]),
        updated_at=updated_at,
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

    async def delete_profile(self, user_id: UserId) -> None:
        await self._connection.execute(
            delete(health_profiles).where(health_profiles.c.user_id == user_id)
        )

    # --- Undo for a profile change ---------------------------------------------------------

    async def add_profile_undo(
        self, user_id: UserId, token: str, previous: HealthProfile | None, at: datetime
    ) -> None:
        # Rows past their time are of no use: clear the user's own as one is added.
        await self._connection.execute(
            delete(profile_undo).where(
                profile_undo.c.user_id == user_id, profile_undo.c.created_at < at - UNDO_WINDOW
            )
        )
        await self._connection.execute(
            profile_undo.insert().values(
                token=token,
                user_id=user_id,
                previous=None if previous is None else _profile_json(previous),
                created_at=at,
            )
        )

    async def take_profile_undo(
        self, user_id: UserId, token: str, *, now: datetime
    ) -> tuple[bool, HealthProfile | None]:
        row = (
            await self._connection.execute(
                delete(profile_undo)
                .where(
                    profile_undo.c.user_id == user_id,
                    profile_undo.c.token == token,
                    profile_undo.c.created_at >= now - UNDO_WINDOW,
                )
                .returning(profile_undo.c.previous)
            )
        ).first()
        if row is None:
            return False, None
        previous = row.previous
        if previous is None:
            return True, None
        return True, _profile_from_json(user_id, previous, now)

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
