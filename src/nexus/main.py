import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
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

from nexus.agent.email_reader import LlmEmailReader
from nexus.agent.graph import AgentDeps, AgentGraph
from nexus.agent.holdings_reader import HoldingsReader, LlmHoldingsReader
from nexus.agent.memory_writer import MemoryWriter
from nexus.agent.receipts import LlmReceiptReader, ReceiptReader
from nexus.agent.service import AgentService
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application import email as email_cases
from nexus.application.clock import utcnow
from nexus.application.departments import Departments, default_registry
from nexus.application.email import EmailRuntime
from nexus.application.fx import RateSource
from nexus.application.limits import RateLimiter
from nexus.application.market import PriceSource
from nexus.application.plans import plan_kind
from nexus.application.ports import (
    EmailReader,
    ForwardingInboxes,
    ReceiptStore,
    SignInMailbox,
)
from nexus.application.research import NewsSource
from nexus.application.travel_research import research_kind
from nexus.channels.telegram import webhook as telegram_webhook
from nexus.channels.telegram.client import HttpTelegramClient, TelegramClient
from nexus.channels.web import api as web_api
from nexus.channels.web import email_api, health, investments_api, travel_api
from nexus.channels.web.errors import install_error_handlers
from nexus.channels.web.frontend import mount_frontend
from nexus.channels.web.hardening import install_hardening
from nexus.channels.web.security import WebRuntime
from nexus.domain.ledger import User, UserId
from nexus.infra.crypto.fernet import FernetCipher
from nexus.infra.db.checkpointer import postgres_checkpointer
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import assert_schema_at_head
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.infra.email.agentmail import AgentMailInboxes
from nexus.infra.email.gmail import GmailMailbox
from nexus.infra.fx.frankfurter import FrankfurterRates
from nexus.infra.llm.factory import (
    ChatModels,
    build_chat_models,
    build_memory_model,
    build_research_models,
    build_screener,
    build_travel_sorter,
    openrouter_routing,
)
from nexus.infra.logs import configure_logging
from nexus.infra.market.finnhub import FinnhubNews
from nexus.infra.market.tiingo import TiingoPrices
from nexus.infra.search.openrouter_web import OpenRouterWebSearch
from nexus.infra.search.serpapi import SerpApiTravel
from nexus.infra.storage.s3 import S3ReceiptStore
from nexus.jobs.handlers import MEMORY_UPDATE, SCHEDULES, build_handlers
from nexus.jobs.runner import JobRunner
from nexus.settings import Environment, Settings, get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Overrides:
    """Swap in fakes for tests. Anything left None is built from settings."""

    models: ChatModels | None = None
    departments: Departments | None = None  # the registry, with test run kinds
    receipts: ReceiptReader | None = None
    holdings: HoldingsReader | None = None
    telegram: TelegramClient | None = None
    checkpointer: BaseCheckpointSaver[Any] | None = None
    clock: Callable[[], datetime] | None = None
    rates: RateSource | None = None
    prices: PriceSource | None = None
    news: NewsSource | None = None
    receipt_store: ReceiptStore | None = None
    mailbox: SignInMailbox | None = None
    forwarding: ForwardingInboxes | None = None
    email_reader: EmailReader | None = None


def _receipt_store(settings: Settings, overrides: Overrides) -> ReceiptStore | None:
    if overrides.receipt_store is not None:
        return overrides.receipt_store
    if not settings.storage_enabled:
        return None
    key, secret = settings.storage_access_key_id, settings.storage_secret_access_key
    if (
        settings.storage_bucket is None
        or settings.storage_endpoint is None
        or key is None
        or secret is None
    ):  # pragma: no cover - the settings validator requires all of them
        raise RuntimeError("receipt storage is half configured")
    return S3ReceiptStore(
        bucket=settings.storage_bucket,
        endpoint=settings.storage_endpoint,
        region=settings.storage_region,
        access_key_id=key.get_secret_value(),
        secret_access_key=secret.get_secret_value(),
        path_style=settings.storage_path_style,
    )


async def _prices(
    settings: Settings, overrides: Overrides, stack: AsyncExitStack
) -> PriceSource | None:
    """Daily stock prices, when a Tiingo key is set."""
    if overrides.prices is not None:
        return overrides.prices
    key = settings.tiingo_api_key
    if key is None:
        log.warning("TIINGO_API_KEY is not set; holdings won't be valued")
        return None
    http = await stack.enter_async_context(httpx.AsyncClient())
    return TiingoPrices(http, key.get_secret_value())


