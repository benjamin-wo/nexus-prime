"""The HTTP client for outside services, timing each call as an "http" event: the
host, the status and how long it took. Never the path or query (Telegram's carry the
bot token), headers or bodies."""

import time
from typing import Any

import httpx

from nexus.application import ops

# Statuses below 500 that still mean something's wrong on our side of the call.
_FAILED = frozenset({401, 403, 429})


class TimedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started = time.monotonic()
        host = request.url.host or "?"
        try:
            response = await self._inner.handle_async_request(request)
        except Exception as exc:
            ops.emit(
                "http",
                host,
                ok=False,
                ms=(time.monotonic() - started) * 1000,
                error=type(exc).__name__,
            )
            raise
        status = response.status_code
        failed = status >= 500 or status in _FAILED
        ops.emit(
            "http",
            host,
            ok=not failed,
            ms=(time.monotonic() - started) * 1000,
            status=status,
            error=f"HTTP {status}" if failed else None,
        )
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def timed_client(**kwargs: Any) -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` whose calls are recorded as ops events."""
    return httpx.AsyncClient(transport=TimedTransport(httpx.AsyncHTTPTransport()), **kwargs)
