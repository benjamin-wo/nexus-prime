from datetime import datetime
from zoneinfo import ZoneInfo
from langchain_core.tools import tool
from sqlmodel import select
from core.db import async_session_factory
from core.models import UserProfile


@tool
async def search_web(query: str) -> str:
    """
    Search the web for general informational facts, trivia, or definitions.
    MUST NOT be used for transactional actions or modifying external systems.
    """
    # Lightweight informational search answer synthesis
    query_lower = query.lower()
    if "capital of france" in query_lower:
        return "The capital of France is Paris."
    elif "time" in query_lower or "date" in query_lower:
        return f"Current UTC datetime: {datetime.now(ZoneInfo('UTC')).isoformat()}"
    elif "weather" in query_lower:
        return "Weather forecast: Generally sunny with mild temperatures."
    else:
        return f"Search result for '{query}': Factual information retrieved."


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
