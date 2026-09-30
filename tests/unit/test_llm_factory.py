"""Which models the app builds from its settings."""

from typing import Any

import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from nexus.infra.llm.factory import LlmNotConfigured, build_chat_models
from nexus.settings import Settings


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://u:p@h/db", **values)


def model_name(model: Any) -> str:
    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base == "https://openrouter.ai/api/v1"
    return str(model.model_name)


def test_openrouter_routes_everything_and_never_uses_gemini() -> None:
    models = build_chat_models(
        settings(
            llm_provider="openrouter",
            openrouter_api_key="or-key",
            openrouter_model="openai/gpt-6-luna",
            openrouter_fallback_models="qwen/qwen3.8-flash, openai/gpt-6-luna,z-ai/glm-5.3-flash",
            # A Gemini key left in the environment is ignored on OpenRouter.
            gemini_api_key="g-key",
            llm_fallback_model="gemini-3.7-flash",
        )
    )
    assert model_name(models.primary) == "openai/gpt-6-luna"
    # In order, without repeating the main model.
    assert [model_name(m) for m in models.fallbacks] == ["qwen/qwen3.8-flash", "z-ai/glm-5.3-flash"]
    assert models.vision is models.primary  # the main model reads receipts too
    assert models.description == "OpenRouter openai/gpt-6-luna"


def test_openrouter_can_read_receipts_with_another_model() -> None:
    models = build_chat_models(
        settings(
            llm_provider="openrouter",
            openrouter_api_key="or-key",
            openrouter_model="deepseek/deepseek-v4-pro-0813",
            openrouter_vision_model="google/gemini-3.8-flash",
        )
    )
    assert models.fallbacks == ()
    assert models.vision is not None and model_name(models.vision) == "google/gemini-3.8-flash"


def test_openrouter_needs_its_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENROUTER_API_KEY", "OPENROUTER_MODEL"):
        monkeypatch.delenv(name, raising=False)  # set in some shells: use none here
    with pytest.raises(LlmNotConfigured):
        build_chat_models(settings(llm_provider="openrouter", openrouter_model="a/b"))
    with pytest.raises(LlmNotConfigured):
        build_chat_models(settings(llm_provider="openrouter", openrouter_api_key="or-key"))


def test_gemini_setup_is_unchanged() -> None:
    models = build_chat_models(settings(llm_provider="gemini", gemini_api_key="g-key"))
    assert isinstance(models.primary, ChatGoogleGenerativeAI)
    assert models.vision is models.primary


@pytest.mark.parametrize(
    "raw",
    ["qwen/qwen3.8-flash, z-ai/glm-5.3-flash", '["qwen/qwen3.8-flash", "z-ai/glm-5.3-flash"]'],
)
def test_fallbacks_read_from_the_environment(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    # As Railway sets it: an environment variable, plain or JSON.
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", raw)
    assert settings().openrouter_fallback_models == ("qwen/qwen3.8-flash", "z-ai/glm-5.3-flash")
