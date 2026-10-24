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
from nexus.agent.image_look import ImageLooker, LlmImageLooker
from nexus.agent.memory_writer import MemoryWriter
from nexus.agent.photo_picker import LlmChooser, LlmSpotter
from nexus.agent.receipts import LlmReceiptReader, ReceiptReader
from nexus.agent.service import AgentService
from nexus.agent.skills import SkillLibrary
from nexus.agent.statement_reader import LlmStatementReader
from nexus.agent.tools import build_tools
from nexus.agent.trip_reader import LlmTripReader, TripReader
from nexus.application import email as email_cases
from nexus.application import ops
from nexus.application.clock import utcnow
from nexus.application.departments import Departments, default_registry
from nexus.application.destination_photos import PhotoFinder
from nexus.application.email import EmailRuntime
from nexus.application.fx import RateSource
from nexus.application.ideas import IdeaFinder
from nexus.application.limits import RateLimiter
from nexus.application.market import PriceSource
from nexus.application.moves import Explainer
from nexus.application.places import Places, PlaceSource
from nexus.application.plans import plan_kind
from nexus.application.ports import (
    EmailReader,
    ForwardingInboxes,
    ReceiptStore,
    SignInMailbox,
    StatementPageReader,
)
from nexus.application.quotes import Quotes, QuoteSource
from nexus.application.rate_store import StoredRates
from nexus.application.research import NewsSource
from nexus.application.routes import Routes, RouteSource
from nexus.application.travel_research import research_kind
from nexus.application.weather import Weather, WeatherSource
from nexus.application.web_lookup import WebLookup
from nexus.application.web_search import KeptReader, KeptSearch, LiveSearch, Product, WebSearch
from nexus.application.whereabouts import ZoneFinder
from nexus.channels.telegram import webhook as telegram_webhook
from nexus.channels.telegram.client import HttpTelegramClient, TelegramClient
from nexus.channels.web import api as web_api
from nexus.channels.web import data_api, email_api, health, investments_api, ops_api, travel_api
from nexus.channels.web.errors import install_error_handlers
from nexus.channels.web.frontend import mount_frontend
from nexus.channels.web.hardening import install_hardening
from nexus.channels.web.security import WebRuntime
from nexus.channels.web.tracing import Tracing
from nexus.domain.ledger import User, UserId
from nexus.infra.crypto.fernet import FernetCipher
from nexus.infra.db.checkpointer import postgres_checkpointer
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import assert_schema_at_head
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.infra.email.agentmail import AgentMailInboxes
from nexus.infra.email.gmail import GmailMailbox
from nexus.infra.fx.frankfurter import FrankfurterRates
from nexus.infra.guides.wikivoyage import Wikivoyage
from nexus.infra.http import timed_client
from nexus.infra.llm.factory import (
    ChatModels,
    build_chat_models,
    build_email_reader,
    build_image_look_models,
    build_memory_model,
    build_research_models,
    build_research_reviewer,
    build_screener,
    build_screenshot_reader,
    build_travel_sorter,
    build_web_writer,
    openrouter_routing,
)
from nexus.infra.logs import configure_logging
from nexus.infra.market.finnhub import FinnhubNews
from nexus.infra.market.finnhub_quotes import FinnhubQuotes
from nexus.infra.market.tiingo import TiingoPrices
from nexus.infra.ops_store import OpsStore
from nexus.infra.photos.wikipedia import WikipediaPhotos
from nexus.infra.places.google import GooglePlaces
from nexus.infra.places.routes import GoogleRoutes
from nexus.infra.search.openrouter_web import OpenRouterWebSearch
from nexus.infra.search.serpapi import SerpApiTravel
from nexus.infra.search.tavily import TavilyReader, TavilySearch
from nexus.infra.storage.s3 import S3ReceiptStore
from nexus.infra.weather.open_meteo import OpenMeteo
from nexus.jobs import ops_tickets as ops_ticket_job
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
    trip_reader: TripReader | None = None
    image_looker: ImageLooker | None = None
    telegram: TelegramClient | None = None
    checkpointer: BaseCheckpointSaver[Any] | None = None
    clock: Callable[[], datetime] | None = None
    rates: RateSource | None = None
    prices: PriceSource | None = None
    news: NewsSource | None = None
    quotes: QuoteSource | None = None
    places: PlaceSource | None = None
    routes: RouteSource | None = None
    receipt_store: ReceiptStore | None = None
    mailbox: SignInMailbox | None = None
    forwarding: ForwardingInboxes | None = None
    email_reader: EmailReader | None = None
    photos: PhotoFinder | None = None
    weather: WeatherSource | None = None
    ideas: IdeaFinder | None = None
    lookup: WebLookup | None = None
    statement_pages: StatementPageReader | None = None


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
    http = await stack.enter_async_context(timed_client())
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
    http = await stack.enter_async_context(timed_client())
    return FinnhubNews(http, key.get_secret_value())


