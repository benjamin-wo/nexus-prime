"""A trip's header photo: a famous, recognisable view of where it goes, in the season
it goes. Found once per place and season and reused for every trip there. Pure
rules, no I/O.

Photos come from Wikimedia Commons, through Wikipedia, under free licences that
allow keeping them: each is shown with its author and licence.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

# Inside the tropics the scenery barely changes with the calendar: one photo.
TROPICS = 23.5
MIN_WIDTH = 1200
MIN_RATIO = 1.2  # wide enough for a header
MAX_RATIO = 2.6
PHOTO_WIDTH = 1280  # what's kept (one of the widths Wikimedia serves ready-made)
LOOK_WIDTH = 500  # what the model looks at when choosing
MAX_CHOICES = 4  # the chosen photo and up to three runners-up a trip can switch to
RETRY_DAYS = 30  # a place with no usable photo is tried again after this long
# Licences that allow keeping and showing the photo with a credit.
_FREE = re.compile(r"\b(cc[ -]?by|cc[ -]?by-sa|cc0|public domain|pd\b|gfdl)", re.I)


class Season(StrEnum):
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"
    ANY = "any"  # the tropics, or a place whose latitude isn't known


# Words that mark a photo as taken in a season, besides the months below.
_WORDS = {
    Season.SPRING: ("spring", "blossom", "sakura", "hanami", "tulip"),
    Season.SUMMER: ("summer",),
    Season.AUTUMN: ("autumn", "fall", "foliage", "koyo", "kōyō", "momiji"),
    Season.WINTER: ("winter", "snow", "snowy", "christmas"),
}
_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
)  # fmt: skip
# Northern seasons by month (1-based); the south is shifted by six months.
_NORTH = {
    12: Season.WINTER, 1: Season.WINTER, 2: Season.WINTER,
    3: Season.SPRING, 4: Season.SPRING, 5: Season.SPRING,
    6: Season.SUMMER, 7: Season.SUMMER, 8: Season.SUMMER,
    9: Season.AUTUMN, 10: Season.AUTUMN, 11: Season.AUTUMN,
}  # fmt: skip


def first_place(destination: str) -> str:
    """The first place a trip goes: "Tokyo, Kyoto" and "Japan and Korea" give "Tokyo"
    and "Japan"; for a multi-country trip the header shows the first."""
    head = re.split(r"\s*(?:,|;|/|&|\+|→|->|\band\b|\bthen\b)\s*", destination.strip(), maxsplit=1)
    return head[0].strip() or destination.strip()


def place_key(place: str) -> str:
    """The same key for the same place however it's written: "Tōkyō" and " tokyo"."""
    plain = unicodedata.normalize("NFKD", place).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


def season(day: date, latitude: float | None) -> Season:
    """The season at the place on the day; ANY in the tropics or without a latitude."""
    if latitude is None or abs(latitude) < TROPICS:
        return Season.ANY
    month = day.month if latitude >= 0 else (day.month + 5) % 12 + 1
    return _NORTH[month]


def _months(of: Season, latitude: float) -> list[str]:
    shift = 0 if latitude >= 0 else 6
    return [m for n, m in enumerate(_MONTHS, 1) if _NORTH[(n + shift - 1) % 12 + 1] is of]


def in_season(text: str, of: Season, latitude: float | None) -> bool:
    """Whether a photo's file name or caption says it was taken in the season."""
    if of is Season.ANY or latitude is None:
        return False
    words = re.findall(r"[a-zō]+", text.lower())
    marks = set(_WORDS[of]) | set(_months(of, latitude))
    return any(w in marks for w in words)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A photo that might do, as Commons describes it."""

    title: str  # "File:Kiyomizudera_Snow.JPG"
    spot: str  # the landmark it shows ("Kiyomizu-dera")
    width: int
    height: int
    mime: str
    url: str  # a PHOTO_WIDTH-wide copy
    preview: str  # a LOOK_WIDTH-wide copy
    page: str  # its description page
    author: str  # plain text
    licence: str  # "CC BY-SA 4.0"
    licence_url: str | None
    seasonal: bool  # its name or caption names the season


def usable(c: Candidate) -> bool:
    """Wide, large, a photograph, and freely licensed."""
    if c.mime not in ("image/jpeg", "image/png", "image/webp"):
        return False
    if c.width < MIN_WIDTH or c.height <= 0:
        return False
    ratio = c.width / c.height
    return MIN_RATIO <= ratio <= MAX_RATIO and bool(_FREE.search(c.licence)) and bool(c.author)


def ranked(found: list[Candidate]) -> list[Candidate]:
    """Usable photos, seasonal ones first, each file once, in the order found."""
    seen: set[str] = set()
    out = []
    for c in sorted((c for c in found if usable(c)), key=lambda c: not c.seasonal):
        if c.title not in seen:
            seen.add(c.title)
            out.append(c)
    return out


@dataclass(frozen=True, slots=True)
class DestinationPhoto:
    """A kept photo for a place in a season, or the note that none was found."""

    id: UUID
    place_key: str
    season: Season
    latitude: float | None
    found: bool
    spot: str | None
    author: str | None
    licence: str | None
    licence_url: str | None
    page: str | None
    created_at: datetime
    rank: int = 0  # 0 is the one chosen; runners-up follow

    @property
    def credit(self) -> str | None:
        if not self.found:
            return None
        return f"Photo: {self.author}, {self.licence}, via Wikimedia Commons"


_TAG = re.compile(r"<[^>]+>")


def plain(html: str | None, limit: int = 120) -> str:
    """Commons' author field as plain text: tags and extra spaces dropped."""
    text = " ".join(_TAG.sub(" ", html or "").split())
    return text[:limit]
