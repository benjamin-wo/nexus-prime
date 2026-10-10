"""Logging setup: the app's own messages at INFO, and no secrets in access logs."""

import json
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


class JsonLines(logging.Formatter):
    """One JSON object per line. Railway reads its ``level``, so INFO shows as info,
    not as an error because it went to stderr."""

    def format(self, record: logging.LogRecord) -> str:
        message = f"{record.name}: {record.getMessage()}"
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        return json.dumps({"level": record.levelname.lower(), "message": message})


def configure_logging() -> None:
    """Idempotent: safe to call once per app created."""
    # HTTP client libraries log request URLs at INFO, and Telegram's carry the bot
    # token: they're held to warnings.
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactQueries) for f in access.filters):
        access.addFilter(RedactQueries())
    app = logging.getLogger("nexus")
    if not app.handlers:
        app.addHandler(_json_handler())
        app.setLevel(logging.INFO)
        app.propagate = False
    # Uvicorn's own lines ("Started server process") go to stderr, which Railway shows
    # as errors: they go out as JSON lines with their real level instead.
    server = logging.getLogger("uvicorn.error")
    if not any(isinstance(h.formatter, JsonLines) for h in server.handlers):
        server.handlers = [_json_handler()]


def _json_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLines())
    return handler