async def _quotes(settings: Settings, overrides: Overrides, stack: AsyncExitStack) -> Quotes | None:
    """Live stock quotes and the market's status, when a Finnhub key is set."""
    if overrides.quotes is not None:
        return Quotes(overrides.quotes)
    key = settings.finnhub_api_key
    if key is None:
        log.warning("FINNHUB_API_KEY is not set; stock prices won't be live")
        return None
    http = await stack.enter_async_context(timed_client())
    return Quotes(FinnhubQuotes(http, key.get_secret_value()))


async def _places(
    settings: Settings, overrides: Overrides, stack: AsyncExitStack, clock: Callable[[], datetime]
) -> Places | None:
    """Google Maps places for trips, when a Places API key is set."""
    source = overrides.places
    if source is None:
        key = settings.google_places_api_key
        if key is None:
            log.warning("GOOGLE_PLACES_API_KEY is not set; trips won't show Google Maps places")
            return None
        if settings.google_maps_browser_key == key.get_secret_value():
            log.warning(
                "GOOGLE_MAPS_BROWSER_KEY is the same as GOOGLE_PLACES_API_KEY; the map is off. "
                "Make a separate key limited to the Maps JavaScript API and this site's address"
            )
        http = await stack.enter_async_context(timed_client())
        source = GooglePlaces(http, key.get_secret_value())
    return Places(source, clock=clock)


async def _routes(
    settings: Settings, overrides: Overrides, stack: AsyncExitStack, clock: Callable[[], datetime]
) -> Routes | None:
    """Travel times between a trip day's stops, with the same Google key as places (its
    Google Cloud project needs the Routes API turned on)."""
    source = overrides.routes
    if source is None:
        key = settings.google_places_api_key
        if key is None:
            return None
        http = await stack.enter_async_context(timed_client())
        source = GoogleRoutes(http, key.get_secret_value())
    return Routes(source, clock=clock)


def _statement_pages(
    settings: Settings, overrides: Overrides, models: ChatModels
) -> StatementPageReader | None:
    """Scanned statements are read by the photo model, without reasoning."""
    if overrides.statement_pages is not None:
        return overrides.statement_pages
    if models.vision is None:
        return None
    return LlmStatementReader(build_screenshot_reader(settings, models.vision))


async def _weather_source(overrides: Overrides, stack: AsyncExitStack) -> WeatherSource:
    """Trip weather from Open-Meteo (no key needed)."""
    if overrides.weather is not None:
        return overrides.weather
    http = await stack.enter_async_context(timed_client())
    return OpenMeteo(http)


async def _photos(
    settings: Settings, overrides: Overrides, stack: AsyncExitStack, models: ChatModels
) -> PhotoFinder:
    """Trip header photos from Wikipedia, with a model naming famous sights and the
    photo model choosing between a few (without it, the place's lead photo)."""
    if overrides.photos is not None:
        return overrides.photos
    http = await stack.enter_async_context(timed_client())
    chooser = (
        LlmChooser(build_screenshot_reader(settings, models.vision))
        if models.vision is not None
        else None
    )
    return PhotoFinder(
        WikipediaPhotos(http), LlmSpotter(build_memory_model(settings, models.primary)), chooser
    )


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
            http = await stack.enter_async_context(timed_client(timeout=30))
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
        build_screener(settings, models.primary), build_email_reader(settings, models.primary)
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
    places: Places | None = None,
    ideas: IdeaFinder | None = None,
    lookup: WebLookup | None = None,
    routes: Routes | None = None,
    zones: ZoneFinder | None = None,
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
            postgres_checkpointer(settings.database_url_str, app_role=settings.db_app_role)
        )
    agent_graph = AgentGraph(
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
            places=places,
            routes=routes,
            ideas=ideas,
            lookup=lookup,
            zones=zones,
        )
    )
    graph = agent_graph.compile(checkpointer)
    receipts: ReceiptReader | None = overrides.receipts
    if receipts is None and models.vision is not None:
        receipts = LlmReceiptReader(models.vision)
    holdings: HoldingsReader | None = overrides.holdings
    if holdings is None and models.vision is not None:
        holdings = LlmHoldingsReader(models.vision)
    trip_reader: TripReader | None = overrides.trip_reader
    if trip_reader is None and models.vision is not None:
        trip_reader = LlmTripReader(build_screenshot_reader(settings, models.vision))
    looker: ImageLooker | None = overrides.image_looker
    if looker is None and models.vision is not None:
        looker = LlmImageLooker(*build_image_look_models(settings, models.vision))
    client = overrides.telegram
    if client is None:
        token = settings.telegram_bot_token
        if token is None:  # pragma: no cover - guarded by telegram_enabled
            raise RuntimeError("Telegram is not configured")
        http = await stack.enter_async_context(timed_client())
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
            trips=trip_reader,
            looker=looker,
            primary_model=_model_id(models.primary),
            condense=agent_graph.condense,
        ),
        client=client,
    )


