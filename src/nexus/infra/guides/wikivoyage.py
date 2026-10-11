"""A destination's travel guide from Wikivoyage: its See, Do, Eat, Drink and Buy
sections, as plain text.

``/w/api.php?action=query&prop=extracts&explaintext=1&exsectionformat=wiki`` gives a
page's text with "== Eat ==" headings. No key is needed; Wikimedia asks for a
User-Agent that says who's asking. Answers are kept in memory for a day. The text
is CC BY-SA, credited where it's shown with a link to the page. It's someone else's
words: the caller treats it as data.
"""

import logging
import re
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from nexus.application.clock import utcnow
from nexus.application.ideas import GuidePage

log = logging.getLogger(__name__)

API = "https://en.wikivoyage.org/w/api.php"
SITE = "https://en.wikivoyage.org/wiki/"
USER_AGENT = "NexusPrime/1.0 (https://github.com/benjamin-wo/nexus-prime; personal finance app)"
SECTIONS = ("See", "Do", "Eat", "Drink", "Buy")
MAX_TEXT = 20_000
KEEP_FOR = timedelta(days=1)
KEEP_MISSING_FOR = timedelta(hours=1)
CACHE_SIZE = 200

_HEADING = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$")
_TITLE = re.compile(r"^[^\x00-\x1f<>\[\]{}|#]{1,100}$")


def sections(extract: str) -> str:
    """The guide's See, Do, Eat, Drink and Buy sections, each under its own heading."""
    kept: list[str] = []
    current: str | None = None
    for line in extract.splitlines():
        heading = _HEADING.match(line.strip())
        if heading and len(heading.group(1)) == 2:
            name = heading.group(2).strip()
            current = name if name in SECTIONS else None
            if current:
                kept.append(f"\n## {current}")
            continue
        if current and line.strip():
            if heading:  # a sub-heading inside a kept section
                kept.append(f"### {heading.group(2).strip()}")
            else:
                kept.append(line.strip())
    return "\n".join(kept).strip()[:MAX_TEXT]


class Wikivoyage:
    def __init__(self, http: httpx.AsyncClient, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._http = http
        self._clock = clock
        self._cache: OrderedDict[str, tuple[datetime, GuidePage | None]] = OrderedDict()

    async def guide(self, place: str) -> GuidePage | None:
        # "Tokyo, Kyoto" is guided by its first place.
        title = place.split(",")[0].strip()
        if not _TITLE.fullmatch(title):
            return None
        key = title.casefold()
        hit = self._cache.get(key)
        now = self._clock()
        if hit is not None:
            at, page = hit
            if now - at < (KEEP_FOR if page else KEEP_MISSING_FOR):
                return page
        page = await self._fetch(title)
        self._cache[key] = (now, page)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return page

    async def _fetch(self, title: str) -> GuidePage | None:
        try:
            response = await self._http.get(
                API,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "explaintext": "1",
                    "exsectionformat": "wiki",
                    "titles": title,
                    "redirects": "1",
                    "format": "json",
                    "formatversion": "2",
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=8.0,
            )
        except httpx.HTTPError as exc:
            log.info("Wikivoyage didn't answer: %s", type(exc).__name__)
            return None
        if response.status_code != 200:
            log.info("Wikivoyage answered HTTP %d", response.status_code)
            return None
        try:
            data: dict[str, Any] = response.json()
            page = data["query"]["pages"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            log.info("Wikivoyage's answer wasn't a page")
            return None
        if (
            not isinstance(page, dict)
            or page.get("missing")
            or not isinstance(page.get("title"), str)
        ):
            return None
        text = sections(str(page.get("extract") or ""))
        if not text:
            return None
        name = page["title"]
        if not _TITLE.fullmatch(name):
            return None
        return GuidePage(f"{SITE}{name.replace(' ', '_')}", f"Wikivoyage: {name}", text)
