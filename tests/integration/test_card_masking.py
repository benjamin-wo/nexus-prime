"""A card number in what a user says never reaches a model or the stored chat: only its
last four digits do, whether it was typed, spoken, or in a photo's or PDF's caption or
text, and the reply says so once. Every number is built when the test runs."""

import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import HISTORY_LIMIT
from nexus.agent.image_look import ImageKind, ImageLook
from nexus.agent.memory_writer import MemoryWriter
from nexus.agent.service import CARD_NOTE, AgentService
from nexus.application.users import get_user
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import chat_log
from nexus.main import Overrides, create_app
from tests.cards import card_number, last4, spaced
from tests.fakes import (
    NOW,
    FakeImageLooker,
    FakeSpeech,
    FakeTelegram,
    ScriptedModel,
    models,
    say,
    scripted,
)
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_agent_context import _config, _messages
from tests.integration.test_memory import FakeWriterModel
from tests.integration.test_telegram_webhook import OWNER, Bot, settings
from tests.integration.test_voice_notes import AUDIO, chat_lines
from tests.integration.test_web_api import World, world  # noqa: F401
from tests.pdfs import make_pdf

pytestmark = pytest.mark.integration

CARD = card_number()
TYPED = spaced(CARD)
MASKED = f"•••• {last4(CARD)}"
MENU = ImageLook(ImageKind.OTHER, "SGD", "A noodle menu.", "Wonton Mee 8.50 / Lemon Tea 3.20")


def leaks(*texts: object) -> bool:
    """Whether the full number is in any of ``texts``, however it is spaced."""
    return any(CARD in re.sub(r"\D", "", str(t)) for t in texts)


def seen_by(model: ScriptedModel) -> str:
    """Everything every model call was shown."""
    return "\n".join(str(m.content) for call in model.seen for m in call)


async def kept_lines(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = (await conn.execute(select(chat_log.c.text).order_by(chat_log.c.id))).all()
    return [r.text for r in rows]


# --- typed text ------------------------------------------------------------------------


async def test_a_typed_card_number_is_kept_to_its_last_four_everywhere(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("Noted."))
    agent = build(uow, model)
    handed: list[list[str]] = []

    async def after_turn(actor: UserId, messages: list[str], ref: str) -> None:
        handed.append(messages)

    agent._after_turn = after_turn
    reply = only(await agent.handle_text(alice, f"my card is {TYPED}, remember it", "web:t:1"))

    assert reply.text == f"Noted.\n\n{CARD_NOTE}"
    # The model saw the last four only.
    assert f"my card is {MASKED}, remember it" in seen_by(model)
    assert not leaks(seen_by(model))
    # The conversation as stored (the graph's checkpoint) and as shown again (the chat log).
    assert not leaks(*(await _messages(agent, alice)))
    assert await chat_lines(uow, alice) == [
        ("user", f"my card is {MASKED}, remember it", "web"),
        ("nexus", f"Noted.\n\n{CARD_NOTE}", "web"),
    ]
    # And what the memory writer is handed.
    assert handed == [[f"my card is {MASKED}, remember it"]]


async def test_the_note_comes_once_per_message_and_only_when_something_was_hidden(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("Noted."), say("Logged."), say("Fine."))
    agent = build(uow, model)
    first = only(await agent.handle_text(alice, f"card {TYPED} and again {CARD}", "web:t:1"))
    assert first.text.count(CARD_NOTE) == 1
    second = only(await agent.handle_text(alice, "coffee 4.50", "web:t:2"))
    assert second.text == "Logged."
    third = only(await agent.handle_text(alice, f"it was {TYPED}", "web:t:3"))
    assert third.text == f"Fine.\n\n{CARD_NOTE}"


async def test_numbers_that_are_not_cards_reach_the_model_untouched(
    uow: UowFactory, alice: UserId
) -> None:
    said = (
        "call +65 9123 4567, paid SGD 1,234,567.89 on 2026-11-03 10:15:30, "
        "booking XK7Q9P, order 1234567890123, IBAN GB00 TEST 1234 5612 3456 78"
    )
    model = scripted(say("Ok."))
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, said, "web:t:1"))
    assert reply.text == "Ok."  # no note
    assert said in seen_by(model)
    assert (await chat_lines(uow, alice))[0] == ("user", said, "web")


async def test_the_memory_writer_is_only_given_the_last_four(
    uow: UowFactory, alice: UserId
) -> None:
    user = await get_user(uow(), alice)
    writer_model = FakeWriterModel({}, {})
    writer = MemoryWriter(writer_model)  # type: ignore[arg-type]
    agent = build(uow, scripted(say("Noted."), say("Ok.")))

    async def after_turn(actor: UserId, messages: list[str], ref: str) -> None:
        await writer.remember(uow, user, messages, NOW)

    agent._after_turn = after_turn
    await agent.handle_text(alice, f"my card is {TYPED}", "web:t:1")
    await agent.handle_text(alice, "what was that for?", "web:t:2")  # sees the earlier one too
    assert len(writer_model.seen) == 2
    prompts = [str(m.content) for call in writer_model.seen for m in call]
    assert not leaks(*prompts)
    assert all(MASKED in str(call[1].content) for call in writer_model.seen)


