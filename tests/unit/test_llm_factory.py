"""Which models the app builds from its settings."""

from typing import Any

import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from nexus.infra.llm.factory import (
    LlmNotConfigured,
    build_chat_models,
    build_email_reader,
    build_memory_model,
    build_screener,
)
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


def test_openrouter_providers_pin_the_main_model_only(monkeypatch: pytest.MonkeyPatch) -> None:
    # A cheap host that drops tool arguments made edits fail: the main model can be
    # kept to providers that handle tool calls well.
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "deepinfra, fireworks")
    models = build_chat_models(
        settings(
            llm_provider="openrouter",
            openrouter_api_key="or-key",
            openrouter_model="deepseek/deepseek-v4.1-flash",
            openrouter_vision_model="qwen/qwen3.8-flash",
        )
    )
    assert isinstance(models.primary, ChatOpenAI)
    assert models.primary.extra_body == {
        "provider": {
            "order": ["deepinfra", "fireworks"],
            "only": ["deepinfra", "fireworks"],
            "require_parameters": True,
        }
    }
    # The receipt reader is another model: those providers may not serve it.
    assert isinstance(models.vision, ChatOpenAI) and models.vision.extra_body is None
    unpinned = build_chat_models(
        settings(
            llm_provider="openrouter",
            openrouter_api_key="or-key",
            openrouter_model="deepseek/deepseek-v4.1-flash",
            openrouter_providers="",
        )
    )
    assert isinstance(unpinned.primary, ChatOpenAI) and unpinned.primary.extra_body is None


def test_email_and_memory_reads_run_without_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    # With reasoning on, an email read took longer than its 25-second limit and the
    # user saw "couldn't read"; the memory writer ran out of reply length.
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "deepinfra")
    config = settings(
        llm_provider="openrouter",
        openrouter_api_key="or-key",
        openrouter_model="deepseek/deepseek-v4.1-flash",
        memory_model="small/model",
    )
    primary = build_chat_models(config).primary
    for build in (build_screener, build_email_reader):
        model = build(config, primary)
        assert model is not primary and model_name(model) == "deepseek/deepseek-v4.1-flash"
        assert isinstance(model, ChatOpenAI) and model.extra_body is not None
        assert model.extra_body["reasoning"] == {"enabled": False}
        assert model.extra_body["provider"]["only"] == ["deepinfra"]  # routed like the main
    memory = build_memory_model(config, primary)
    assert model_name(memory) == "small/model"
    assert isinstance(memory, ChatOpenAI)
    assert memory.extra_body == {"reasoning": {"enabled": False}}
    # Other providers keep the main model as it is.
    gemini = settings(llm_provider="gemini", gemini_api_key="g-key")
    main = build_chat_models(gemini).primary
    assert build_email_reader(gemini, main) is main


def test_the_research_team_writes_without_reasoning() -> None:
    from nexus.infra.llm.factory import build_research_models

    s = settings(
        llm_provider="openrouter",
        openrouter_api_key="sk-or-test",
        openrouter_model="deepseek/deepseek-v4.1-flash",
        openrouter_providers="deepinfra,fireworks",
    )
    primary = build_chat_models(s).primary
    analyst, lead = build_research_models(s, primary)
    assert analyst is lead and model_name(analyst) == "deepseek/deepseek-v4.1-flash"
    assert isinstance(analyst, ChatOpenAI)
    assert analyst.extra_body is not None
    assert analyst.extra_body["reasoning"] == {"enabled": False}
    assert analyst.extra_body["provider"]["order"] == ["deepinfra", "fireworks"]  # routed
    own = settings(
        llm_provider="openrouter",
        openrouter_api_key="sk-or-test",
        openrouter_model="deepseek/deepseek-v4.1-flash",
        research_model="vendor/analyst-model",
        research_lead_model="vendor/lead-model",
    )
    analyst, lead = build_research_models(own, build_chat_models(own).primary)
    assert (model_name(analyst), model_name(lead)) == ("vendor/analyst-model", "vendor/lead-model")
    for m in (analyst, lead):
        assert isinstance(m, ChatOpenAI) and m.extra_body is not None
        assert m.extra_body["reasoning"] == {"enabled": False}
