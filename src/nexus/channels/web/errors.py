from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nexus.domain.errors import (
    Conflict,
    Forbidden,
    InvalidInput,
    NexusError,
    NotFound,
    NothingToUndo,
)

_STATUS: tuple[tuple[type[NexusError], int], ...] = (
    (NotFound, 404),
    (Forbidden, 403),
    (InvalidInput, 422),
    (Conflict, 409),
    (NothingToUndo, 409),
)


def install_error_handlers(app: FastAPI) -> None:
    """Expected use-case failures become clear HTTP errors, never 500s."""

    async def handle(request: Request, exc: Exception) -> JSONResponse:
        status = next((code for kind, code in _STATUS if isinstance(exc, kind)), 400)
        return JSONResponse({"detail": str(exc)}, status_code=status)

    app.add_exception_handler(NexusError, handle)