@dataclass(frozen=True, slots=True)
class Web:
    """Everything that asks the web, each within its product's share of the credits."""

    travel: WebSearch
    general: LiveSearch
    # Reads the articles behind an investment plan's headlines; None without Tavily.
    news: KeptReader | None


async def _web(
    settings: Settings, engine: AsyncEngine, stack: AsyncExitStack, clock: Callable[[], datetime]
) -> Web | None:
    """Web search: Tavily's pages with its key, falling back to OpenRouter's web search,
    kept a day. None without OpenRouter, which reads what's found."""
    key = settings.openrouter_api_key
    model = _travel_model(settings)
    if key is None or not model:
        return None
    http = await stack.enter_async_context(timed_client())
    routed = model == settings.openrouter_model
    fallback = OpenRouterWebSearch(
        http,
        key.get_secret_value(),
        model,
        routing=openrouter_routing(settings) if routed else None,
    )
    tavily = settings.tavily_api_key
    if tavily is None:
        log.warning("TAVILY_API_KEY is not set; research reads search answers, not pages")
    primary = TavilySearch(http, tavily.get_secret_value()) if tavily else None
    uow = lambda: SqlUnitOfWork(engine)  # noqa: E731
    monthly = settings.tavily_monthly_credits

    def search(product: Product) -> KeptSearch:
        return KeptSearch(
            uow, product, primary=primary, fallback=fallback, monthly_credits=monthly, clock=clock
        )

    news = (
        KeptReader(
            uow,
            Product.INVESTMENT,
            reader=TavilyReader(http, tavily.get_secret_value()),
            monthly_credits=monthly,
            clock=clock,
        )
        if tavily
        else None
    )
    return Web(search(Product.TRAVEL), search(Product.GENERAL), news)


def _travel_model(settings: Settings) -> str:
    return settings.travel_research_model or settings.openrouter_model or ""


async def _registry(
    settings: Settings,
    engine: AsyncEngine,
    models: ChatModels,
    rates: RateSource,
    stack: AsyncExitStack,
    web: Web | None = None,
    news: NewsSource | None = None,
    quotes: Quotes | None = None,
) -> Departments:
    """The departments, with the Investment research team and, with travel's web
    search, the Travel researcher (live flight and hotel prices too with a SerpApi
    key)."""
    uow = lambda: SqlUnitOfWork(engine)  # noqa: E731
    analyst, lead = build_research_models(settings, models.primary)
    reviewer = build_research_reviewer(settings)
    kinds = [plan_kind(uow, analyst, lead, reviewer, web.news if web else None, news, quotes)]
    if web is not None:
        http = await stack.enter_async_context(timed_client())
        prices = (
            SerpApiTravel(http, settings.serpapi_api_key.get_secret_value())
            if settings.serpapi_api_key is not None
            else None
        )
        if prices is None:
            log.warning("SERPAPI_API_KEY is not set; trip research uses web search for prices")
        sorter = build_travel_sorter(settings, _travel_model(settings))
        kinds.append(research_kind(uow, web.travel, sorter, rates, prices))
    else:
        log.warning("OpenRouter isn't set up; trip research is off")
    return default_registry(kinds)


async def _ideas(
    settings: Settings,
    overrides: Overrides,
    stack: AsyncExitStack,
    web: Web | None,
    places: Places | None,
    clock: Callable[[], datetime],
) -> IdeaFinder | None:
    """Quick ideas for a trip, from travel's web search and Wikivoyage, matched to
    Google Maps when that's set up. None without travel's web search."""
    if overrides.ideas is not None:
        return overrides.ideas
    if web is None:
        return None
    http = await stack.enter_async_context(timed_client())
    return IdeaFinder(
        web.travel,
        build_travel_sorter(settings, _travel_model(settings)),
        guides=Wikivoyage(http, clock=clock),
        places=places,
        clock=clock,
    )


