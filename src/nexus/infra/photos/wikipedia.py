"""Destination photos from Wikipedia and Wikimedia Commons.

``GET /api/rest_v1/page/summary/{title}`` names a place and gives its latitude;
``GET /api/rest_v1/page/media-list/{title}`` lists the photos in an article, with
captions; ``/w/api.php?action=query&prop=imageinfo`` gives each photo's size, type,
author and licence, and a ready-made copy at a standard width. No key is needed:
Wikimedia asks for a User-Agent that says who's asking and how to reach them.

Everything that comes back is someone else's text: titles and authors are cleaned,
and links must be Wikimedia's own https ones.
"""

import logging
import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from nexus.application.destination_photos import PhotoSourceError, PlaceInfo
from nexus.domain.destination_photos import (
    LOOK_WIDTH,
    PHOTO_WIDTH,
    Candidate,
    Season,
    in_season,
    plain,
)

log = logging.getLogger(__name__)

WIKI = "https://en.wikipedia.org"
USER_AGENT = "NexusPrime/1.0 (https://github.com/benjamin-wo/nexus-prime; personal finance app)"
MAX_BYTES = 4_000_000
PER_SPOT = 4  # photos from one article: its lead photo and the first seasonal ones
_HOSTS = ("wikimedia.org", "wikipedia.org")
_TYPES = {"image/jpeg", "image/png", "image/webp"}
_TITLE = re.compile(r"^[^\x00-\x1f<>\[\]{}|#]{1,200}$")


def _ours(url: str) -> bool:
    """A Wikimedia https link."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in _HOSTS)


def _page(title: str) -> str:
    return quote(title.replace(" ", "_"), safe="")


class WikipediaPhotos:
    def __init__(self, http: httpx.AsyncClient, *, base_url: str = WIKI) -> None:
        self._http = http
        self._base = base_url

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        try:
            response = await self._http.get(
                f"{self._base}{path}",
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=15,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise PhotoSourceError(type(exc).__name__) from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PhotoSourceError(f"Wikipedia answered {response.status_code} to {path}")
        try:
            return response.json()
        except ValueError as exc:
            raise PhotoSourceError("Wikipedia's answer wasn't JSON") from exc

    async def place(self, name: str) -> PlaceInfo | None:
        if not _TITLE.match(name.strip()):
            return None
        data = await self._get(f"/api/rest_v1/page/summary/{_page(name.strip())}")
        if not isinstance(data, dict) or data.get("type") != "standard":
            return None  # missing, or a disambiguation page
        title = plain(str(data.get("title") or ""), 200)
        coords = data.get("coordinates")
        latitude = None
        if isinstance(coords, dict) and isinstance(coords.get("lat"), int | float):
            lat = float(coords["lat"])
            latitude = lat if -90 <= lat <= 90 else None
        return PlaceInfo(title or name, latitude) if title or name else None

    async def candidates(self, spot: str, of: Season, latitude: float | None) -> list[Candidate]:
        if not _TITLE.match(spot.strip()):
            return []
        data = await self._get(f"/api/rest_v1/page/media-list/{_page(spot.strip())}")
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        files: dict[str, bool] = {}  # file title -> named for the season
        for item in items:
            if not isinstance(item, dict) or item.get("type") != "image":
                continue
            title = str(item.get("title") or "")
            if not title.startswith("File:") or title in files:
                continue
            caption = item.get("caption")
            text = caption.get("text", "") if isinstance(caption, dict) else ""
            seasonal = in_season(f"{title} {text}", of, latitude)
            if item.get("leadImage") or seasonal:
                files[title] = seasonal
            if len(files) >= PER_SPOT:
                break
        if not files:
            return []
        return await self._describe(files, spot)

    async def _describe(self, files: dict[str, bool], spot: str) -> list[Candidate]:
        data = await self._get(
            "/w/api.php",
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "titles": "|".join(files),
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": str(PHOTO_WIDTH),
                "iiextmetadatafilter": "LicenseShortName|Artist|LicenseUrl",
            },
        )
        pages = (data or {}).get("query", {}).get("pages", [])
        named = {t.replace("_", " "): s for t, s in files.items()}
        out = []
        for page in pages if isinstance(pages, list) else []:
            found = _candidate(page, spot, named)
            if found is not None:
                out.append(found)
        return out

    async def download(self, url: str) -> tuple[bytes, str]:
        if not _ours(url):
            raise PhotoSourceError("not a Wikimedia link")
        try:
            response = await self._http.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            raise PhotoSourceError(type(exc).__name__) from exc
        mime = response.headers.get("content-type", "").split(";")[0].strip()
        if response.status_code != 200 or mime not in _TYPES:
            raise PhotoSourceError(f"the photo answered {response.status_code} {mime}")
        if len(response.content) > MAX_BYTES:
            raise PhotoSourceError("the photo is too large")
        return response.content, mime


def _candidate(page: Any, spot: str, named: dict[str, bool]) -> Candidate | None:
    if not isinstance(page, dict):
        return None
    title = str(page.get("title") or "")
    info = page.get("imageinfo")
    if title not in named or not isinstance(info, list) or not info:
        return None
    first = info[0] if isinstance(info[0], dict) else {}
    meta = first.get("extmetadata") or {}

    def field(name: str) -> str:
        value = meta.get(name) if isinstance(meta, dict) else None
        return str(value.get("value") or "") if isinstance(value, dict) else ""

    url = str(first.get("thumburl") or first.get("url") or "")
    page_url = str(first.get("descriptionurl") or "")
    licence_url = field("LicenseUrl")
    if not _ours(url) or not _ours(page_url):
        return None
    try:
        width, height = int(first.get("width") or 0), int(first.get("height") or 0)
    except (TypeError, ValueError):
        return None
    preview = url.replace(f"/{PHOTO_WIDTH}px-", f"/{LOOK_WIDTH}px-")
    return Candidate(
        title=title,
        spot=plain(spot, 120),
        width=width,
        height=height,
        mime=str(first.get("mime") or ""),
        url=url,
        preview=preview,
        page=page_url,
        author=plain(field("Artist")),
        licence=plain(field("LicenseShortName"), 60),
        licence_url=licence_url if licence_url.startswith("https://") else None,
        seasonal=named[title],
    )
