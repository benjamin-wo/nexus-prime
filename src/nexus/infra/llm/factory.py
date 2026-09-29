import re
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from nexus.settings import LlmProvider, Settings

# Gemini 3.x Flash models reject temperature/top_p/top_k with a 400; they take
# thinking_level instead.
_NO_SAMPLING_PARAMS = frozenset({"gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash"})


class LlmNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ChatModels:
    """The agent's model plus fallbacks, tried in order, and a vision model."""

    primary: BaseChatModel
    fallbacks: tuple[BaseChatModel, ...]
    # None when no Gemini key is configured: receipt photos are then unavailable.
    vision: BaseChatModel | None
    description: str


def _gemini_kwargs(model: str) -> dict[str, Any]:
    name = re.sub(r"-\d{3}$", "", model.lower().rsplit("/", 1)[-1])
    return {"thinking_level": "low"} if name in _NO_SAMPLING_PARAMS else {"temperature": 0.0}


def _gemini(settings: Settings, model: str) -> BaseChatModel:
    if settings.gemini_api_key is None:
        raise LlmNotConfigured("GEMINI_API_KEY is not set")
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.gemini_api_key,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_max_retries,
        **_gemini_kwargs(model),
    )


def _openai_compatible(
    settings: Settings, *, model: str, api_key: SecretStr | None, base_url: str | None, name: str
) -> BaseChatModel:
    if api_key is None:
        raise LlmNotConfigured(f"the {name} API key is not set")
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def _provider_model(settings: Settings, provider: LlmProvider) -> BaseChatModel:
    match provider:
        case LlmProvider.GEMINI:
            return _gemini(settings, settings.gemini_model)
        case LlmProvider.OPENROUTER:
            if not settings.openrouter_model:
                raise LlmNotConfigured("OPENROUTER_MODEL is not set")
            return _openai_compatible(
                settings,
                model=settings.openrouter_model,
                api_key=settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                name="OpenRouter",
            )
        case LlmProvider.DEEPSEEK:
            return _openai_compatible(
                settings,
                model=settings.deepseek_model,
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                name="DeepSeek",
            )
        case LlmProvider.OPENAI:
            return _openai_compatible(
                settings,
                model=settings.openai_model,
                api_key=settings.openai_api_key,
                base_url=None,
                name="OpenAI",
            )


def build_chat_models(settings: Settings) -> ChatModels:
    """Build from settings, or raise LlmNotConfigured.

    The fallback is LLM_FALLBACK_MODEL on Gemini, when a Gemini key is set.
    Receipts are read by Gemini, which handles images.
    """
    primary = _provider_model(settings, settings.llm_provider)
    fallbacks: list[BaseChatModel] = []
    if settings.gemini_api_key is not None and settings.llm_fallback_model:
        is_same = (
            settings.llm_provider is LlmProvider.GEMINI
            and settings.llm_fallback_model == settings.gemini_model
        )
        if not is_same:
            fallbacks.append(_gemini(settings, settings.llm_fallback_model))
    vision: BaseChatModel | None = None
    if settings.llm_provider is LlmProvider.GEMINI:
        vision = primary
    elif settings.gemini_api_key is not None:
        vision = _gemini(settings, settings.gemini_model)
    return ChatModels(primary, tuple(fallbacks), vision, settings.llm_provider.value)


def build_screener(settings: Settings, primary: BaseChatModel) -> BaseChatModel:
    """The cheap model that screens emails: EMAIL_CLASSIFIER_MODEL on OpenRouter when
    set, otherwise the main model."""
    if settings.email_classifier_model and settings.openrouter_api_key is not None:
        return _openai_compatible(
            settings,
            model=settings.email_classifier_model,
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            name="OpenRouter",
        )
    return primary


def text_of(content: Any) -> str:
    """Plain text from a model reply; Gemini may return a list of typed parts."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            item if isinstance(item, str) else str(item.get("text", ""))
            for item in content
            if isinstance(item, str) or (isinstance(item, dict) and item.get("type") == "text")
        ]
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()
