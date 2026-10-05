"""Images on Telegram: photos and image files, PDFs, photos sent together, and a
question replying to an earlier photo. Every shop, name and figure is made up."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.image_look import ImageKind, ImageLook
from nexus.agent.receipts import ReceiptDraft
from nexus.channels.telegram import webhook
from nexus.main import Overrides, create_app
from tests.fakes import (
    NOW,
    FakeImageLooker,
    FakeReceipts,
    FakeTelegram,
    ScriptedModel,
    models,
    say,
    scripted,
)
from tests.integration.test_image_routing import MENU, TRANSFER, told
from tests.integration.test_telegram_webhook import OWNER, Bot, settings
from tests.pdfs import make_pdf

pytestmark = pytest.mark.integration


@pytest.fixture
def looker() -> FakeImageLooker:
    return FakeImageLooker([TRANSFER])


@pytest.fixture
def model() -> ScriptedModel:
    return scripted()


@pytest.fixture
async def bot(
    engine: AsyncEngine, empty_database_url: str, model: ScriptedModel, looker: FakeImageLooker
) -> AsyncIterator[Bot]:
    telegram = FakeTelegram(
        files={"img1": b"png-1", "img2": b"jpeg-2", "pdf1": make_pdf(["Amount due: 88.00"])}
    )
    app = create_app(
        settings(empty_database_url),
        Overrides(
            models=models(model),
            receipts=FakeReceipts(ReceiptDraft(is_receipt=False)),
            image_looker=looker,
            telegram=telegram,
            checkpointer=InMemorySaver(),
            clock=lambda: NOW,
        ),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield Bot(client, telegram, model, app.state.telegram)


def message(bot: Bot, **body: Any) -> dict[str, Any]:
    return bot.update(
        message={"message_id": 9, "from": {"id": OWNER},
                 "chat": {"id": OWNER, "type": "private"}, **body}
    )  # fmt: skip


def photo(file_id: str) -> list[dict[str, Any]]:
    return [{"file_id": file_id, "file_unique_id": f"u-{file_id}", "width": 800, "height": 600}]


async def test_an_image_sent_as_a_file_is_read(bot: Bot, model: ScriptedModel) -> None:
    model.script += [say("It's your rent transfer to Jamie.")]
    doc = {"file_id": "img1", "file_unique_id": "d1", "mime_type": "image/png"}
    await bot.post(message(bot, document=doc, caption="what's this for?"))
    assert bot.telegram.sent[-1].text == "It's your rent transfer to Jamie."
    assert told(model).startswith("[photo] what's this for?\n<image>\nkind: transfer")


async def test_files_it_cant_read(bot: Bot) -> None:
    heic = {"file_id": "x", "file_unique_id": "h", "mime_type": "image/heic"}
    await bot.post(message(bot, document=heic))
    assert bot.telegram.sent[-1].text == webhook.UNREADABLE_FILE
    big = {"file_id": "x", "file_unique_id": "b", "mime_type": "image/png", "file_size": 11e6}
    await bot.post(message(bot, document=big))
    assert bot.telegram.sent[-1].text == "That file is too large."


async def test_a_pdf_is_read_for_its_text(bot: Bot, model: ScriptedModel) -> None:
    model.script += [say("A bill for 88.00.")]
    pdf = {"file_id": "pdf1", "file_unique_id": "p1", "mime_type": "application/pdf",
           "file_name": "bill.pdf"}  # fmt: skip
    await bot.post(message(bot, document=pdf))
    assert bot.telegram.sent[-1].text == "A bill for 88.00."
    assert "Amount due: 88.00" in told(model)


@pytest.mark.parametrize("looker", [FakeImageLooker([TRANSFER, MENU])])
async def test_an_album_is_answered_once_with_its_caption(
    bot: Bot, model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webhook, "ALBUM_WAIT", 0.3)
    model.script += [say("The transfer and the menu, compared.")]
    first = message(bot, photo=photo("img1"), media_group_id="g1")
    second = message(bot, photo=photo("img2"), media_group_id="g1", caption="compare these")
    await asyncio.gather(bot.post(first), bot.post(second))
    assert [s.text for s in bot.telegram.sent] == ["The transfer and the menu, compared."]
    given = told(model)
    assert given.startswith("[2 photos] compare these\n<image 1>")
    assert "<image 2>" in given


@pytest.mark.parametrize(
    "looker",
    [FakeImageLooker([ImageLook(ImageKind.OTHER, None, "A menu.", "Lemon Tea 3.20")])],
)
async def test_a_question_replying_to_a_photo_looks_at_it_again(
    bot: Bot, model: ScriptedModel, looker: FakeImageLooker
) -> None:
    model.script += [say("Lemon tea is 3.20.")]
    earlier = {"message_id": 3, "chat": {"id": OWNER, "type": "private"}, "photo": photo("img2")}
    await bot.post(message(bot, text="how much is the lemon tea?", reply_to_message=earlier))
    assert bot.telegram.sent[-1].text == "Lemon tea is 3.20."
    assert looker.seen == ["how much is the lemon tea?"]
    assert told(model).startswith("[photo] how much is the lemon tea?\n<image>")
