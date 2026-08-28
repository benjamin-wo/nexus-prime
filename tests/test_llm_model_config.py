"""Model selection and per-model reasoning parameters.

Gemini 3.x Flash dropped the sampling parameters: temperature/top_p/top_k are
a 400 on those models, not a silently-ignored field. Google's migration
guidance for 3.7 Flash is to remove them and steer with thinking_level.

langchain-google-genai keeps its own list of such models and would strip the
parameters for us, but the pinned 4.3.2 predates gemini-3.7-flash's
2026-08-13 GA -- it knows only 3.5-flash-lite and 3.6-flash. So switching the
model without this handling would have sent temperature=0.7 straight through
and 400'd every single agent call.
"""
import pytest

from core.config import settings
from core.llm import (
    ThinkingLevel,
    _rejects_sampling_params,
    get_agent_llm,
    get_judge_llm,
    get_multimodal_llm,
)


@pytest.fixture(autouse=True)
def _gemini_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key-for-construction-test")


@pytest.mark.parametrize(
    "model_name,rejects",
    [
        ("gemini-3.7-flash", True),
        ("gemini-3.6-flash", True),
        ("gemini-3.5-flash-lite", True),
        ("gemini-3.7-flash-001", True),      # pinned point release
        ("models/gemini-3.7-flash", True),   # fully-qualified form
        ("gemini-2.5-flash", False),         # the model we came from
        ("gemini-3.1-pro-preview", False),   # the judge
    ],
)
def test_sampling_parameter_support_is_detected_per_model(model_name, rejects):
    assert _rejects_sampling_params(model_name) is rejects


def test_the_agent_model_sends_thinking_level_and_no_temperature(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.7-flash")

    llm = get_agent_llm(complexity=ThinkingLevel.MEDIUM, temperature=0.7)

    assert llm.model == "gemini-3.7-flash"
    assert llm.thinking_level == "medium"
    assert llm.temperature is None, (
        "gemini-3.7-flash 400s on temperature -- it must never be sent"
    )


@pytest.mark.parametrize(
    "complexity,expected",
    [(ThinkingLevel.LOW, "low"), (ThinkingLevel.MEDIUM, "medium"), (ThinkingLevel.HIGH, "high")],
)
def test_thinking_level_follows_the_requested_complexity(monkeypatch, complexity, expected):
    """ThinkingLevel used to be computed and then discarded on the Gemini
    path -- it only ever reached DeepSeek. Now it actually steers Gemini."""
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.7-flash")
    assert get_agent_llm(complexity=complexity).thinking_level == expected


def test_an_unknown_complexity_falls_back_to_medium(monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.7-flash")
    assert get_agent_llm(complexity="nonsense").thinking_level == "medium"


def test_the_vision_model_gets_the_same_treatment(monkeypatch):
    """get_multimodal_llm shares settings.gemini_model, so the switch hits the
    receipt-photo path too."""
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.7-flash")

    mm = get_multimodal_llm(temperature=0.2)

    assert mm.temperature is None
    assert mm.thinking_level == "medium"


def test_a_model_that_still_takes_temperature_keeps_it(monkeypatch):
    """The guard must be per-model, not a blanket removal -- older models and
    the judge still accept sampling parameters."""
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-flash")

    llm = get_agent_llm(complexity=ThinkingLevel.MEDIUM, temperature=0.7)

    assert llm.temperature == 0.7
    assert llm.thinking_level is None


def test_the_judge_model_is_unaffected_by_the_agent_switch():
    judge = get_judge_llm(temperature=0.0)

    assert judge.model == settings.gemini_judge_model
    assert judge.temperature == 0.0


def test_the_configured_default_is_the_intended_model():
    """Guards against the code default drifting away from what production
    runs. NOTE: Railway sets GEMINI_MODEL explicitly, and that env var
    overrides this default -- both must be changed together."""
    from core.config import Settings

    assert Settings().gemini_model == "gemini-3.7-flash"


def test_the_deepseek_path_is_untouched(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", "fake-deepseek-key")

    llm = get_agent_llm(complexity=ThinkingLevel.HIGH, temperature=0.7)

    assert llm.temperature == 0.7
    assert llm.reasoning_effort == "high"
