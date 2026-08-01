import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from core.llm import (
    ThinkingLevel,
    get_llm,
    get_multimodal_llm,
    get_agent_llm,
    THINKING_CONFIGS,
)

def test_multimodal_io_llm_initialization():
    """Verify that role='multimodal_io' returns a ChatGoogleGenerativeAI instance for Gemini Flash."""
    llm = get_llm(role="multimodal_io", temperature=0.2)
    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.model == "gemini-3.1-flash-lite"
    assert llm.temperature == 0.2

    # Verify convenience helper
    helper_llm = get_multimodal_llm()
    assert isinstance(helper_llm, ChatGoogleGenerativeAI)
    assert helper_llm.model == "gemini-3.1-flash-lite"

def test_agent_core_llm_low_thinking_level():
    """Verify that role='agent_core' with LOW complexity configures DeepSeek v4 Flash with low reasoning effort."""
    llm = get_llm(role="agent_core", complexity=ThinkingLevel.LOW)
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "deepseek-v4-flash"
    assert llm.reasoning_effort == "low"
    assert llm.max_tokens == 512

def test_agent_core_llm_high_thinking_level():
    """Verify that role='agent_core' with HIGH complexity configures DeepSeek v4 Flash with high reasoning effort."""
    llm = get_llm(role="agent_core", complexity="high")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "deepseek-v4-flash"
    assert llm.reasoning_effort == "high"
    assert llm.max_tokens == 4096

def test_agent_core_llm_medium_default_thinking_level():
    """Verify that get_agent_llm defaults to MEDIUM thinking level."""
    llm = get_agent_llm()
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "deepseek-v4-flash"
    assert llm.reasoning_effort == "medium"
    assert llm.max_tokens == 2048

def test_unrecognized_complexity_falls_back_to_medium():
    """Verify that an invalid complexity string gracefully falls back to MEDIUM."""
    llm = get_agent_llm(complexity="super_heavy")
    assert llm.reasoning_effort == "medium"
    assert llm.max_tokens == 2048

def test_invalid_role_raises_value_error():
    """Verify that requesting an unsupported role raises a ValueError."""
    with pytest.raises(ValueError, match="Unsupported LLM role"):
        get_llm(role="invalid_role")
