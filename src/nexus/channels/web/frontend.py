"""Serve the built React app (web/dist) with a strict Content-Security-Policy.

Any path that isn't an API, webhook or health route gets index.html, so the
client-side router can handle it.
"""

from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parents[4] / "web" / "dist"
_BACKEND_PREFIXES = ("api/", "telegram/", "healthz")

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://telegram.org",
        "frame-src https://oauth.telegram.org",
        "img-src 'self' data: https://t.me https://*.telegram.org",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


def mount_frontend(app: FastAPI, dist: Path = DIST) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    index = dist / "index.html"
    if not index.is_file():
        return  # API-only (e.g. tests, or before the frontend is built)
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    # Top-level files in the build (favicon etc.), fixed at startup: nothing else is served.
    top_level = {p.name: p for p in dist.iterdir() if p.is_file() and p.name != "index.html"}

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(_BACKEND_PREFIXES):
            return Response(status_code=404)
        if path in top_level:
            return FileResponse(top_level[path])
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
