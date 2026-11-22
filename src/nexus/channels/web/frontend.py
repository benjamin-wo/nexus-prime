"""Serve the built React app (web/dist) with a strict Content-Security-Policy.

Any path that isn't an API, webhook or health route gets index.html, so the
client-side router can handle it. The exceptions are the public pages (the landing page at
``/`` for anyone without a session cookie, and /privacy, /terms and /support), which are
prerendered HTML from the second Vite entry (dist/landing/).
"""

from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nexus.channels.web.security import COOKIE

DIST = Path(__file__).resolve().parents[4] / "web" / "dist"
_BACKEND_PREFIXES = ("api/", "telegram/", "healthz")
# Public pages built from web/landing/<name>.html, served at /<path> ("" is the landing page).
_PUBLIC_PAGES = {"": "index", "privacy": "privacy", "terms": "terms", "support": "support"}

# Google's map on the trip page loads its script from maps.googleapis.com, draws tiles
# and icons from Google's image hosts, calls its own APIs and adds <style> elements of
# its own (hence 'unsafe-inline' for styles only; scripts stay strict).
_MAPS_IMAGES = "https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.googleusercontent.com"
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://telegram.org https://maps.googleapis.com",
        "frame-src https://oauth.telegram.org",
        f"img-src 'self' data: blob: https://t.me https://*.telegram.org {_MAPS_IMAGES}",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self'",
        "connect-src 'self' https://*.googleapis.com https://*.google.com https://*.gstatic.com",
        "worker-src blob:",
        "base-uri 'none'",
        "form-action 'self'",
        # Telegram's web clients show the Mini App in an iframe; nobody else may.
        "frame-ancestors https://web.telegram.org",
    ]
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
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

    public = {
        path: dist / "landing" / f"{name}.html"
        for path, name in _PUBLIC_PAGES.items()
        if (dist / "landing" / f"{name}.html").is_file()
    }

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> Response:
        if path.startswith(_BACKEND_PREFIXES):
            return Response(status_code=404)
        page = public.get(path.rstrip("/"))
        # The landing page is for visitors; a signed-in person at / gets the app (which sends
        # them on to /app). The other public pages are the same for everyone.
        if page is not None and (path.rstrip("/") != "" or COOKIE not in request.cookies):
            return FileResponse(page, headers={"Cache-Control": "no-cache", "Vary": "Cookie"})
        if path in top_level:
            return FileResponse(top_level[path])
        headers = {"Cache-Control": "no-cache"}
        if path.startswith("shared/"):
            # A trip's read-only link is for whoever it was sent to, not search engines,
            # and its address never leaves the page (the default same-origin policy).
            headers["X-Robots-Tag"] = "noindex, nofollow"
        else:
            # Elsewhere, other sites see only our origin, never a path: Google checks it
            # against the map key's allowed websites.
            headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return FileResponse(index, headers=headers)
