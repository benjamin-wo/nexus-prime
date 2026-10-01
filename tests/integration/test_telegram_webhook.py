"""The Telegram webhook through the real app, with a fake Bot API and model."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.receipts import ReceiptDraft
from nexus.agent.service import UNDO, Button, Reply
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import list_ledger
from nexus.application.users import find_telegram_user
from nexus.channels.telegram import webhook
from nexus.infra.db.tables import jobs
from nexus.jobs.handlers import build_handlers
from nexus.main import Overrides, create_app
from nexus.settings import Settings
from tests.fakes import (
    NOW,
    FakeRates,
    FakeReceipts,
    FakeTelegram,
    ScriptedModel,
    call,
    models,
    say,
    scripted,
)
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

OWNER = 555
SECRET = "hook-secret"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


class Bot:
    def __init__(
        self,
        client: AsyncClient,
        telegram: FakeTelegram,
        model: ScriptedModel,
        runtime: webhook.TelegramRuntime,
    ) -> None:
        self.client = client
        self.runtime = runtime
        self.telegram = telegram
        self.model = model
        self._next = 1

    async def post(self, update: dict[str, Any], headers: dict[str, str] = HEADERS) -> int:
        response = await self.client.post("/telegram/webhook", json=update, headers=headers)
        return response.status_code

    def update(self, **body: Any) -> dict[str, Any]:
        self._next += 1
        return {"update_id": self._next, **body}

    def text(self, text: str, sender: int = OWNER, chat_type: str = "private") -> dict[str, Any]:
        return self.update(
            message={
                "message_id": self._next,
                "from": {"id": sender},
                "chat": {"id": sender, "type": chat_type},
                "text": text,
            }
        )

    def press(self, data: str, sender: int = OWNER, message_id: int = 77) -> dict[str, Any]:
        return self.update(
            callback_query={
                "id": f"cb{self._next}",
                "from": {"id": sender},
                "data": data,
                "message": {"message_id": message_id, "chat": {"id": sender, "type": "private"}},
            }
        )


def settings(url: str, **extra: Any) -> Settings:
    return Settings(
        _env_file=None,
        database_url=url,
        telegram_bot_token="123:fake",
        telegram_webhook_secret=SECRET,
        admin_telegram_chat_id=OWNER,
        default_timezone="UTC",
        **extra,
    )


@pytest.fixture
def model() -> ScriptedModel:
    return scripted()


@pytest.fixture
async def bot(
    engine: AsyncEngine, empty_database_url: str, model: ScriptedModel
) -> AsyncIterator[Bot]:
    telegram = FakeTelegram(files={"big": b"jpeg-bytes"})
    receipts = FakeReceipts(ReceiptDraft(is_receipt=True, amount="9.90", merchant="Cheers"))
    app = create_app(
        settings(empty_database_url),
        Overrides(
            models=models(model),
            receipts=receipts,
            telegram=telegram,
            checkpointer=InMemorySaver(),
            clock=lambda: NOW,
        ),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield Bot(client, telegram, model, app.state.telegram)


async def test_rejects_requests_without_the_secret(bot: Bot) -> None:
    assert await bot.post(bot.text("hi"), headers={}) == 401
    assert await bot.post(bot.text("hi"), headers={"X-Telegram-Bot-Api-Secret-Token": "no"}) == 401
    assert bot.telegram.sent == []
    bad = await bot.client.post("/telegram/webhook", content=b"{nope", headers=HEADERS)
    assert bad.status_code == 400


async def test_disabled_without_a_token(engine: AsyncEngine, empty_database_url: str) -> None:
    app = create_app(Settings(_env_file=None, database_url=empty_database_url))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            response = await client.post(
                "/telegram/webhook", json={"update_id": 1}, headers=HEADERS
            )
    assert response.status_code == 404


async def test_strangers_and_groups_are_not_served(bot: Bot, uow: UowFactory) -> None:
    assert await bot.post(bot.text("coffee 5", sender=999)) == 200
    assert [s.text for s in bot.telegram.sent] == ["This is a private assistant."]
    assert await find_telegram_user(uow(), 999) is None
    assert await bot.post(bot.text("coffee 5", chat_type="group")) == 200
    assert len(bot.telegram.sent) == 1


async def test_text_round_trip_and_replayed_update(
    bot: Bot, model: ScriptedModel, uow: UowFactory
) -> None:
    model.script += [call("log_expense", amount="4.20", merchant="Kopi"), say("Logged 4.20.")]
    update = bot.text("kopi 4.20")
    assert await bot.post(update) == 200
    assert await bot.post(update) == 200  # Telegram redelivers; handled once
    assert [(s.chat_id, s.text) for s in bot.telegram.sent] == [(OWNER, "Logged 4.20.")]
    owner = await find_telegram_user(uow(), OWNER)
    assert owner is not None and owner.role.value == "owner"
    assert (await list_ledger(uow(), owner.id, LedgerQuery())).total == 1


async def test_confirmation_buttons(bot: Bot, model: ScriptedModel, uow: UowFactory) -> None:
    model.script += [call("log_expense", amount="30", merchant="Taxi"), say("Logged.")]
    await bot.post(bot.text("taxi 30"))
    owner = await find_telegram_user(uow(), OWNER)
    assert owner is not None
    tx = (await list_ledger(uow(), owner.id, LedgerQuery())).items[0]

    model.script += [call("delete_transaction", transaction_id=str(tx.id)), say("Deleted.")]
    await bot.post(bot.text("delete the taxi"))
    prompt = bot.telegram.sent[-1]
    assert prompt.text.startswith("Delete ")
    assert prompt.buttons is not None
    confirm = prompt.buttons[0][0].data
    assert all(len(b.data.encode()) <= 64 for row in prompt.buttons for b in row)

    await bot.post(bot.press(confirm))
    assert bot.telegram.sent[-1].text == "Deleted."
    assert bot.telegram.cleared == [(OWNER, 77)]
    assert bot.telegram.answered
    assert (await list_ledger(uow(), owner.id, LedgerQuery())).total == 0


async def test_menu_and_quick_actions(bot: Bot) -> None:
    await bot.post(bot.text("/start"))
    menu = bot.telegram.sent[-1]
    assert menu.buttons is not None
    assert {b.data for row in menu.buttons for b in row} >= {"qa:summary", "act:undo"}
    await bot.post(bot.press("qa:help"))
    assert bot.telegram.sent[-1].text.startswith("Just tell me")


async def test_receipt_photo(bot: Bot, uow: UowFactory) -> None:
    photo = bot.update(
        message={
            "message_id": 5,
            "from": {"id": OWNER},
            "chat": {"id": OWNER, "type": "private"},
            "photo": [
                {"file_id": "small", "file_unique_id": "u", "width": 90, "height": 90},
                {"file_id": "big", "file_unique_id": "u", "width": 1200, "height": 1600},
            ],
        }
    )
    await bot.post(photo)
    prompt = bot.telegram.sent[-1]
    assert prompt.text == "Log 9.90 SGD at Cheers on 2026-09-28 from this receipt?"
    assert prompt.buttons is not None
    await bot.post(bot.press(prompt.buttons[0][0].data))
    assert bot.telegram.sent[-1].text.startswith("Logged from receipt")


async def test_failures_are_reported_not_swallowed(bot: Bot, model: ScriptedModel) -> None:
    model.script += [ValueError("boom")]
    await bot.post(bot.text("coffee 3"))
    assert bot.telegram.sent[-1].text.startswith("Sorry, I can't reach the AI model")


async def undo_jobs(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as db:
        query = select(jobs.c.dedupe_key, jobs.c.payload, jobs.c.run_at).where(
            jobs.c.kind == webhook.UNDO_EXPIRE
        )
        return list(await db.execute(query))


async def test_the_undo_button_comes_off_after_a_few_minutes(
    bot: Bot, model: ScriptedModel, engine: AsyncEngine, uow: UowFactory
) -> None:
    model.script += [call("log_expense", amount="4.20", merchant="Kopi"), say("Logged 4.20.")]
    await bot.post(bot.text("kopi 4.20"))
    reply = bot.telegram.sent[-1]
    assert reply.buttons == [[UNDO]]
    [job] = await undo_jobs(engine)
    message_id = 1000 + len(bot.telegram.sent)
    assert job.dedupe_key == f"undo-expire:{OWNER}:{message_id}"
    assert job.run_at == NOW + timedelta(minutes=5)

    await build_handlers(uow, bot.telegram, FakeRates(), lambda: NOW)[webhook.UNDO_EXPIRE](
        job.payload
    )
    assert bot.telegram.edited == [(OWNER, message_id, [])]


async def test_other_buttons_stay_and_a_pressed_one_cancels_the_expiry(
    bot: Bot, engine: AsyncEngine, uow: UowFactory
) -> None:
    offer = Button("Yes, always", "rule:abc:y")
    await webhook._send(bot.runtime, OWNER, [Reply("Moved.", [[offer], [UNDO]])])
    [job] = await undo_jobs(engine)
    handlers = build_handlers(uow, bot.telegram, FakeRates(), lambda: NOW)
    await handlers[webhook.UNDO_EXPIRE](job.payload)
    assert bot.telegram.edited[-1][2] == [[offer]]  # only Undo is taken off

    await webhook._send(bot.runtime, OWNER, [Reply("Moved.", [[offer], [UNDO]])])
    message_id = 1000 + len(bot.telegram.sent)
    assert len(await undo_jobs(engine)) == 2
    await bot.post(bot.press("rule:abc:n", message_id=message_id))
    assert (OWNER, message_id) in bot.telegram.cleared
    # The one still queued is the first message's; the pressed message's is gone.
    assert [j.dedupe_key for j in await undo_jobs(engine)] == [job.dedupe_key]