async def _news(
    settings: Settings, overrides: Overrides, stack: AsyncExitStack
) -> NewsSource | None:
    """Company news and earnings dates, when a Finnhub key is set."""
    if overrides.news is not None:
        return overrides.news
    key = settings.finnhub_api_key
    if key is None:
        log.warning("FINNHUB_API_KEY is not set; no news or earnings dates will be fetched")
        return None
    http = await stack.enter_async_context(httpx.AsyncClient())
    return FinnhubNews(http, key.get_secret_value())


async def _email_runtime(
    settings: Settings,
    overrides: Overrides,
    stack: AsyncExitStack,
    models: ChatModels,
    origin: str | None,
) -> EmailRuntime | None:
    """Connect Gmail and forwarding addresses, each when configured (both need the
    encryption key)."""
    if not (settings.gmail_enabled or settings.forwarding_enabled) or origin is None:
        return None
    key = settings.token_encryption_key
    if key is None:  # pragma: no cover - validated
        raise RuntimeError("email is configured without TOKEN_ENCRYPTION_KEY")
    http: httpx.AsyncClient | None = None

    async def client() -> httpx.AsyncClient:
        nonlocal http
        if http is None:
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=30))
        return http

    mailbox = overrides.mailbox
    if mailbox is None and settings.gmail_enabled:
        client_id, secret = settings.google_client_id, settings.google_client_secret
        if client_id is None or secret is None:  # pragma: no cover - validated
            raise RuntimeError("Gmail is half configured")
        mailbox = GmailMailbox(
            await client(), client_id=client_id, client_secret=secret.get_secret_value()
        )
    forwarding = overrides.forwarding
    if forwarding is None and settings.forwarding_enabled and settings.agentmail_api_key:
        forwarding = AgentMailInboxes(
            await client(),
            api_key=settings.agentmail_api_key.get_secret_value(),
            domain=settings.agentmail_domain,
        )
    reader = overrides.email_reader or LlmEmailReader(
        build_screener(settings, models.primary), models.primary
    )
    return EmailRuntime(
        mailbox=mailbox,
        reader=reader,
        cipher=FernetCipher(key.get_secret_value()),
        origin=origin,
        forwarding=forwarding,
    )


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
    settings: Settings,
    engine: AsyncEngine,
    overrides: Overrides,
    stack: AsyncExitStack,
    rates: RateSource,
    archive: ReceiptStore | None,
    models: ChatModels,
    email: EmailRuntime | None,
    departments: Departments | None = None,
) -> telegram_webhook.TelegramRuntime:
    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(engine)

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
            skill_tools=skills.tools(),
            health=_health(engine, models),
            clock=clock,
            rates=rates,
            connect_link=_connect_link(uow, email, clock),
            forward_address=_forward_address(uow, email, clock),
            departments=departments,
        )
    ).compile(checkpointer)
    receipts: ReceiptReader | None = overrides.receipts
    if receipts is None and models.vision is not None:
        receipts = LlmReceiptReader(models.vision)
    holdings: HoldingsReader | None = overrides.holdings
    if holdings is None and models.vision is not None:
        holdings = LlmHoldingsReader(models.vision)
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
        clock=clock,
        service=AgentService(
            graph,
            uow,
            receipts,
            clock,
            archive,
            rates,
            after_turn=_queue_memory(uow, clock),
            limiter=RateLimiter(clock=clock),
            holdings=holdings,
        ),
        client=client,
    )


async def _registry(
    settings: Settings,
    engine: AsyncEngine,
    models: ChatModels,
    rates: RateSource,
    stack: AsyncExitStack,
) -> Departments:
    """The departments, with the Investment research team and, with OpenRouter, the
    Travel researcher (live flight and hotel prices too with a SerpApi key)."""
    uow = lambda: SqlUnitOfWork(engine)  # noqa: E731
    analyst, lead = build_research_models(settings, models.primary)
    kinds = [plan_kind(uow, analyst, lead)]
    key = settings.openrouter_api_key
    model = settings.travel_research_model or settings.openrouter_model
    if key is not None and model:
        http = await stack.enter_async_context(httpx.AsyncClient())
        routed = model == settings.openrouter_model
        web = OpenRouterWebSearch(
            http,
            key.get_secret_value(),
            model,
            routing=openrouter_routing(settings) if routed else None,
        )
        prices = (
            SerpApiTravel(http, settings.serpapi_api_key.get_secret_value())
            if settings.serpapi_api_key is not None
            else None
        )
        if prices is None:
            log.warning("SERPAPI_API_KEY is not set; trip research uses web search for prices")
        sorter = build_travel_sorter(settings, model)
        kinds.append(research_kind(uow, web, sorter, rates, prices))
    else:
        log.warning("OpenRouter isn't set up; trip research is off")
    return default_registry(kinds)


