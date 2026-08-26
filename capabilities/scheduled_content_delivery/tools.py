"""Scheduled content delivery: build and push recurring briefings (news + markets)."""

from __future__ import annotations

from core.config import settings
from core.llm import ThinkingLevel, get_agent_llm


async def _search(query: str) -> str:
    from capabilities.general.tools import search_web

    try:
        return await search_web.ainvoke({"query": query})
    except Exception as exc:  # noqa: BLE001
        return f"[search failed: {exc}]"


def _fallback_briefing(news: str, markets: str) -> str:
    """Deterministic formatting when no LLM key is available."""
    news_lines = [ln for ln in news.splitlines() if ln.strip()][:6]
    market_lines = [ln for ln in markets.splitlines() if ln.strip()][:6]
    if not news_lines and not market_lines:
        return "No briefing content could be fetched right now."
    parts = []
    if news_lines:
        parts.append("🌍 *Top Global News*\n" + "\n".join(f"• {ln}" for ln in news_lines))
    if market_lines:
        parts.append("📈 *Stock Market*\n" + "\n".join(f"• {ln}" for ln in market_lines))
    return "\n\n".join(parts)


async def build_daily_briefing() -> str:
    """Fetch today's top global news and stock market headlines and format a
    Telegram-ready morning briefing."""
    news = await _search("top global news headlines today")
    markets = await _search("stock market news today")

    fallback = _fallback_briefing(news, markets)

    if not settings.has_llm_key:
        return fallback

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.4)
        ai_message = await llm.ainvoke(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Nexus Prime. Build a concise morning briefing from "
                        "the raw web-search results below. Two sections: 🌍 Top Global News "
                        "and 📈 Stock Market. 3-5 bullet lines per section, bold headers, "
                        "Telegram-friendly. Never invent facts or headlines that are not "
                        "present in the provided text."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Global news:\n{news[:3000]}\n\nStock market:\n{markets[:3000]}",
                },
            ]
        )
        content = str(getattr(ai_message, "content", "") or "").strip()
        return content or fallback
    except Exception as exc:  # noqa: BLE001
        print(f"[BRIEFING] summary LLM failed, using fallback: {exc}")
        return fallback