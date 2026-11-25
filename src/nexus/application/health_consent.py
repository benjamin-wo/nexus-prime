"""Health consent: the master agreement and the separate, withdrawable scopes.

``users.health_consent_at`` (see ``application.gym``) is the master "health processing"
consent; the scopes in ``health_consents`` sit beside it. A scope can only be granted while the
master consent is given, and every check needs both. Withdrawing keeps what is stored: deleting
data never needs consent.
"""

from dataclasses import dataclass
from datetime import datetime

from nexus.application.ports import UnitOfWork
from nexus.domain.health import ConsentScope, check_consent
from nexus.domain.ledger import UserId


@dataclass(frozen=True, slots=True)
class ScopeState:
    scope: ConsentScope
    granted_at: datetime | None  # when they last agreed; None if they never have
    withdrawn_at: datetime | None

    @property
    def active(self) -> bool:
        return self.granted_at is not None and self.withdrawn_at is None


@dataclass(frozen=True, slots=True)
class ConsentOverview:
    health_at: datetime | None  # the master consent
    scopes: tuple[ScopeState, ...]  # every scope, in a fixed order


async def require_consent(uow: UnitOfWork, user_id: UserId, scope: ConsentScope | None) -> None:
    """Inside the unit of work: raise ``ConsentRequired`` unless the master consent is given
    and, when ``scope`` is named, that scope too. Typed and chat entries pass ``None``."""
    master = await uow.gym.health_consent(user_id)
    active = await uow.health.active_scopes(user_id) if scope is not None else frozenset()
    check_consent(master, active, scope)


async def may_send_to_ai(uow: UnitOfWork, user_id: UserId) -> bool:
    """Whether this user's health data may go to the model provider: the master consent and
    the ``ai_processing`` scope, both given and neither withdrawn. The agent asks before it
    puts any health figure in a prompt."""
    async with uow:
        if await uow.gym.health_consent(user_id) is None:
            return False
        return ConsentScope.AI_PROCESSING in await uow.health.active_scopes(user_id)


async def overview(uow: UnitOfWork, user_id: UserId) -> ConsentOverview:
    async with uow:
        master = await uow.gym.health_consent(user_id)
        states = await uow.health.scope_states(user_id)
    return ConsentOverview(
        master,
        tuple(ScopeState(scope, *(states.get(scope) or (None, None))) for scope in ConsentScope),
    )


async def grant(
    uow: UnitOfWork, user_id: UserId, scope: ConsentScope, *, now: datetime
) -> ScopeState:
    """Agree to a scope (again, after withdrawing it; one already given keeps its date)."""
    async with uow:
        await require_consent(uow, user_id, None)
        await uow.health.grant_scope(user_id, scope, now)
        await uow.commit()
        granted, withdrawn = (await uow.health.scope_states(user_id))[scope]
    return ScopeState(scope, granted, withdrawn)


async def withdraw(
    uow: UnitOfWork, user_id: UserId, scope: ConsentScope, *, now: datetime
) -> ScopeState:
    """Take a scope back. Nothing stored is deleted; a scope never given stays so."""
    async with uow:
        await uow.health.withdraw_scope(user_id, scope, now)
        await uow.commit()
        granted, withdrawn = (await uow.health.scope_states(user_id)).get(scope, (None, None))
    return ScopeState(scope, granted, withdrawn)


async def turn_on(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> ConsentOverview:
    """One tap: the master consent and ``ai_processing`` together, in one unit of work. Each
    keeps its first date when it was already given; the other scopes stay as they were."""
    async with uow:
        if await uow.gym.health_consent(user_id) is None:
            await uow.gym.set_health_consent(user_id, now)
        await uow.health.grant_scope(user_id, ConsentScope.AI_PROCESSING, now)
        await uow.commit()
        states = await uow.health.scope_states(user_id)
        master = await uow.gym.health_consent(user_id)
    return ConsentOverview(
        master,
        tuple(ScopeState(scope, *(states.get(scope) or (None, None))) for scope in ConsentScope),
    )
