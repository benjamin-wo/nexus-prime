"""Your data: export all of it as a zip, or delete all of it.

    GET  /api/me/export   a zip of the user's own data (three an hour)
    POST /api/me/delete   {"confirm": "DELETE"}: removes the account and everything in it

Both are for owners and members; guests are refused like on every route but their trips.
"""

from collections.abc import Iterator
from typing import IO, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from nexus.agent.graph import thread_id
from nexus.application import erasure, export
from nexus.channels.web.api import ledger_csv
from nexus.channels.web.security import Auth, Runtime, clear_session_cookie, limit

router = APIRouter(prefix="/api/me")
_CHUNK = 64 * 1024


def _chunks(archive: IO[bytes]) -> Iterator[bytes]:
    try:
        while chunk := archive.read(_CHUNK):
            yield chunk
    finally:
        archive.close()


@router.get("/export")
async def export_my_data(auth: Auth, web: Runtime) -> StreamingResponse:
    limit(web, auth, "export")
    user = auth.user
    now = web.clock()
    ledger = await ledger_csv(web, auth)
    archive = await export.build_export(web.uow, web.archive, user, ledger_csv=ledger, now=now)
    size = archive.seek(0, 2)
    archive.seek(0)
    stamp = now.astimezone(ZoneInfo(user.timezone)).strftime("%Y%m%d")
    return StreamingResponse(
        _chunks(archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="nexus-export-{stamp}.zip"',
            "Content-Length": str(size),
            "Cache-Control": "no-store",
        },
    )


class DeleteIn(BaseModel):
    # Exact: no stripping, no other spelling.
    model_config = ConfigDict(extra="forbid")
    confirm: Literal["DELETE"]


@router.post("/delete", status_code=204)
async def delete_my_data(body: DeleteIn, auth: Auth, web: Runtime, response: Response) -> None:
    await erasure.delete_user_data(
        web.uow,
        auth.user,
        chat_thread=thread_id(auth.user.id),
        store=web.archive,
        email=web.email,
    )
    clear_session_cookie(response)
