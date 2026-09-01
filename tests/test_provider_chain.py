from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from core.config import settings
from core.llm import (
    ThinkingLevel,
    build_extra_provider_rungs,
    get_fallback_llm,
)


def test_extra_rungs_empty_without_keys(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    assert build_extra_provider_rungs() == []


def test_extra_rungs_exclude_placeholder_keys(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "test_deepseek_key")
    monkeypatch.setattr(settings, "openai_api_key", "your_openai_api_key_here")
    assert build_extra_provider_rungs() == []


def test_extra_rungs_include_deepseek_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-real-deepseek")
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    rungs = build_extra_provider_rungs(complexity=ThinkingLevel.LOW, temperature=0.1)
    assert [label for label, _ in rungs] == ["deepseek"]
    assert isinstance(rungs[0][1], ChatOpenAI)


def test_extra_rungs_exclude_deepseek_when_primary(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-real-deepseek")
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    assert build_extra_provider_rungs() == []


def test_extra_rungs_include_openrouter_and_openai(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-real")
    monkeypatch.setattr(settings, "openrouter_model", "anthropic/claude-3.5-sonnet")
    monkeypatch.setattr(settings, "openai_api_key", "sk-oa-real")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    rungs = build_extra_provider_rungs()
    labels = [label for label, _ in rungs]
    assert labels == ["openrouter", "openai"]
    assert all(isinstance(client, ChatOpenAI) for _, client in rungs)


def test_get_fallback_llm_prefers_gemini_fallback_model(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.5-flash")
    monkeypatch.setattr(settings, "llm_fallback_model", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "gemini_api_key", "sk-gemini-real")
    monkeypatch.setattr(settings, "google_api_key", None)
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    client = get_fallback_llm(complexity=ThinkingLevel.LOW, temperature=0.1)
    assert isinstance(client, ChatGoogleGenerativeAI)
    assert client.model == "gemini-2.5-flash"


def test_get_fallback_llm_falls_to_multimodal_without_other_keys(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.5-flash")
    monkeypatch.setattr(settings, "llm_fallback_model", "")
    monkeypatch.setattr(settings, "gemini_api_key", "sk-gemini-real")
    monkeypatch.setattr(settings, "google_api_key", None)
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    client = get_fallback_llm()
    assert isinstance(client, ChatGoogleGenerativeAI)
    assert client.model == "gemini-3.5-flash"