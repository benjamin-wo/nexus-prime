import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from fastapi import FastAPI
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import AgentDeps, AgentGraph
from nexus.agent.receipts import LlmReceiptReader, ReceiptReader
from nexus.agent.service import AgentService
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application.clock import utcnow
from nexus.application.fx import RateSource
from nexus.channels.telegram import webhook as telegram_webhook
from nexus.channels.telegram.client import HttpTelegramClient, TelegramClient
from nexus.channels.web import api as web_api
from nexus.channels.web import health
from nexus.channels.web.errors import install_error_handlers
from nexus.channels.web.frontend import mount_frontend
from nexus.channels.web.security import WebRuntime
from nexus.infra.db.checkpointer import postgres_checkpointer
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import assert_schema_at_head
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.infra.fx.frankfurter import FrankfurterRates
from nexus.infra.llm.factory import ChatModels, build_chat_models
from nexus.jobs.handlers import SCHEDULES, build_handlers
from nexus.jobs.runner import JobRunner
from nexus.settings import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Overrides:
    """Swap in fakes for tests. Anything left None is built from settings."""

    models: ChatModels | None = None
    receipts: ReceiptReader | None = None
    telegram: TelegramClient | None = None
    checkpointer: BaseCheckpointSaver[Any] | None = None
    clock: Callable[[], datetime] | None = None
    rates: RateSource | None = None


async def _stop_worker(stop: asyncio.Event, worker: "asyncio.Task[None]") -> None:
    stop.set()
    # wait_for cancels the worker if a job is still running after 30s.
    with contextlib.suppress(asyncio.CancelledError, TimeoutError):
        await asyncio.wait_for(worker, timeout=30)


async def _finish(task: "asyncio.Task[None]") -> None:
    if not task.done():
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _health(engine: AsyncEngine, models: ChatModels) -> Callable[[], Any]:
    async def report() -> str:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            database = "the database is reachable"
        except Exception:
            database = "I can't reach the database"
        return f"I'm running: {database}, and I'm using the {models.description} model."

    return report


async def _telegram_runtime(
    settings: Settings, engine: AsyncEngine, overrides: Overrides, stack: AsyncExitStack
) -> telegram_webhook.TelegramRuntime:
    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(engine)

    models = overrides.models or build_chat_models(settings)
    skills = SkillLibrary.load()
    tools = build_tools(skills.body)
    skills.validate_tools(set(tools))
    clock = overrides.clock or utcnow
    checkpointer: BaseCheckpointSaver[Any]
    if overrides.checkpointer is not None:
        checkpointer = overrides.checkpointer
    else:
        checkpointer = await stack.enter_async_context(
            postgres_checkpointer(settings.database_url_str)
        )
    graph = AgentGraph(
        AgentDeps(
            uow=uow,
            tools=tools,
            primary=models.primary,
            fallbacks=models.fallbacks,
            skill_index=skills.index(),
            health=_health(engine, models),
            clock=clock,
        )
    ).compile(checkpointer)
    receipts: ReceiptReader | None = overrides.receipts
    if receipts is None and models.vision is not None:
        receipts = LlmReceiptReader(models.vision)
    client = overrides.telegram
    if client is None:
        token = settings.telegram_bot_token
        if token is None:  # pragma: no cover - guarded by telegram_enabled
            raise RuntimeError("Telegram is not configured")
        http = await stack.enter_async_context(httpx.AsyncClient())
        client = HttpTelegramClient(token.get_secret_value(), http)
    return telegram_webhook.TelegramRuntime(
        settings=settings,
        uow=uow,
        service=AgentService(graph, uow, receipts, clock),
        client=client,
    )


async def _set_menu_button(client: TelegramClient, origin: str) -> None:
    """Point the bot's menu button at the web app. Best effort: the bot works without it."""
    try:
        await client.set_menu_button(telegram_webhook.APP_LABEL, f"{origin}/")
    except Exception:
        log.warning("could not set the Telegram menu button", exc_info=True)


def create_app(settings: Settings | None = None, overrides: Overrides | None = None) -> FastAPI:
    resolved = settings or get_settings()
    extra = overrides or Overrides()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(resolved.database_url_str)
        async with AsyncExitStack() as stack:
            stack.push_async_callback(engine.dispose)
            await assert_schema_at_head(engine)
            app.state.engine = engine
            if resolved.telegram_enabled:
                telegram = await _telegram_runtime(resolved, engine, extra, stack)
                app.state.telegram = telegram
                origin = resolved.public_origin
                clock = extra.clock or utcnow
                rates = extra.rates
                if rates is None:
                    http = await stack.enter_async_context(httpx.AsyncClient())
                    rates = FrankfurterRates(http)
                if resolved.run_jobs:
                    runner = JobRunner(
                        engine,
                        build_handlers(telegram.uow, telegram.client, rates, clock),
                        schedules=SCHEDULES,
                        clock=clock,
                    )
                    stop = asyncio.Event()
                    worker = asyncio.create_task(runner.run(stop))
                    stack.push_async_callback(_stop_worker, stop, worker)
                if origin is not None:
                    app.state.web = WebRuntime(
                        settings=resolved,
                        origin=origin,
                        uow=telegram.uow,
                        service=telegram.service,
                        clock=clock,
                        bot_username=telegram.client.bot_username,
                        rates=rates,
                    )
                    menu = asyncio.create_task(_set_menu_button(telegram.client, origin))
                    stack.push_async_callback(_finish, menu)
            yield

    app = FastAPI(title="Nexus Prime", lifespan=lifespan)
    app.state.settings = resolved
    app.state.telegram = None
    app.state.web = None
    app.include_router(health.router)
    app.include_router(telegram_webhook.router)
    app.include_router(web_api.router)
    install_error_handlers(app)
    mount_frontend(app)
    return app


__all__ = ["BaseChatModel", "Overrides", "create_app"]
