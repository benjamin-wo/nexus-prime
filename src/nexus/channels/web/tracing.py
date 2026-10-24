"""Gives each API request a trace (sent back as X-Trace-Id, and on its log lines and
events) and records it as a "request" event: the route's template, never the path
itself (which can carry ids), its status and how long until the response was sent."""

import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nexus.application import acting, ops

TRACED = ("/api/", "/telegram/")
HEADER = b"x-trace-id"


class Tracing:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] != "http" or not path.startswith(TRACED):
            await self.app(scope, receive, send)
            return
        channel = "web" if path.startswith("/api/") else "telegram"
        started = time.monotonic()
        done: dict[str, Any] = {}

        # ``acting_as(None)``: whoever the request signs in as is forgotten when it ends.
        with (
            ops.scope(trace=ops.new_trace(), channel=channel, fresh=True) as trace,
            acting.acting_as(None),
        ):

            async def traced_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    done["status"] = message["status"]
                    message["headers"] = [*message.get("headers", []), (HEADER, trace.encode())]
                elif message["type"] == "http.response.body" and not message.get("more_body"):
                    # Sent: what runs after (a Telegram update's handling) isn't the request.
                    done.setdefault("ms", (time.monotonic() - started) * 1000)
                await send(message)

            try:
                await self.app(scope, receive, traced_send)
            except Exception:
                done.setdefault("status", 500)
                raise
            finally:
                route = scope.get("route")
                template = getattr(route, "path", None) or "(no route)"
                status = int(done.get("status", 500))
                ops.emit(
                    "request",
                    f"{scope.get('method', '?')} {template}",
                    ok=status < 500,
                    ms=done.get("ms", (time.monotonic() - started) * 1000),
                    status=status,
                )
