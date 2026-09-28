from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    engine: AsyncEngine = request.app.state.engine
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok"}