async def test_the_rolling_summary_is_only_given_the_last_four(
    uow: UowFactory, alice: UserId
) -> None:
    turns = HISTORY_LIMIT // 2
    model = scripted(*[say("ok") for _ in range(turns + 1)], say("A summary."), say("ok"))
    agent = build(uow, model)
    await agent.handle_text(alice, f"my card is {TYPED}", "tg:1:0")
    for n in range(1, turns):
        await agent.handle_text(alice, f"note {n}", f"tg:1:{n}")
    await agent.handle_text(alice, "one more", "tg:1:x")
    await agent.drain()

    summariser = model.seen[turns + 1]  # the call after the turns: the summary request
    assert len(summariser) == 1 and MASKED in str(summariser[0].content)
    assert not leaks(seen_by(model))
    state = await agent._graph.aget_state(_config(alice))
    assert "A summary." in state.values["summary"]


# --- voice -----------------------------------------------------------------------------


async def test_a_spoken_card_number_is_kept_to_its_last_four(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("Noted."))
    speech = FakeSpeech([f"Paid for lunch with my card {TYPED}."])
    agent = build(uow, model, speech=speech)
    reply = only(await agent.handle_voice(alice, AUDIO, "audio/ogg", "telegram:1:1"))

    assert reply.text == f"Noted.\n\n{CARD_NOTE}"
    assert f"Paid for lunch with my card {MASKED}." in seen_by(model)
    assert not leaks(seen_by(model), *(await _messages(agent, alice)))
    [(_, spoken, _), (_, answer, _)] = await chat_lines(uow, alice)
    assert spoken == f"🎙 Paid for lunch with my card {MASKED}."
    assert answer == reply.text


async def test_a_spoken_card_number_is_hidden_after_the_transcript_is_tidied(
    uow: UowFactory, alice: UserId
) -> None:
    # A lone "1111" in a spending sentence would be tidied into 11.11 if hiding came first.
    model = scripted(say("Noted."))
    agent = build(uow, model, speech=FakeSpeech([f"I paid with card {MASKED} today"]))
    await agent.handle_voice(alice, AUDIO, "audio/ogg", "telegram:1:1")
    assert f"I paid with card {MASKED} today" not in seen_by(model)  # the tidy-up did read it
    model = scripted(say("Noted."))
    agent = build(uow, model, speech=FakeSpeech([f"I paid with card {CARD} today"]))
    await agent.handle_voice(alice, AUDIO, "audio/ogg", "telegram:1:2")
    assert f"I paid with card {MASKED} today" in seen_by(model)


async def test_a_forwarded_voice_note_is_hidden_too(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("It says to use the card."))
    agent = build(uow, model, speech=FakeSpeech([f"Use my card {TYPED} for the deposit."]))
    reply = only(
        await agent.handle_voice(alice, AUDIO, "audio/ogg", "telegram:1:1", forwarded=True)
    )
    assert reply.text.endswith(CARD_NOTE) and reply.text.count(CARD_NOTE) == 1
    assert MASKED in seen_by(model) and not leaks(seen_by(model))
    assert not leaks(*(await chat_lines(uow, alice)))


# --- photos and PDFs -------------------------------------------------------------------


async def test_a_photo_caption_is_kept_to_its_last_four(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("A noodle menu."))
    looker = FakeImageLooker([MENU])
    agent = build(uow, model, looker=looker)
    reply = only(
        await agent.handle_photo(
            alice, b"png", "image/png", f"is this ok for {TYPED}?", "telegram:1:1"
        )
    )
    assert reply.text == f"A noodle menu.\n\n{CARD_NOTE}"
    assert looker.seen == [f"is this ok for {MASKED}?"]  # even the image model gets the safe one
    assert f"is this ok for {MASKED}?" in seen_by(model) and not leaks(seen_by(model))
    assert not leaks(*(await _messages(agent, alice)), *(await chat_lines(uow, alice)))
    assert (await chat_lines(uow, alice))[0][1] == f"[Sent a photo] is this ok for {MASKED}?"


