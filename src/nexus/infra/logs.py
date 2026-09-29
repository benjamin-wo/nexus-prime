"""Logging setup: the app's own messages at INFO, and no secrets in access logs."""

import logging
import sys
from typing import Any

# Query strings on these paths carry one-time tokens or OAuth codes.
_SECRET_PATHS = ("/api/email/", "/connect/", "/api/auth/", "/invite/")


class RedactQueries(logging.Filter):
    """Drop the query string from access-log lines for paths that carry secrets."""

    def filter(self, record: logging.LogRecord) -> bool:
        args: Any = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if "?" in path and path.startswith(_SECRET_PATHS):
                record.args = (*args[:2], path.split("?", 1)[0] + "?…", *args[3:])
        return True


def configure_logging() -> None:
    """Idempotent: safe to call once per app created."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactQueries) for f in access.filters):
        access.addFilter(RedactQueries())
    app = logging.getLogger("nexus")
    if not app.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        app.addHandler(handler)
        app.setLevel(logging.INFO)
        app.propagate = False
