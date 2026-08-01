from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from langchain_core.tools import tool
from sqlmodel import select
from core.config import settings
from core.db import async_session_factory
from core.models import UserProfile


@tool
async def search_web(query: str) -> str:
    """
    Search the web for general informational facts, trivia, or definitions.
    MUST NOT be used for transactional actions or modifying external systems.
    """
    api_key = settings.tavily_api_key
    if not api_key or api_key.startswith("your_"):
        return f"[search] No Tavily API key configured for query: {query}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_answer": True,
                },
            )
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return f"[search] Tavily error: {exc}"

    if resp.status_code != 200:
        return f"[search] Tavily status {resp.status_code}: {data.get('message', '')}"

    answer = data.get("answer")
    results = data.get("results") or []
    lines = []
    if answer:
        lines.append(f"Summary: {answer}")
    for item in results[:5]:
        title = item.get("title", "")
        url = item.get("url", "")
        content = (item.get("content") or "")[:300]
        lines.append(f"- {title} ({url}): {content}")
    return "\n".join(lines) if lines else f"[search] No results for: {query}"


@tool
async def get_current_time_in_user_tz(user_id: int) -> str:
    """
    Calculate the current local date and time in the user's configured timezone.
    """
    tz_name = "UTC"
    async with async_session_factory() as session:
        profile = await session.get(UserProfile, user_id)
        if profile and profile.current_timezone:
            tz_name = profile.current_timezone

    try:
        now_dt = datetime.now(ZoneInfo(tz_name))
    except Exception:
        tz_name = "UTC"
        now_dt = datetime.now(ZoneInfo("UTC"))

    return f"Current local time for user {user_id} ({tz_name}): {now_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}"
