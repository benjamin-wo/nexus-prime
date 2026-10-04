"""News and earnings dates for a stock, as the provider gave them. Pure rules.

News is someone else's text: it's cleaned and kept short, links must be plain
http(s), and anything that reads it (a model in M13c) treats it as data, never as
instructions.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

MAX_HEADLINE = 300
MAX_SUMMARY = 600
MAX_SOURCE = 80

_SPACE = re.compile(r"\s+")


def clean_text(raw: object, limit: int) -> str:
    """Printable text on one line, at most ``limit`` characters."""
    text = "".join(
        " " if unicodedata.category(c).startswith(("C", "Z")) else c for c in str(raw or "")
    )
    text = _SPACE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def safe_url(raw: object) -> str | None:
    """The link if it's an ordinary http(s) address, else None."""
    url = str(raw or "").strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc or len(url) > 2000:
        return None
    if any(c.isspace() or ord(c) < 32 for c in url):
        return None
    return url


@dataclass(frozen=True, slots=True)
class NewsItem:
    symbol: str
    external_id: str  # the provider's id, unique per stock
    headline: str
    source: str
    url: str
    summary: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class EarningsDate:
    symbol: str
    day: date
    # "before open", "after close", or None when the company hasn't said.
    timing: str | None


def _key(headline: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", headline.casefold()).strip()


def dedupe(items: list[NewsItem]) -> list[NewsItem]:
    """One item per story: the same headline from several feeds is kept once
    (the earliest), newest first."""
    seen: dict[str, NewsItem] = {}
    for item in sorted(items, key=lambda i: i.published_at):
        seen.setdefault(_key(item.headline), item)
    return sorted(seen.values(), key=lambda i: i.published_at, reverse=True)
