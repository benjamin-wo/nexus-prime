import logging
import re
from enum import Enum
from typing import Any, Dict, Union
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from core.config import settings

logger = logging.getLogger("nexus_prime.llm")

# None of the four client constructions below set a request timeout, so a
# stalled provider call (network stall, provider-side hang) can block an
# ainvoke() indefinitely. That is fatal upstream: app/webhook.py awaits the
# whole request-handling chain before responding to Telegram, so a single
# hung LLM call there means the webhook never returns, Telegram never gets
# its 200 OK, and it redelivers the same update on its own backoff schedule
# forever -- piling up duplicate in-flight work for one stuck chat.
LLM_REQUEST_TIMEOUT_SECONDS = 30.0

# The Gemini client retries internally SIX times by default. With a 30s
# per-attempt timeout that is a ~3min worst case hidden inside a single
# ainvoke(), far longer than any bound the caller thinks it has -- and each
# retry is another chance to swallow an outer cancellation (see
# core.tool_safety.bounded_call, and the silent-reply incident it documents).
# 2 = the initial request plus one genuine retry for a transient blip.
LLM_MAX_RETRIES = 2

class ThinkingLevel(str, Enum):
    """
    Thinking complexity tiers for DeepSeek v4 Flash agent reasoning.
    Controls reasoning token budgets and effort allocation based on task complexity.
    """
    LOW = "low"        # 0–512 tokens: basic chit-chat, simple button callbacks, keyword routing
    MEDIUM = "medium"  # 1024–2048 tokens: standard domain subagent execution (email, expenses, etc.)
    HIGH = "high"      # 4096+ tokens: multi-step planning, capability gap synthesis, HITL conflict resolution

# Map ThinkingLevel to token budgets and reasoning effort
THINKING_CONFIGS: Dict[str, Dict[str, Any]] = {
    ThinkingLevel.LOW.value: {
        "reasoning_effort": "low",
        "max_tokens": 2048,
    },
    ThinkingLevel.MEDIUM.value: {
        "reasoning_effort": "medium",
        "max_tokens": 4096,
    },
    ThinkingLevel.HIGH.value: {
        "reasoning_effort": "high",
        "max_tokens": 8192,
    },
}

# Gemini 3.x Flash models dropped the sampling parameters entirely: passing
# temperature/top_p/top_k to them is a 400, not a silently-ignored field.
# Google's own migration guidance for 3.7 Flash is explicit -- "remove
# deprecated sampling parameters (temperature, top_p, top_k)" -- and directs
# callers to thinking_level instead.
#
# langchain-google-genai carries its own copy of this list
# (_FIXED_SAMPLING_AND_NO_PREFILL_MODELS) and would strip the parameters for
# us, but 4.3.2 predates gemini-3.7-flash's 2026-08-13 GA and so knows only
# 3.5-flash-lite and 3.6-flash. Ours is the superset. When the library
# catches up this can defer to it instead.
_NO_SAMPLING_PARAM_MODELS = frozenset(
    {"gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash"}
)


def _rejects_sampling_params(model_name: str) -> bool:
    """Whether `model_name` 400s on temperature/top_p/top_k."""
    normalized = (model_name or "").lower().rsplit("/", 1)[-1]
    normalized = re.sub(r"-\d{3}$", "", normalized)  # strip a -001 style suffix
    return normalized in _NO_SAMPLING_PARAM_MODELS


def _normalize_thinking_level(complexity: Union[ThinkingLevel, str]) -> str:
    level = complexity.value if isinstance(complexity, ThinkingLevel) else str(complexity).lower()
    if level not in THINKING_CONFIGS:
        logger.warning(f"Unknown thinking complexity '{complexity}', falling back to 'medium'.")
        level = ThinkingLevel.MEDIUM.value
    return level


def _gemini_reasoning_kwargs(
    model_name: str, temperature: float, complexity: Union[ThinkingLevel, str]
) -> Dict[str, Any]:
    """Sampling/reasoning kwargs appropriate to `model_name`.

    For a model that still takes sampling parameters, that is just the
    temperature it was called with. For a Gemini 3.x Flash that rejects them,
    reasoning depth is steered by thinking_level instead -- which this repo
    already has a vocabulary for: ThinkingLevel's low/medium/high are exactly
    the values 3.7 Flash accepts (it dropped "minimal"). Previously that enum
    only ever reached DeepSeek; on Gemini it was computed and discarded.
    """
    if _rejects_sampling_params(model_name):
        return {"thinking_level": _normalize_thinking_level(complexity)}
    return {"temperature": temperature}


