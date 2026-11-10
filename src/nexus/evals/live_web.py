"""``--live-web``: the evals' web_search tool asks the real web, built as the app builds it
(Tavily's pages, read by the travel research model, within the monthly credits).

The eval clock is fixed (``seed.NOW``, 28 September 2026), because the seeded data and the
grading are dated by it, but a live search sees today's web. So the cases that search the
web run on the real time (``run_cases(now=...)``) and "today" or "this weekend" is the
same day for the agent and for the pages. Each web case
costs about one search credit and the model's tokens. The credit count lives in the
throwaway database, so it starts again from zero every run: it is no cap across runs.
"""

from collections.abc import Callable
from contextlib import AsyncExitStack
from datetime import datetime

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.clock import utcnow
from nexus.application.web_lookup import WebLooker
from nexus.main import build_web, web_lookup
from nexus.settings import Settings

# Never connected to: Settings insists on a database, and the web search is given the
# eval database's engine directly.
_UNUSED_DATABASE = "postgresql+asyncpg://eval@localhost/eval"


def live_settings(openrouter_key: str, fallback_model: str) -> Settings:
    """The app's settings from the environment (TAVILY_API_KEY, TAVILY_MONTHLY_CREDITS,
    TRAVEL_RESEARCH_MODEL, ...), with the eval's OpenRouter key. The model that writes
    the answers is the app's if set, else ``fallback_model``. Exits without a Tavily key."""
    settings = Settings(database_url=_UNUSED_DATABASE, openrouter_api_key=SecretStr(openrouter_key))
    if settings.tavily_api_key is None:
        raise SystemExit("--live-web needs TAVILY_API_KEY to be set")
    if not (settings.travel_research_model or settings.openrouter_model):
        settings = settings.model_copy(update={"travel_research_model": fallback_model})
    return settings


async def live_lookup(
    settings: Settings,
    engine: AsyncEngine,
    stack: AsyncExitStack,
    clock: Callable[[], datetime] = utcnow,
) -> WebLooker:
    """The production web lookup, with its credits counted in the eval database."""
    web = await build_web(settings, engine, stack, clock)
    if web is None:  # pragma: no cover - live_settings always sets a key and a model
        raise SystemExit("--live-web could not set up the web search")
    return web_lookup(settings, web, clock)
