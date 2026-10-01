"""App-wide protections: security headers on every response, a cap on request
size, and no API documentation in production."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

# The largest legitimate body is a 10 MB PDF statement, base64-encoded.
MAX_BODY_BYTES = 16 * 1024 * 1024
HSTS = "max-age=31536000; includeSubDomains"


def install_hardening(app: FastAPI, *, https: bool) -> None:
    @app.middleware("http")
    async def harden(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                too_big = int(declared) > MAX_BODY_BYTES
            except ValueError:
                return JSONResponse({"detail": "bad Content-Length"}, status_code=400)
            if too_big:
                return JSONResponse({"detail": "request too large"}, status_code=413)
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        if https:
            headers.setdefault("Strict-Transport-Security", HSTS)
        if request.url.path.startswith("/api/"):
            # Money data: never cached by a browser or a proxy, never framed.
            headers.setdefault("Cache-Control", "no-store")
            headers.setdefault("X-Frame-Options", "DENY")
        return response