def _queue_memory(
    uow: Callable[[], SqlUnitOfWork], clock: Callable[[], datetime]
) -> Callable[[UserId, list[str], str], Awaitable[None]]:
    """Queue the memory writer for a turn; the job runner does the work."""

    async def queue(actor: UserId, messages: list[str], ref: str) -> None:
        async with uow() as tx:
            await tx.jobs.enqueue(
                MEMORY_UPDATE,
                {"user_id": str(actor), "messages": messages},
                dedupe_key=f"memory:{actor}:{ref}",
                run_at=clock(),
            )
            await tx.commit()

    return queue


def _connect_link(
    uow: Callable[[], SqlUnitOfWork], email: EmailRuntime | None, clock: Callable[[], datetime]
) -> Callable[[User], Awaitable[str]] | None:
    if email is None or email.mailbox is None:
        return None

    async def make(user: User) -> str:
        token = await email_cases.create_link(uow(), user, now=clock())
        return email.connect_url(token)

    return make


def _forward_address(
    uow: Callable[[], SqlUnitOfWork], email: EmailRuntime | None, clock: Callable[[], datetime]
) -> Callable[[User], Awaitable[str]] | None:
    if email is None or email.forwarding is None:
        return None
    inboxes = email.forwarding

    async def make(user: User) -> str:
        connection = await email_cases.set_up_forwarding(
            uow, inboxes, email.cipher, user, now=clock()
        )
        return connection.address

    return make


async def _set_menu_button(client: TelegramClient, origin: str) -> None:
    """Point the bot's menu button at the web app. Best effort: the bot works without it."""
    try:
        await client.set_menu_button(telegram_webhook.APP_LABEL, f"{origin}/")
    except Exception:
        log.warning("could not set the Telegram menu button", exc_info=True)


def create_app(settings: Settings | None = None, overrides: Overrides | None = None) -> FastAPI:
    configure_logging()
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
                rates = extra.rates
                if rates is None:
                    http = await stack.enter_async_context(httpx.AsyncClient())
                    rates = FrankfurterRates(http)
                prices = await _prices(resolved, extra, stack)
                news = await _news(resolved, extra, stack)
                archive = _receipt_store(resolved, extra)
                if archive is None:
                    log.warning("receipt storage is not configured; receipt photos won't be kept")
                models = extra.models or build_chat_models(resolved)
                email = await _email_runtime(resolved, extra, stack, models, resolved.public_origin)
                departments = extra.departments or await _registry(
                    resolved, engine, models, rates, stack
                )
                telegram = await _telegram_runtime(
                    resolved, engine, extra, stack, rates, archive, models, email, departments
                )
                app.state.telegram = telegram
                origin = resolved.public_origin
                clock = extra.clock or utcnow
                if resolved.run_jobs:
                    runner = JobRunner(
                        engine,
                        build_handlers(
                            telegram.uow,
                            telegram.client,
                            rates,
                            clock,
                            archive,
                            email,
                            MemoryWriter(build_memory_model(resolved, models.primary)),
                            departments,
                            prices,
                            news,
                        ),
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
                        archive=archive,
                        email=email,
                        departments=departments,
                        prices=prices is not None,
                        news=news is not None,
                    )
                    menu = asyncio.create_task(_set_menu_button(telegram.client, origin))
                    stack.push_async_callback(_finish, menu)
            yield

    # The API's own docs map every route; they aren't served in production.
    hidden = resolved.environment is Environment.PROD
    app = FastAPI(
        title="Nexus Prime",
        lifespan=lifespan,
        docs_url=None if hidden else "/docs",
        redoc_url=None if hidden else "/redoc",
        openapi_url=None if hidden else "/openapi.json",
    )
    app.state.settings = resolved
    app.state.telegram = None
    app.state.web = None
    app.include_router(health.router)
    app.include_router(telegram_webhook.router)
    app.include_router(web_api.router)
    app.include_router(email_api.router)
    app.include_router(investments_api.router)
    app.include_router(travel_api.router)
    install_error_handlers(app)
    origin = resolved.public_origin
    install_hardening(app, https=bool(origin and origin.startswith("https://")))
    mount_frontend(app)
    return app


__all__ = ["BaseChatModel", "Overrides", "create_app"]
