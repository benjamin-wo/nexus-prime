"""The ops ticket job: every few hours, the ops report's problems are synced to
GitHub issues (see application/ops_tickets.py)."""

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import ops_tickets
from nexus.infra.github_issues import GitHubIssues
from nexus.infra.http import timed_client
from nexus.infra.ops_gather import WebhookInfo, build_report
from nexus.jobs.runner import Schedule
from nexus.settings import Settings

log = logging.getLogger(__name__)

OPS_TICKETS = "ops.tickets"
EVERY = timedelta(hours=6)
SCHEDULE = Schedule(OPS_TICKETS, EVERY)


async def sync_tickets(
    engine: AsyncEngine, settings: Settings, webhook_info: WebhookInfo | None
) -> ops_tickets.Synced:
    token, repo = settings.ops_github_token, settings.ops_github_repo
    if token is None or not repo:
        raise RuntimeError("ops tickets need OPS_GITHUB_TOKEN and OPS_GITHUB_REPO")
    report = await build_report(engine, settings, webhook_info, settings.ops_ticket_hours)
    async with timed_client(timeout=20) as http:
        synced = await ops_tickets.sync(
            GitHubIssues(http, repo, token.get_secret_value()),
            report,
            repo,
            at_least=settings.ops_ticket_severity,
        )
    log.info(
        "ops tickets: %d opened, %d updated, %d reopened, %d closed",
        len(synced.opened),
        len(synced.updated),
        len(synced.reopened),
        len(synced.closed),
    )
    return synced


def handler(engine: AsyncEngine, settings: Settings, webhook_info: WebhookInfo | None) -> Any:
    async def run(payload: dict[str, Any]) -> None:
        await sync_tickets(engine, settings, webhook_info)

    return run