async def test_a_card_read_off_a_photo_is_kept_to_its_last_four(
    uow: UowFactory, alice: UserId
) -> None:
    look = ImageLook(ImageKind.OTHER, None, f"A card, {TYPED}.", f"VISA / {TYPED} / 12/28")
    model = scripted(say("It's a card."))
    agent = build(uow, model, looker=FakeImageLooker([look]))
    reply = only(await agent.handle_photo(alice, b"png", "image/png", "what is this?", "web:t:1"))
    assert reply.text == f"It's a card.\n\n{CARD_NOTE}"
    assert f"VISA / {MASKED} / 12/28" in seen_by(model) and not leaks(seen_by(model))
    assert not leaks(*(await _messages(agent, alice)))


async def test_a_pdf_caption_and_text_are_kept_to_their_last_four(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("It's an invoice."))
    agent = build(uow, model)
    pdf = make_pdf([f"Invoice 88.00 paid by card {TYPED}"])
    reply = only(
        await agent.handle_pdf(alice, pdf, "invoice.pdf", f"mine: {TYPED}", "telegram:1:1")
    )
    assert reply.text == f"It's an invoice.\n\n{CARD_NOTE}"
    assert f"paid by card {MASKED}" in seen_by(model) and f"mine: {MASKED}" in seen_by(model)
    assert not leaks(seen_by(model), *(await _messages(agent, alice)))
    assert not leaks(*(await chat_lines(uow, alice)))


async def test_a_photo_without_a_card_has_no_note(uow: UowFactory, alice: UserId) -> None:
    agent = build(uow, scripted(say("A noodle menu.")), looker=FakeImageLooker([MENU]))
    reply = only(await agent.handle_photo(alice, b"png", "image/png", "lunch 8.50", "web:t:1"))
    assert reply.text == "A noodle menu."


# --- the web chat and Telegram ---------------------------------------------------------


async def test_a_web_chat_message_with_a_card_number(world: World) -> None:  # noqa: F811
    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    service: AgentService = world.app.state.web.service
    handed: list[list[str]] = []

    async def after_turn(actor: UserId, messages: list[str], ref: str) -> None:
        handed.append(messages)

    service._after_turn = after_turn
    world.model.script += [say("Noted.")]
    sent = await owner.send("POST", "/api/chat", {"message": f"my card is {TYPED}"})
    [reply] = sent.json()

    assert reply["text"] == f"Noted.\n\n{CARD_NOTE}"
    assert f"my card is {MASKED}" in seen_by(world.model) and not leaks(seen_by(world.model))
    assert handed == [[f"my card is {MASKED}"]]
    history = (await owner.get("/api/chat/history")).json()
    assert [x["text"] for x in history["lines"]] == [f"my card is {MASKED}", reply["text"]]
    assert not leaks(*(await kept_lines(world.engine)))


@pytest.fixture
def model() -> ScriptedModel:
    return scripted()


@pytest.fixture
async def bot(
    engine: AsyncEngine, empty_database_url: str, model: ScriptedModel
) -> AsyncIterator[Bot]:
    telegram = FakeTelegram()
    app = create_app(
        settings(empty_database_url),
        Overrides(
            models=models(model),
            telegram=telegram,
            image_looker=FakeImageLooker([MENU]),
            checkpointer=InMemorySaver(),
            clock=lambda: NOW,
        ),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield Bot(client, telegram, model, app.state.telegram)


async def test_a_telegram_message_with_a_card_number(
    bot: Bot, model: ScriptedModel, engine: AsyncEngine
) -> None:
    handed: list[list[str]] = []

    async def after_turn(actor: UserId, messages: list[str], ref: str) -> None:
        handed.append(messages)

    service: AgentService = bot.runtime.service
    service._after_turn = after_turn
    model.script += [say("Noted.")]
    assert await bot.post(bot.text(f"my card is {TYPED}")) == 200

    assert bot.telegram.sent[-1].text.count(CARD_NOTE) == 1
    assert bot.telegram.sent[-1].text.startswith("Noted.")
    assert f"my card is {MASKED}" in seen_by(model) and not leaks(seen_by(model))
    assert handed == [[f"my card is {MASKED}"]]
    kept = await kept_lines(engine)
    assert kept[0] == f"my card is {MASKED}" and not leaks(*kept)


async def test_a_telegram_photo_caption_with_a_card_number(
    bot: Bot, model: ScriptedModel, engine: AsyncEngine
) -> None:
    bot.telegram.files["p1"] = b"png"
    model.script += [say("A noodle menu.")]
    update: dict[str, Any] = bot.update(
        message={
            "message_id": 9,
            "from": {"id": OWNER},
            "chat": {"id": OWNER, "type": "private"},
            "caption": f"is {TYPED} ok?",
            "photo": [{"file_id": "p1", "file_unique_id": "u-p1", "width": 8, "height": 6}],
        }
    )
    assert await bot.post(update) == 200
    assert bot.telegram.sent[-1].text.count(CARD_NOTE) == 1
    assert f"is {MASKED} ok?" in seen_by(model) and not leaks(seen_by(model))
    assert not leaks(*(await kept_lines(engine)))
