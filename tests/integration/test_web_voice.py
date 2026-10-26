"""POST /api/chat/voice through the real app: auth, CSRF, size and type limits, the rate
limit, and a voice note answered like a typed message."""

from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.limits import RateLimiter
from nexus.application.users import find_telegram_user
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.main import Overrides, create_app
from nexus.settings import Settings
from tests.fakes import NOW, FakeSpeech, FakeTelegram, ScriptedModel, call, models, say, scripted
from tests.integration.test_agent import ledger
from tests.integration.test_voice_notes import AUDIO, HEARD, LOG_LUNCH
from tests.integration.test_web_api import ORIGIN, OWNER, TOKEN, Browser, Clock

pytestmark = pytest.mark.integration

TOO_LONG = "That's too long — keep voice notes under 2 minutes."


class Voice:
    def __init__(self, app: Any, browser: Browser, model: ScriptedModel, speech: FakeSpeech):
        self.app = app
        self.owner = browser
        self.model = model
        self.speech = speech

    async def post(
        self,
        audio: bytes = AUDIO,
        content_type: str = "audio/webm",
        *,
        field: str = "audio",
        csrf: str | None = None,
        origin: str = ORIGIN,
    ) -> Response:
        return await self.owner.client.post(
            "/api/chat/voice",
            files={field: ("note", audio, content_type)},
            headers={"Origin": origin, "X-CSRF-Token": self.owner.csrf if csrf is None else csrf},
        )


def make_app(url: str, model: ScriptedModel, speech: FakeSpeech | None) -> Any:
    return create_app(
        Settings(
            _env_file=None,
            database_url=url,
            telegram_bot_token=TOKEN,
            telegram_webhook_secret="hook",
            admin_telegram_chat_id=OWNER,
            web_origin=ORIGIN,
            default_timezone="UTC",
            openrouter_api_key=None,
        ),
        Overrides(
            models=models(model),
            speech=speech,
            telegram=FakeTelegram(),
            checkpointer=InMemorySaver(),
            clock=lambda: NOW,
        ),
    )


async def signed_in(app: Any) -> Browser:
    browser = Browser(app, Clock())
    assert (await browser.login(OWNER)).status_code == 200
    return browser


@pytest.fixture
async def voice(engine: AsyncEngine, empty_database_url: str) -> AsyncIterator[Voice]:
    model, speech = scripted(), FakeSpeech()
    app = make_app(empty_database_url, model, speech)
    async with app.router.lifespan_context(app):
        yield Voice(app, await signed_in(app), model, speech)


async def test_a_voice_note_is_answered_like_a_typed_message(voice: Voice) -> None:
    voice.model.script += LOG_LUNCH
    voice.speech.script += ["Lunch at Maxwell 8:40."]
    response = await voice.post(content_type="audio/webm;codecs=opus")
    assert response.status_code == 200
    [reply] = response.json()
    assert reply["text"] == f"{HEARD}\nLogged 8.40 at Maxwell."
    assert [b["data"] for row in reply["buttons"] for b in row] == ["act:undo"]
    assert voice.speech.heard == [(AUDIO, "webm")]  # the codec parameter is dropped
    history = (await voice.owner.get("/api/chat/history")).json()["lines"]
    assert [(x["role"], x["text"], x["channel"]) for x in history] == [
        ("user", "🎙 Lunch at Maxwell 8.40.", "web"),
        ("nexus", f"{HEARD}\nLogged 8.40 at Maxwell.", "web"),
    ]


async def test_a_question_by_voice_has_no_heard_line(voice: Voice) -> None:
    voice.model.script += [say("Nothing yet.")]
    voice.speech.script += ["How much did I spend on Grab this month?"]
    [reply] = (await voice.post(content_type="audio/mp4")).json()
    assert reply == {"text": "Nothing yet.", "buttons": []}
    assert voice.speech.heard[0][1] == "m4a"


@pytest.mark.parametrize(
    "content_type", ["audio/webm", "audio/ogg", "audio/mp4", "audio/m4a", "audio/aac", "audio/mpeg"]
)
async def test_every_accepted_type_gets_through(voice: Voice, content_type: str) -> None:
    voice.speech.script += [""]
    response = await voice.post(content_type=content_type)
    assert response.status_code == 200
    assert response.json()[0]["text"] == "Couldn't make that out — mind typing it?"


async def test_only_the_signed_in_user_with_the_csrf_token_may_send(voice: Voice) -> None:
    assert (await voice.post(csrf="wrong")).status_code == 403
    assert (await voice.post(csrf="")).status_code == 403
    assert (await voice.post(origin="https://evil.test")).status_code == 403
    stranger = Browser(voice.app, Clock())
    response = await stranger.client.post(
        "/api/chat/voice", files={"audio": ("n", AUDIO, "audio/webm")}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 401
    assert voice.speech.heard == []


async def test_a_note_over_5_mb_is_refused(voice: Voice) -> None:
    response = await voice.post(bytes(5 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json() == {"detail": TOO_LONG}
    # By its declared size, before the body is read.
    huge = await voice.post(bytes(5 * 1024 * 1024 + 200_000))
    assert huge.status_code == 413
    assert huge.json() == {"detail": TOO_LONG}
    assert voice.speech.heard == []


async def test_exactly_5_mb_is_fine(voice: Voice) -> None:
    voice.speech.script += [""]
    assert (await voice.post(bytes(5 * 1024 * 1024))).status_code == 200


@pytest.mark.parametrize("content_type", ["audio/wav", "video/mp4", "text/plain", "audio/flac"])
async def test_other_types_are_refused(voice: Voice, content_type: str) -> None:
    assert (await voice.post(content_type=content_type)).status_code == 415
    assert voice.speech.heard == []


async def test_the_recording_must_be_the_audio_field(voice: Voice) -> None:
    assert (await voice.post(field="file")).status_code == 422
    plain = await voice.owner.send("POST", "/api/chat/voice", {"audio": "x"})
    assert plain.status_code == 422


async def test_thirty_notes_an_hour_then_429(voice: Voice) -> None:
    service = voice.app.state.telegram.service
    service._limiter = RateLimiter(rules={"voice": ((2, timedelta(hours=1)),)}, clock=lambda: NOW)
    voice.speech.script += ["", ""]
    assert (await voice.post()).status_code == 200
    assert (await voice.post()).status_code == 200
    third = await voice.post()
    assert third.status_code == 429
    assert "voice notes" in third.json()["detail"]
    assert len(voice.speech.heard) == 2


async def test_without_a_speech_model_it_is_503(
    engine: AsyncEngine, empty_database_url: str
) -> None:
    app = make_app(empty_database_url, scripted(), None)
    async with app.router.lifespan_context(app):
        browser = await signed_in(app)
        response = await Voice(app, browser, scripted(), FakeSpeech()).post()
    assert response.status_code == 503
    assert response.json() == {"detail": "Voice notes aren't set up — mind typing it?"}


async def test_the_note_is_logged_for_the_signed_in_user_only(
    voice: Voice, engine: AsyncEngine
) -> None:
    voice.model.script += [call("log_expense", amount="4.20", merchant="Kopi"), say("Logged.")]
    voice.speech.script += ["kopi 4.20"]
    await voice.post()
    owner = await find_telegram_user(SqlUnitOfWork(engine), OWNER)
    assert owner is not None
    assert await ledger(lambda: SqlUnitOfWork(engine), owner.id) == [("out", Decimal("4.20"))]
