"""The Turn on Health button in chat: one press sets the master consent and ai_processing."""

import pytest

from nexus.application import health_consent as consent_cases
from nexus.application.health_menu import health_on_button
from nexus.domain.health import ConsentScope
from nexus.domain.ledger import UserId
from tests.fakes import scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only

pytestmark = pytest.mark.integration


def test_the_button_presses_health_on() -> None:
    button = health_on_button()
    assert (button.label, button.data) == ("Turn on Health", "health:on")


async def test_pressing_it_turns_health_on(uow: UowFactory, alice: UserId) -> None:
    agent = build(uow, scripted())
    assert not await consent_cases.may_send_to_ai(uow(), alice)
    reply = only(await agent.press(alice, "health:on"))
    assert reply.text == "Health is on. Send me a food photo or ask for a workout."
    state = await consent_cases.overview(uow(), alice)
    assert state.health_at is not None
    assert {s.scope for s in state.scopes if s.active} == {ConsentScope.AI_PROCESSING}
    again = only(await agent.press(alice, "health:on"))
    assert again.text == reply.text
    assert (await consent_cases.overview(uow(), alice)).health_at == state.health_at