def get_llm(
    role: str = "agent_core",
    complexity: Union[ThinkingLevel, str] = ThinkingLevel.MEDIUM,
    temperature: float = 0.0,
    model: Optional[str] = None,
) -> Any:
    """
    Factory function for Hybrid Multimodal (Gemini Flash) & Variable-Thinking (DeepSeek v4 Flash) LLM routing.

    Args:
        role: Either "multimodal_io" (Google Gemini) or "agent_core" (DeepSeek v4 Flash).
        complexity: ThinkingLevel ("low", "medium", "high") controlling reasoning depth for DeepSeek.
        temperature: Sampling temperature.

    Returns:
        Configured LangChain chat model instance.
    """
    if role == "multimodal_io":
        api_key = settings.active_gemini_api_key or "test_google_key"
        chosen_model = model or settings.gemini_model
        logger.debug(f"Initializing Google Gemini ({chosen_model}) for multimodal_io role.")
        return ChatGoogleGenerativeAI(
            model=chosen_model,
            google_api_key=api_key,
            timeout=LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
            **_gemini_reasoning_kwargs(settings.gemini_model, temperature, complexity),
        )

    elif role == "agent_core":
        if settings.llm_provider == "gemini" or (not settings.deepseek_api_key and settings.active_gemini_api_key):
            api_key = settings.active_gemini_api_key or "test_google_key"
            chosen_model = model or settings.gemini_model
            logger.debug(f"Initializing Google Gemini ({chosen_model}) for agent_core role.")
            return ChatGoogleGenerativeAI(
                model=chosen_model,
                google_api_key=api_key,
                timeout=LLM_REQUEST_TIMEOUT_SECONDS,
                max_retries=LLM_MAX_RETRIES,
                **_gemini_reasoning_kwargs(settings.gemini_model, temperature, complexity),
            )

        api_key = settings.deepseek_api_key or "test_deepseek_key"
        base_url = settings.deepseek_base_url or "https://api.deepseek.com/v1"
        
        # Normalize complexity level
        level_key = complexity.value if isinstance(complexity, ThinkingLevel) else str(complexity).lower()
        if level_key not in THINKING_CONFIGS:
            logger.warning(f"Unknown thinking complexity '{complexity}', falling back to 'medium'.")
            level_key = ThinkingLevel.MEDIUM.value

        thinking_config = THINKING_CONFIGS[level_key]
        logger.debug(
            f"Initializing DeepSeek ({settings.deepseek_model}) for agent_core role "
            f"with thinking level='{level_key}' ({thinking_config})."
        )

        return ChatOpenAI(
            model=settings.deepseek_model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            reasoning_effort=thinking_config["reasoning_effort"],
            max_tokens=thinking_config["max_tokens"],
            timeout=LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )

    else:
        raise ValueError(
            f"Unsupported LLM role: '{role}'. Must be 'multimodal_io' (Gemini) or 'agent_core' (DeepSeek)."
        )

def get_multimodal_llm(temperature: float = 0.0) -> ChatGoogleGenerativeAI:
    """Convenience helper to obtain Google Gemini Flash for multimodal I/O tasks."""
    return get_llm(role="multimodal_io", temperature=temperature)


def get_judge_llm(temperature: float = 0.0) -> ChatGoogleGenerativeAI:
    """Gemini Pro used as the LLM-as-a-Judge for whole-conversation reviews."""
    api_key = settings.active_gemini_api_key or "test_google_key"
    return ChatGoogleGenerativeAI(
        model=settings.gemini_judge_model,
        google_api_key=api_key,
        temperature=temperature,
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
    )

def get_agent_llm(
    complexity: Union[ThinkingLevel, str] = ThinkingLevel.MEDIUM,
    temperature: float = 0.0,
    model: Optional[str] = None,
) -> ChatOpenAI:
    """Convenience helper to obtain the agent-core LLM. `model` overrides the
    provider's default -- used by the degraded-mode fallback path."""
    return get_llm(role="agent_core", complexity=complexity, temperature=temperature, model=model)


def extract_llm_text(content: Any) -> str:
    """
    Normalize an LLM response into plain text. Gemini may return a list of
    typed parts (e.g. [{'type': 'text', 'text': ...}]) rather than a string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
        return "\n".join(parts).strip()
    return str(content)
