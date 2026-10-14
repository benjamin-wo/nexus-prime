"""Operational events: what the app did and how it went, for finding failures and
slow spots. Never what anyone said, wrote or spent.

An event is a kind ("turn", "model", "tool", "job", "request", "http", "log"), a
name (a channel, a model id, a tool, a job kind, a route template, a host or a
logger), whether it went well, how long it took, and a few details that are counts,
names, status codes and error types only. The user is a short keyed hash, so events
from one person can be told apart without saying who.

Events are handed to a sink (the database writer in production) and never block or
fail the work they describe. Nothing is recorded until a sink is set.
"""

import contextlib
import hashlib
import hmac
import logging
import re
import uuid
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from nexus.application.clock import utcnow

# Logs about recording events are never recorded as events.
LOGGER = "nexus.ops"
log = logging.getLogger(LOGGER)

_trace: ContextVar[str | None] = ContextVar("ops_trace", default=None)
_user: ContextVar[str | None] = ContextVar("ops_user", default=None)
_channel: ContextVar[str | None] = ContextVar("ops_channel", default=None)

_sink: Callable[["Event"], None] | None = None
_salt = b"nexus-ops"


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    name: str
    ok: bool
    ms: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    trace: str | None = None
    user: str | None = None
    channel: str | None = None
    at: datetime = field(default_factory=utcnow)


def set_sink(sink: Callable[[Event], None] | None) -> None:
    global _sink
    _sink = sink


def set_salt(secret: str | bytes | None) -> None:
    """The key user references are hashed with: a server secret, so a reference
    can't be turned back into a user id by hashing ids."""
    global _salt
    if secret:
        _salt = secret.encode() if isinstance(secret, str) else secret


def user_ref(user_id: object) -> str:
    """A user, as a 10-character keyed hash."""
    return hmac.new(_salt, str(user_id).encode(), hashlib.sha256).hexdigest()[:10]


def new_trace() -> str:
    return uuid.uuid4().hex[:12]


def trace() -> str | None:
    return _trace.get()


def current_channel() -> str | None:
    return _channel.get()


def set_user(user_id: object) -> None:
    """Mark the rest of this task's events as this user's (a web request, once its
    session is checked). Ends with the task."""
    _user.set(user_ref(user_id))


@contextlib.contextmanager
def scope(
    *,
    trace: str | None = None,
    user: object = None,
    channel: str | None = None,
    fresh: bool = False,
) -> Iterator[str]:
    """Events and log lines inside carry this trace (a new one unless given), user and
    channel. ``fresh`` starts with no user (a new request on a reused connection)."""
    tokens = [_trace.set(trace or _trace.get() or new_trace())]
    if user is not None or fresh:
        tokens.append(_user.set(None if user is None else user_ref(user)))
    if channel is not None:
        tokens.append(_channel.set(channel))
    try:
        yield _trace.get() or ""
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


def emit(
    kind: str,
    name: str,
    *,
    ok: bool = True,
    ms: float | None = None,
    **detail: Any,
) -> None:
    """Record an event. Never raises."""
    sink = _sink
    if sink is None:
        return
    try:
        sink(
            Event(
                kind=kind,
                name=name[:120],
                ok=ok,
                ms=None if ms is None else int(ms),
                detail={k: v for k, v in detail.items() if v is not None},
                trace=_trace.get(),
                user=_user.get(),
                channel=_channel.get(),
            )
        )
    except Exception:  # an event must never break what it describes
        log.debug("couldn't record an ops event", exc_info=True)


# --- Turning warnings and errors into events -----------------------------------

_SRC = re.compile(r".*?/(src/nexus/.+|nexus/.+)$")


def where(path: str, line: int) -> str:
    """A code location as a repository path ("src/nexus/x.py:12"), never a full path."""
    m = _SRC.match(path.replace("\\", "/"))
    shown = m.group(1) if m else Path(path).name
    if shown.startswith("nexus/"):
        shown = f"src/{shown}"
    return f"{shown}:{line}"


def fingerprint(*parts: object) -> str:
    """A stable id for one kind of problem, the same every time it happens."""
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _origin(record: logging.LogRecord) -> str:
    """Where it went wrong: the innermost frame in the app's own code, else where it
    was logged."""
    if record.exc_info and record.exc_info[2] is not None:
        tb: TracebackType | None = record.exc_info[2]
        found: str | None = None
        while tb is not None:
            path = tb.tb_frame.f_code.co_filename
            if "/nexus/" in path.replace("\\", "/") and "site-packages" not in path:
                found = where(path, tb.tb_lineno)
            tb = tb.tb_next
        if found:
            return found
    return where(record.pathname, record.lineno)


class EventsFromLogs(logging.Handler):
    """Warnings and errors become "log" events, keyed by the message's template (a
    constant in the code, so never a user's words; the arguments aren't kept) and the
    exception's type (not its message)."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(LOGGER):
            return
        template = record.msg if isinstance(record.msg, str) else type(record.msg).__name__
        template = " ".join(template.split())[:160]
        error = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None
        place = _origin(record)
        emit(
            "log",
            record.name,
            ok=False,
            level=record.levelname.lower(),
            template=template,
            error=error,
            where=place,
            fp=fingerprint(record.name, template, error or ""),
        )
