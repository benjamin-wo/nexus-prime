"""Links to the pages a web answer came from, as reply buttons. Pure rules.

The answer names its source in words ("per HardwareZone, 11 May"); the pages are
under it as buttons, so the text carries no web addresses (Telegram messages are plain
text, so a pasted link would be ugly there and a long one would wrap). A button's data
is ``src:<https url>``: like ``url:`` it opens a link, but the web chat draws it as a
small chip rather than a big button. At most ``MAX_SOURCES`` show, one per site, and
only for pages with a plain public https address.
"""

import re
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

from nexus.domain.news import clean_text
from nexus.domain.travel_research import safe_url

PREFIX = "src:"
ARROW = "↗"
MAX_SOURCES = 3
# Two to a row: on a phone's inline keyboard each gets half the width, which fits about
# this many characters, the arrow included, before Telegram cuts the label off.
PER_ROW = 2
MAX_LABEL = 20
_MAX_NAME = MAX_LABEL - len(ARROW) - 1

# "bbc.co.uk", "mom.gov.sg", "emb-japan.go.jp": the site is the label before these.
_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "edu", "ac", "go", "or", "ne"})
_TITLE_PARTS = re.compile(r"\s[|\-\u2013\u2014\u00b7\u2022]\s|:\s")  # | - en/em dash, dots
_WORD = re.compile(r"[\w&'.-]+")
_PLAIN = re.compile(r"[^a-z0-9]")

type Button = tuple[str, str]


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").rstrip(".").lower().removeprefix("www.")


def site(url: str) -> str:
    """The site a page is on, for telling two pages on one site apart from two sites:
    ``www.hardwarezone.com.sg`` and ``forums.hardwarezone.com.sg`` are both
    ``hardwarezone.com.sg``."""
    parts = _host(url).split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _from_domain(core: str) -> str:
    name = core.replace("-", " ").replace("_", " ")
    return name.upper() if len(name) <= 3 else name.title()


def _from_title(title: str, core: str) -> str | None:
    """The site's name as the page's title writes it ("HardwareZone Forums"), which
    has the capitals a domain lacks: a short part of the title with the domain's name in
    it, else a word that is the domain's name."""
    wanted = _PLAIN.sub("", core)
    for part in _TITLE_PARTS.split(title):
        part = part.strip()
        if part and len(part) <= _MAX_NAME and wanted in _PLAIN.sub("", part.casefold()):
            return part
    for word in _WORD.findall(title):
        if _PLAIN.sub("", word.casefold()) == wanted and word.casefold() != word:
            return str(word).strip(".-'")
    return None


def site_name(url: str, title: str) -> str:
    """A short readable name for a page's site: "HardwareZone", "XE", "Mom"."""
    core = site(url).split(".")[0]
    name = _from_title(clean_text(title, 120), core) or _from_domain(core)
    name = clean_text(name, 200)
    return name if len(name) <= _MAX_NAME else name[: _MAX_NAME - 1].rstrip() + "…"


def source_button(url: str, title: str) -> Button | None:
    """A ``src:`` button for a page, or None if its address isn't a public https one."""
    safe = safe_url(url)
    if safe is None or not _host(safe):
        return None
    return (f"{site_name(safe, title)} {ARROW}", f"{PREFIX}{safe}")


def source_buttons(pages: Iterable[tuple[str, str]]) -> list[Button]:
    """Up to ``MAX_SOURCES`` buttons for (url, title) pages, in order, one per site."""
    return _capped(b for url, title in pages if (b := source_button(url, title)))


def _capped(buttons: Iterable[Button]) -> list[Button]:
    kept: list[Button] = []
    seen: set[str] = set()
    for label, data in buttons:
        key = site(data.removeprefix(PREFIX))
        if key in seen:
            continue
        seen.add(key)
        kept.append((label, data))
        if len(kept) == MAX_SOURCES:
            break
    return kept


def in_rows(buttons: Sequence[Button]) -> list[list[Button]]:
    return [list(buttons[i : i + PER_ROW]) for i in range(0, len(buttons), PER_ROW)]


def source_rows(pages: Iterable[tuple[str, str]]) -> list[list[Button]]:
    """What the web_search tool puts under its answer."""
    return in_rows(source_buttons(pages))


def merge(rows: Iterable[Iterable[Button]]) -> list[list[Button]]:
    """A turn's button rows with the source buttons of all its searches boiled down to
    at most ``MAX_SOURCES``, one per site, the earliest first, in rows of their own at
    the end. Other buttons are left as they were."""
    others: list[list[Button]] = []
    links: list[Button] = []
    for row in rows:
        kept = [b for b in row if not b[1].startswith(PREFIX)]
        links.extend(b for b in row if b[1].startswith(PREFIX))
        if kept:
            others.append(kept)
    return [*others, *in_rows(_capped(links))]
