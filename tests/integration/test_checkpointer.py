"""A waiting confirmation survives a restart: the Postgres checkpointer holds it."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import AgentDeps, AgentGraph
from nexus.agent.service import AgentService
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import NewTransaction, list_ledger, log_transaction
from nexus.domain.ledger import Direction, UserId
from nexus.domain.money import Money
from nexus.infra.db.checkpointer import postgres_checkpointer
from tests.fakes import NOW, ScriptedModel, call, say, scripted
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration


def service(uow: UowFactory, model: ScriptedModel, checkpointer: object) -> AgentService:
    skills = SkillLibrary.load()

    async def health() -> str:
        return "ok"

    graph = AgentGraph(
        AgentDeps(uow, build_tools(skills.body), model, (), skills.index(), health, lambda: NOW)
    ).compile(checkpointer)  # type: ignore[arg-type]
    return AgentService(graph, uow, None, lambda: NOW)


async def test_confirmation_survives_restart(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory, alice: UserId
) -> None:
    tx = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("7", "SGD"), NOW)
    )
    async with postgres_checkpointer(empty_database_url) as saver:
        first = service(uow, scripted(call("delete_transaction", transaction_id=str(tx.id))), saver)
        reply = (await first.handle_text(alice, "delete it", "tg:1:1"))[0]
    confirmation = reply.buttons[0][0].data.split(":")[1]

    async with postgres_checkpointer(empty_database_url) as saver:
        restarted = service(uow, scripted(say("Deleted.")), saver)
        done = await restarted.resolve(alice, confirmation, True)
    assert done[0].text == "Deleted."
    assert (await list_ledger(uow(), alice, LedgerQuery())).total == 0
