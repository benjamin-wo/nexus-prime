"""Who a piece of work is being done for, so the database can refuse anyone else's rows.

A web request (once its session is checked) and a chat turn name their user here. The unit of
work reads it when it opens a transaction and tells Postgres (``app.user_id``), where
row-level security shows and accepts only that user's rows. Background jobs and sign-in never
name one, so they see every row, as they must.

It is a context variable, so it ends with the task that set it; ``acting_as`` also puts it
back, so it can't reach work that runs later on the same task (every web request and Telegram
update runs inside ``acting_as(None)``, see ``channels.web.tracing``).
"""

import functools
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast

from nexus.domain.ledger import UserId

_current: ContextVar[UserId | None] = ContextVar("acting_user", default=None)


def current_user_id() -> UserId | None:
    """The user the current work is for; None for a job, a sign-in or an admin task."""
    return _current.get()


@contextmanager
def acting_as(user_id: UserId | None, *, keep: bool = False) -> Iterator[None]:
    """Do the work inside for ``user_id`` (None: for no one in particular). With ``keep``, a
    user already named stays: the signed-in person of a web request is the authority."""
    if keep and _current.get() is not None:
        yield
        return
    token = _current.set(user_id)
    try:
        yield
    finally:
        _current.reset(token)


def set_acting_user(user_id: UserId) -> None:
    """Name the user for the rest of this task, from a place that can't wrap what follows
    it (a web dependency). The code that starts the task wraps it in ``acting_as(None)``,
    which puts it back when the request is over."""
    _current.set(user_id)


def as_actor[F: Callable[..., Awaitable[Any]]](method: F) -> F:
    """For a method ``(self, actor, ...)``: run it for ``actor`` unless a user is already
    named."""

    @functools.wraps(method)
    async def wrapper(self: object, actor: UserId, *args: object, **kwargs: object) -> Any:
        with acting_as(actor, keep=True):
            return await method(self, actor, *args, **kwargs)

    return cast(F, wrapper)
