import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from core.llm import (
    ThinkingLevel,
    get_llm,
    get_multimodal_llm,
    get_agent_llm,
    get_judge_llm,
    THINKING_CONFIGS,
)

def test_multimodal_io_llm_initialization():
    """Verify that role='multimodal_io' returns a ChatGoogleGenerativeAI instance for Gemini Flash."""
    from core.config import settings
    from core.llm import _rejects_sampling_params

    llm = get_llm(role="multimodal_io", temperature=0.2)
    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.model == settings.gemini_model
    # Whether temperature is forwarded depends on the configured model:
    # Gemini 3.x Flash 400s on sampling parameters and takes thinking_level
    # instead (see core.llm._gemini_reasoning_kwargs). Asserted per-model so
    # this stays a real check whichever model is configured, rather than
    # hardcoding one era's behaviour.
    if _rejects_sampling_params(settings.gemini_model):
        assert llm.temperature is None
        assert llm.thinking_level is not None
    else:
        assert llm.temperature == 0.2

    # Verify convenience helper
    helper_llm = get_multimodal_llm()
    assert isinstance(helper_llm, ChatGoogleGenerativeAI)
    assert helper_llm.model == settings.gemini_model


def test_judge_llm_initialization():
    """Verify the conversation judge uses Gemini Judge model."""
    from core.config import settings
    llm = get_judge_llm()
    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.model == settings.gemini_judge_model
    assert llm.temperature == 0.0

def test_agent_core_llm_with_gemini_provider(monkeypatch):
    """Verify that role='agent_core' with Gemini provider returns ChatGoogleGenerativeAI."""
    from core.config import settings
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    llm = get_llm(role="agent_core")
    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.model == settings.gemini_model


def test_agent_core_llm_low_thinking_level(monkeypatch):
    """Verify that role='agent_core' with DeepSeek provider configures DeepSeek with low reasoning effort."""
    from core.config import settings
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    llm = get_llm(role="agent_core", complexity=ThinkingLevel.LOW)
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "deepseek-v4-flash"
    assert llm.reasoning_effort == "low"
    assert llm.max_tokens == 2048

def test_agent_core_llm_high_thinking_level(monkeypatch):
    """Verify that role='agent_core' with HIGH complexity configures DeepSeek with high reasoning effort."""
    from core.config import settings
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    llm = get_llm(role="agent_core", complexity="high")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "deepseek-v4-flash"
    assert llm.reasoning_effort == "high"
    assert llm.max_tokens == 8192

def test_agent_core_llm_medium_default_thinking_level(monkeypatch):
    """Verify that get_agent_llm with DeepSeek defaults to MEDIUM thinking level."""
    from core.config import settings
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    llm = get_agent_llm()
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "deepseek-v4-flash"
    assert llm.reasoning_effort == "medium"
    assert llm.max_tokens == 4096

def test_unrecognized_complexity_falls_back_to_medium(monkeypatch):
    """Verify that an invalid complexity string gracefully falls back to MEDIUM for DeepSeek."""
    from core.config import settings
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    llm = get_agent_llm(complexity="super_heavy")
    assert isinstance(llm, ChatOpenAI)
    assert llm.reasoning_effort == "medium"
    assert llm.max_tokens == 4096

def test_invalid_role_raises_value_error():
    """Verify that requesting an unsupported role raises a ValueError."""
    with pytest.raises(ValueError, match="Unsupported LLM role"):
        get_llm(role="invalid_role")


def test_all_llm_clients_have_a_bounded_request_timeout(monkeypatch):
    """Regression (P0): none of the four client constructions set a request
    timeout, so a stalled provider call could hang an ainvoke() forever.
    That's fatal upstream -- app/webhook.py awaits the whole request chain
    before responding to Telegram, so one hung LLM call meant the webhook
    never returned, Telegram never got its 200 OK, and it redelivered the
    same update on its own backoff schedule indefinitely (verified against
    a real production incident: a stuck chat retried every ~60-130s for
    10+ minutes with the typing-indicator loop never cancelled, escalating
    to a sendChatAction 429 storm)."""
    from core.config import settings
    from core.llm import LLM_REQUEST_TIMEOUT_SECONDS

    assert LLM_REQUEST_TIMEOUT_SECONDS is not None and LLM_REQUEST_TIMEOUT_SECONDS > 0

    assert get_llm(role="multimodal_io").timeout == LLM_REQUEST_TIMEOUT_SECONDS
    assert get_judge_llm().timeout == LLM_REQUEST_TIMEOUT_SECONDS

    monkeypatch.setattr(settings, "llm_provider", "gemini")
    assert get_llm(role="agent_core").timeout == LLM_REQUEST_TIMEOUT_SECONDS

    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    assert get_agent_llm().request_timeout == LLM_REQUEST_TIMEOUT_SECONDS
