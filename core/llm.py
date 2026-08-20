import logging
from enum import Enum
from typing import Any, Dict, Union
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from core.config import settings

logger = logging.getLogger("nexus_prime.llm")

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
        "max_tokens": 512,
    },
    ThinkingLevel.MEDIUM.value: {
        "reasoning_effort": "medium",
        "max_tokens": 2048,
    },
    ThinkingLevel.HIGH.value: {
        "reasoning_effort": "high",
        "max_tokens": 4096,
    },
}

def get_llm(
    role: str = "agent_core",
    complexity: Union[ThinkingLevel, str] = ThinkingLevel.MEDIUM,
    temperature: float = 0.0,
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
        logger.debug(f"Initializing Google Gemini ({settings.gemini_model}) for multimodal_io role.")
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=api_key,
            temperature=temperature,
        )

    elif role == "agent_core":
        if settings.llm_provider == "gemini" or (not settings.deepseek_api_key and settings.active_gemini_api_key):
            api_key = settings.active_gemini_api_key or "test_google_key"
            logger.debug(f"Initializing Google Gemini ({settings.gemini_model}) for agent_core role.")
            return ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=api_key,
                temperature=temperature,
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
    )

def get_agent_llm(
    complexity: Union[ThinkingLevel, str] = ThinkingLevel.MEDIUM,
    temperature: float = 0.0,
) -> ChatOpenAI:
    """Convenience helper to obtain DeepSeek v4 Flash with the specified thinking complexity level."""
    return get_llm(role="agent_core", complexity=complexity, temperature=temperature)


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