def _lookup(settings: Settings, overrides: Overrides, web: Web | None) -> WebLookup | None:
    """Looking things up on the web from chat, within general's share of the credits.
    None without web search."""
    if overrides.lookup is not None:
        return overrides.lookup
    if web is None:
        return None
    return WebLookup(web.general, build_web_writer(settings, _travel_model(settings)))


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


def _model_id(model: BaseChatModel) -> str | None:
    found = getattr(model, "model_name", None) or getattr(model, "model", None)
    return str(found) if found else None


async def _ops_store(
    settings: Settings, engine: AsyncEngine, stack: AsyncExitStack
) -> OpsStore | None:
    """Ops events kept in the database, written every few seconds. On the real clock,
    like the events themselves, whatever clock the app runs on."""
    if not settings.ops_events:
        return None
    salt = settings.ops_salt or settings.telegram_webhook_secret or settings.token_encryption_key
    ops.set_salt(salt.get_secret_value() if salt else None)
    store = OpsStore(engine)
    ops.set_sink(store.add)
    stop = asyncio.Event()
    task = asyncio.create_task(store.run(stop))

    async def close() -> None:
        ops.set_sink(None)
        await _stop_worker(stop, task)

    stack.push_async_callback(close)
    return store


def create_app(settings: Settings | None = None, overrides: Overrides | None = None) -> FastAPI:
    configure_logging()
    resolved = settings or get_settings()
    extra = overrides or Overrides()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(resolved.database_url_str, app_role=resolved.db_app_role)
        async with AsyncExitStack() as stack:
            stack.push_async_callback(engine.dispose)
            await assert_schema_at_head(engine)
            app.state.engine = engine
            app.state.ops = await _ops_store(resolved, engine, stack)
            if resolved.telegram_enabled:
                rates = extra.rates
                if rates is None:
                    http = await stack.enter_async_context(timed_client())
                    rates = StoredRates(FrankfurterRates(http), lambda: SqlUnitOfWork(engine))
                prices = await _prices(resolved, extra, stack)
                news = await _news(resolved, extra, stack)
                quotes = await _quotes(resolved, extra, stack)
                archive = _receipt_store(resolved, extra)
                if archive is None:
                    log.warning("receipt storage is not configured; receipt photos won't be kept")
                models = extra.models or build_chat_models(resolved)
                email = await _email_runtime(resolved, extra, stack, models, resolved.public_origin)
                web = await _web(resolved, engine, stack, extra.clock or utcnow)
                departments = extra.departments or await _registry(
                    resolved, engine, models, rates, stack, web, news, quotes
                )
                weather = Weather(await _weather_source(extra, stack), clock=extra.clock or utcnow)
                places = await _places(resolved, extra, stack, extra.clock or utcnow)
                ideas = await _ideas(resolved, extra, stack, web, places, extra.clock or utcnow)
                routes = await _routes(resolved, extra, stack, extra.clock or utcnow)
                telegram = await _telegram_runtime(
                    resolved, engine, extra, stack, rates, archive, models, email, departments,
                    places, ideas, _lookup(resolved, extra, web), routes, weather,
                )  # fmt: skip
                app.state.telegram = telegram
                origin = resolved.public_origin
                clock = extra.clock or utcnow
                if resolved.run_jobs:
                    handlers = build_handlers(
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
                        await _photos(resolved, extra, stack, models),
                        origin,
                        quotes,
                        weather,
                    )
                    schedules = list(SCHEDULES)
                    if resolved.ops_tickets_enabled:
                        handlers[ops_ticket_job.OPS_TICKETS] = ops_ticket_job.handler(
                            engine, resolved, ops_api.webhook_info(app)
                        )
                        schedules.append(ops_ticket_job.SCHEDULE)
                    runner = JobRunner(
                        engine,
                        handlers,
                        schedules=schedules,
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
                        quotes=quotes,
                        explainer=Explainer(
                            build_memory_model(resolved, models.primary), clock=clock
                        ),
                        places=places,
                        routes=routes,
                        ideas=ideas,
                        weather=weather,
                        scans=_statement_pages(resolved, extra, models),
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
    app.include_router(data_api.router)
    app.include_router(email_api.router)
    app.include_router(investments_api.router)
    app.include_router(travel_api.router)
    app.include_router(travel_api.shared_router)
    app.include_router(ops_api.router)
    install_error_handlers(app)
    origin = resolved.public_origin
    install_hardening(app, https=bool(origin and origin.startswith("https://")))
    app.add_middleware(Tracing)
    mount_frontend(app)
    return app


__all__ = ["BaseChatModel", "Overrides", "create_app"]
