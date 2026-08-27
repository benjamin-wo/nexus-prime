import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from orchestrator.checkpointer import prune_and_summarize_messages, recent_turns


def _long_conversation(fact: str, turns: int = 19) -> list:
    """A conversation that opens with a distinctive fact, then `turns` filler
    exchanges — long enough to trip GeneralPlugin's `len(messages) > 12` pruning
    trigger."""
    messages = [HumanMessage(content=fact)]
    for i in range(turns):
        messages.append(
            HumanMessage(content=f"filler message {i}")
            if i % 2 == 0
            else AIMessage(content=f"filler reply {i}")
        )
    return messages


def test_prune_and_summarize_keeps_early_fact_in_the_summary():
    messages = _long_conversation("My dog is named Biscuit")
    pruned, summary = prune_and_summarize_messages(messages, threshold=12)

    assert "Biscuit" in summary
    assert isinstance(pruned[0], SystemMessage)
    assert "Biscuit" in str(pruned[0].content)


def test_prune_and_summarize_is_a_noop_under_threshold():
    messages = _long_conversation("My dog is named Biscuit", turns=5)
    pruned, summary = prune_and_summarize_messages(messages, threshold=12)

    assert pruned == messages
    assert summary == ""


class _CapturingLLM:
    """Records the exact message list it was invoked with."""

    def __init__(self):
        self.calls: list = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        return AIMessage(content="here's what I've got")


@pytest.mark.asyncio
async def test_agent_loop_carries_the_summary_into_llm_history(monkeypatch):
    """Regression: GeneralPlugin.execute (deleted, logic now in
    orchestrator/agent_loop.py's agent_loop()) used to re-slice the already-
    bounded `pruned` list with `[-8:]`, which cut off the summary
    SystemMessage sitting at index 0 — and even when that note survived, the
    history-building loop's if/elif only recognized HumanMessage/AIMessage,
    so a SystemMessage fell through and was silently dropped either way. Net
    effect: once a conversation passed ~12-20 messages, anything before the
    last ~8 turns vanished from the assistant's context with no compensating
    summary — "the chat cannot remember what they said earlier." """
    import orchestrator.agent_loop as agent_loop_module
    from orchestrator.agent_loop import agent_loop

    fake_llm = _CapturingLLM()
    monkeypatch.setattr(agent_loop_module, "get_agent_llm", lambda *a, **k: fake_llm)
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")

    messages = _long_conversation("My dog is named Biscuit")
    messages.append(HumanMessage(content="what's my dog's name again?"))

    command = await agent_loop({"user_id": 1, "messages": messages})

    assert fake_llm.calls, "the LLM should have been invoked"
    history = fake_llm.calls[0]
    history_text = "\n".join(str(getattr(m, "content", "")) for m in history)
    assert "Biscuit" in history_text
    assert command.update["messages"][0].content == "here's what I've got"


# --- recent_turns (#35) -------------------------------------------------

def test_recent_turns_excludes_the_current_message_by_default():
    """The current message is the plugin's own primary input, extracted
    separately -- including it again here would just duplicate it."""
    messages = [
        HumanMessage(content="spent $15 on lunch"),
        AIMessage(content="Logged $15 for lunch."),
        HumanMessage(content="actually make that $20"),
    ]
    context = recent_turns(messages)
    assert "spent $15 on lunch" in context
    assert "Logged $15 for lunch" in context
    assert "actually make that $20" not in context


def test_recent_turns_caps_at_n_pairs():
    messages = []
    for i in range(10):
        messages.append(HumanMessage(content=f"user turn {i}"))
        messages.append(AIMessage(content=f"reply {i}"))
    messages.append(HumanMessage(content="current message"))

    context = recent_turns(messages, n=2)
    assert "user turn 9" in context
    assert "reply 9" in context
    assert "user turn 8" in context
    assert "user turn 7" not in context  # older than the last 2 pairs


def test_recent_turns_empty_for_first_message_in_conversation():
    assert recent_turns([HumanMessage(content="hello")]) == ""
    assert recent_turns([]) == ""


def test_recent_turns_formats_roles_distinctly():
    messages = [
        HumanMessage(content="what's on my Bali board"),
        AIMessage(content="Villa Samatha, booked."),
        HumanMessage(content="current"),
    ]
    context = recent_turns(messages)
    assert "User: what's on my Bali board" in context
    assert "Assistant: Villa Samatha, booked." in context
