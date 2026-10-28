"""What the AI models cost: who asked for each call, for which feature, and what it cost.

Every model call is counted by the day (UTC), the user, the feature and the model: calls,
tokens and US dollars. Never what was asked or answered. The numbers are for the owner's cost
page (``GET /api/ops/costs``).

Who and which feature are context variables set where the work starts (a chat handler, a job
run), so no call site passes them down. A call made where none is set counts under
``unknown`` and no user. Charges are handed to a sink (the database writer in production) and
never block or fail the work they describe. Nothing is recorded until a sink is set.
"""

import contextlib
import functools
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID

from nexus.application.acting import current_user_id
from nexus.application.clock import utcnow

# Logs about recording costs are never recorded as ops events.
log = logging.getLogger("nexus.ops.costs")

UNKNOWN = "unknown"
MAX_FEATURE = 64
MAX_MODEL = 120

_feature: ContextVar[str | None] = ContextVar("cost_feature", default=None)
_user: ContextVar[UUID | None] = ContextVar("cost_user", default=None)
_UNSET: Any = object()

_sink: Callable[["Charge"], None] | None = None


@dataclass(frozen=True, slots=True)
class Charge:
    """What one or more calls cost: the unit that is buffered and stored."""

    day: date
    user_id: UUID | None
    feature: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost: Decimal  # US dollars

    @property
    def key(self) -> tuple[date, UUID | None, str, str]:
        return self.day, self.user_id, self.feature, self.model


def set_sink(sink: Callable[[Charge], None] | None) -> None:
    global _sink
    _sink = sink


def as_user(value: object) -> UUID | None:
    """A user id from a UUID or its text; None for anything else (a payload can hold
    anything)."""
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def current_feature() -> str:
    return _feature.get() or UNKNOWN


def current_user() -> UUID | None:
    """The user the work was marked as for, else the user it is being done for (the signed-in
    person of a web request)."""
    return _user.get() or as_user(current_user_id())


@contextlib.contextmanager
def scope(
    feature: str | None = None, *, user: object = _UNSET, keep: bool = False
) -> Iterator[None]:
    """Model calls inside count under ``feature`` and ``user``. A name left out stays as it
    is; ``user=None`` clears it (work for no one in particular). With ``keep``, a feature
    already named stays (a turn started by a voice note is still ``voice``)."""
    tokens: list[Token[Any]] = []
    if feature is not None and not (keep and _feature.get() is not None):
        tokens.append(_feature.set(feature[:MAX_FEATURE]))
    if user is not _UNSET:
        tokens.append(_user.set(as_user(user)))
    try:
        yield
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


def to_cost(value: object) -> Decimal:
    """Dollars from what a provider sent: a number or numeric text. Anything else (missing,
    negative, not a number) is zero."""
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        return Decimal(0)
    try:
        cost = Decimal(str(value).strip())
    except InvalidOperation:
        return Decimal(0)
    return cost if cost.is_finite() and cost > 0 else Decimal(0)


def to_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return max(0, int(value))


def record(
    model: str,
    *,
    input_tokens: object = 0,
    output_tokens: object = 0,
    cost: object = 0,
    at: datetime | None = None,
) -> None:
    """Count one call. Never raises."""
    sink = _sink
    if sink is None:
        return
    try:
        sink(
            Charge(
                day=(at or utcnow()).date(),
                user_id=current_user(),
                feature=current_feature(),
                model=(model or UNKNOWN)[:MAX_MODEL],
                calls=1,
                input_tokens=to_count(input_tokens),
                output_tokens=to_count(output_tokens),
                cost=to_cost(cost),
            )
        )
    except Exception:  # a charge must never break the call it describes
        log.debug("couldn't record a model cost", exc_info=True)


def as_feature[F: Callable[..., Awaitable[Any]]](name: str) -> Callable[[F], F]:
    """For a method ``(self, actor, ...)``: model calls inside count under ``name`` and
    ``actor``."""

    def decorate(method: F) -> F:
        @functools.wraps(method)
        async def wrapper(self: object, actor: object, *args: object, **kwargs: object) -> Any:
            with scope(name, user=actor):
                return await method(self, actor, *args, **kwargs)

        return cast(F, wrapper)

    return decorate
