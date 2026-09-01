import pytest
from langchain_core.messages import AIMessage

from evals.config import EvalConfig
from evals.judge import (
    aggregate_judgments,
    build_judge_prompt,
    judge_conversation,
    parse_judgment,
)
from evals.transcript import Conversation, Turn

GOOD_JSON = (
    '{"criteria": {"tone": 5, "factual_accuracy": 4, "safety": 5, '
    '"hallucination": 4, "helpfulness": 5}, "overall": 4.6, "summary": "solid"}'
)


def test_parse_judgment_strips_fences():
    judgment = parse_judgment("```json\n" + GOOD_JSON + "\n```")
    assert judgment["overall"] == 4.6
    assert judgment["criteria"]["tone"] == 5


def test_parse_judgment_malformed_raises():
    with pytest.raises(ValueError):
        parse_judgment("not json at all")


def test_build_judge_prompt_truncates():
    conv = Conversation(
        id="c",
        scenario_id="s",
        turns=[Turn(role="user", text=f"message {i}") for i in range(30)],
    )
    prompt = build_judge_prompt(conv, max_turns=4)
    assert prompt.count("USER:") == 4


class _FakeJudge:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, messages):
        return AIMessage(content=self.content)


@pytest.mark.asyncio
async def test_judge_conversation_ok():
    conv = Conversation(
        id="c1",
        scenario_id="s1",
        turns=[Turn(role="user", text="hi"), Turn(role="assistant", text="hello!")],
    )
    judgment = await judge_conversation(conv, _FakeJudge(GOOD_JSON), EvalConfig())
    assert judgment["error"] is None
    assert judgment["overall"] == 4.6
    assert judgment["turns"] == 2


@pytest.mark.asyncio
async def test_judge_conversation_error_recorded():
    conv = Conversation(id="c2", scenario_id="s1", turns=[Turn(role="user", text="hi")])
    judgment = await judge_conversation(conv, _FakeJudge("garbage output"), EvalConfig())
    assert judgment["error"] is not None
    assert judgment["overall"] == 0.0


def _judgment(id_, overall, safety, error=None):
    criteria = {c: 5.0 for c in ["tone", "factual_accuracy", "safety", "hallucination", "helpfulness"]}
    criteria["safety"] = safety
    return {
        "id": id_,
        "scenario_id": "s",
        "turns": 2,
        "criteria": criteria,
        "overall": overall,
        "summary": "",
        "error": error,
    }


def test_aggregate_judgments():
    cfg = EvalConfig()
    ok = _judgment("a", 5.0, 5.0)
    bad_safety = _judgment("b", 4.5, 1.0)
    errored = _judgment("c", 0.0, 0.0, error="boom")
    report = aggregate_judgments([ok, bad_safety, errored], cfg)
    assert report["count"] == 3
    assert report["judged"] == 2
    assert report["passed"] == 1
    assert report["failed_judgments"] == 1
    assert report["all_passed"] is False


def test_aggregate_all_passed():
    cfg = EvalConfig()
    report = aggregate_judgments([_judgment("a", 5.0, 5.0), _judgment("b", 4.2, 4.0)], cfg)
    assert report["all_passed"] is True
    assert report["overall_mean"] == pytest.approx(4.6)