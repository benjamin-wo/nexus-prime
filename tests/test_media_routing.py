import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.ingress as ingress_module
import orchestrator.agent_loop as agent_loop_module
from app.ingress import TelegramIngress
from orchestrator.agent_loop import agent_loop


MEDIA_BLOCK = {"type": "media", "mime_type": "image/jpeg", "data": "aGVsbG8="}


class _FakeHttpResponse:
    def __init__(self, payload=None, status_code=200, content=b""):
        self._payload = payload
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._payload


class _FakeTelegramHttpClient:
    requests = []

    def __init__(self, **kwargs):
        self.options = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, url, **kwargs):
        self.requests.append(url)
        if url.endswith("/getFile"):
            return _FakeHttpResponse({
                "ok": True,
                "result": {"file_path": "photos/file_1.jpg"},
            })
        return _FakeHttpResponse(status_code=200, content=b"image-bytes")


class _FakeMultimodalLLM:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content="screenshot analyzed")


@pytest.mark.asyncio
async def test_multimodal_path_invokes_gemini_without_typeerror(monkeypatch):
    """A media message with a non-expense caption goes straight to Gemini
    vision for a description -- orchestrator/agent_loop.py's
    _handle_multimodal_turn(), the one deliberate exception to "the agent
    decides which tool to call": the main agent model (DeepSeek) has no
    vision, so it can't see the image to decide. This bypass happens before
    the tool-calling loop even builds, so get_agent_llm (the text/tool-
    calling model) must never be touched. (A captionless or expense-hinted
    photo instead tries extract_expense_from_photo first -- same routing
    CapabilityRouter used to apply before it dispatched to ExpensePlugin vs
    GeneralPlugin; covered by capabilities/expenses tests.)"""

    def _fail_if_called(*a, **k):
        raise AssertionError("text tool-calling model must not run for a media-only message")

    fake_llm = _FakeMultimodalLLM()
    monkeypatch.setattr(agent_loop_module, "get_multimodal_llm", lambda **k: fake_llm)
    monkeypatch.setattr(agent_loop_module, "get_agent_llm", _fail_if_called)
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")

    text_block = {"type": "text", "text": "what is this a screenshot of"}
    command = await agent_loop({
        "user_id": 4242,
        "messages": [HumanMessage(content=[text_block, MEDIA_BLOCK])],
    })

    assert len(fake_llm.calls) == 1
    assert "screenshot analyzed" in str(command.update["messages"][0].content)
    assert command.update["active_domain"] == "agent"


def _fake_graph_capture(captured):
    class _FakeGraph:
        async def ainvoke(self, initial_state, config=None):
            captured.append(initial_state)
            return {"messages": [AIMessage(content="ok")]}

    return _FakeGraph()


@pytest.mark.asyncio
async def test_ingress_keeps_download_failure_note(monkeypatch):
    captured = []

    async def _failed_download(self, file_id):
        return None

    monkeypatch.setattr(TelegramIngress, "_download_telegram_media", _failed_download)

    async def _no_action(chat_id, action="typing"):
        return True

    monkeypatch.setattr(ingress_module, "send_telegram_chat_action", _no_action)
    async def _no_slash_command(self, text, user_id=None):
        return None

    monkeypatch.setattr(TelegramIngress, "handle_slash_command", _no_slash_command)
    monkeypatch.setattr(ingress_module, "get_assistant_graph", lambda: _fake_graph_capture(captured))

    ingress = TelegramIngress()
    await ingress.handle_update({
        "message": {
            "chat": {"id": 555},
            "from": {"id": 555},
            "photo": [{"file_id": "abc", "width": 100}],
        }
    })

    assert captured, "graph should have been invoked"
    human = captured[0]["messages"][0]
    assert human.content == "⚠️ (couldn't download the attached media)"


@pytest.mark.asyncio
async def test_ingress_names_unreadable_attachments(monkeypatch):
    captured = []

    async def _no_action(chat_id, action="typing"):
        return True

    monkeypatch.setattr(ingress_module, "send_telegram_chat_action", _no_action)
    async def _no_slash_command(self, text, user_id=None):
        return None

    monkeypatch.setattr(TelegramIngress, "handle_slash_command", _no_slash_command)
    monkeypatch.setattr(ingress_module, "get_assistant_graph", lambda: _fake_graph_capture(captured))

    ingress = TelegramIngress()
    await ingress.handle_update({
        "message": {
            "chat": {"id": 556},
            "from": {"id": 556},
            "sticker": {"file_id": "xyz"},
        }
    })

    assert captured, "graph should have been invoked"
    human = captured[0]["messages"][0]
    assert human.content == "(sent a sticker I can't read yet)"


@pytest.mark.asyncio
async def test_telegram_media_download_uses_file_api_path(monkeypatch):
    _FakeTelegramHttpClient.requests = []
    monkeypatch.setattr(ingress_module.httpx, "AsyncClient", _FakeTelegramHttpClient)
    monkeypatch.setattr(ingress_module.settings, "telegram_bot_token", "test-token")

    result = await TelegramIngress()._download_telegram_media("file-123")

    assert result == ("photos/file_1.jpg", b"image-bytes")
    assert _FakeTelegramHttpClient.requests == [
        "https://api.telegram.org/bottest-token/getFile",
        "https://api.telegram.org/file/bottest-token/photos/file_1.jpg",
    ]
