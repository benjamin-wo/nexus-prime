import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.ingress as ingress_module
import orchestrator.plan_router as plan_router_module
import orchestrator.router as router_module
from app.ingress import TelegramIngress
from orchestrator.plan_router import plan_dispatch
from orchestrator.router import GeneralPlugin


MEDIA_BLOCK = {"type": "media", "mime_type": "image/jpeg", "data": "aGVsbG8="}


class _FakeMultimodalLLM:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content="screenshot analyzed")


@pytest.mark.asyncio
async def test_multimodal_path_invokes_gemini_without_typeerror(monkeypatch):
    fake_llm = _FakeMultimodalLLM()
    monkeypatch.setattr(router_module, "get_multimodal_llm", lambda **k: fake_llm)
    monkeypatch.setattr(router_module.settings, "gemini_api_key", "fake-key-for-test")

    output = await GeneralPlugin().execute({
        "user_id": 4242,
        "messages": [HumanMessage(content=[MEDIA_BLOCK])],
    })

    assert len(fake_llm.calls) == 1
    assert "screenshot analyzed" in str(output.message.content)
    assert output.state_update == {"active_domain": "general"}


class _SpyGeneralPlugin:
    name = "general"
    keywords = []
    description = "spy"

    def __init__(self):
        self.executed = []

    async def execute(self, state):
        self.executed.append(state)
        from orchestrator.router import PluginOutput

        return PluginOutput(
            message=AIMessage(content="media answer"),
            state_update={"active_domain": "general"},
        )


@pytest.mark.asyncio
async def test_plan_dispatch_routes_media_only_message_straight_to_general(monkeypatch):
    from orchestrator.router import CAPABILITY_REGISTRY, PluginOutput

    async def _fail(*args, **kwargs):
        raise AssertionError("planner must not run for media-only messages")

    monkeypatch.setattr(plan_router_module, "plan_with_llm", _fail, raising=False)
    spy = _SpyGeneralPlugin()
    monkeypatch.setitem(CAPABILITY_REGISTRY, "general", spy)

    result = await plan_dispatch({
        "user_id": 4242,
        "messages": [HumanMessage(content=[MEDIA_BLOCK])],
    })

    update = result.update
    assert len(spy.executed) == 1
    assert "media answer" in str(update["messages"][0].content)
    assert update["active_domain"] == "general"
    assert update["plan"]["source"] == "deterministic-media"


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
