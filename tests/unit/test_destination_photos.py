"""Trip header photos: which place, which season, which photos qualify, and reading
Wikipedia's and the models' answers."""

from datetime import date
from typing import Any

import httpx
import pytest

from nexus.agent.photo_picker import parse_pick, parse_spots
from nexus.application.destination_photos import PhotoSourceError
from nexus.domain.destination_photos import (
    Candidate,
    Season,
    first_place,
    in_season,
    place_key,
    plain,
    ranked,
    season,
    usable,
)
from nexus.infra.photos.wikipedia import USER_AGENT, WikipediaPhotos


@pytest.mark.parametrize(
    ("destination", "place"),
    [
        ("Tokyo", "Tokyo"),
        ("Tokyo, Kyoto", "Tokyo"),
        ("Japan and Korea", "Japan"),
        ("Seoul / Busan", "Seoul"),
        ("Paris → Rome", "Paris"),
        ("  Bali  ", "Bali"),
    ],
)
def test_the_first_place_gives_the_photo(destination: str, place: str) -> None:
    assert first_place(destination) == place


def test_one_key_however_the_place_is_written() -> None:
    assert place_key("Tōkyō") == place_key(" tokyo ") == "tokyo"
    assert place_key("Kuala  Lumpur!") == "kuala lumpur"


def test_seasons_flip_in_the_south_and_vanish_in_the_tropics() -> None:
    november = date(2026, 11, 10)
    assert season(november, 35.0) is Season.AUTUMN  # Kyoto
    assert season(november, -33.9) is Season.SPRING  # Sydney
    assert season(date(2027, 1, 5), 35.0) is Season.WINTER
    assert season(date(2027, 1, 5), -33.9) is Season.SUMMER
    assert season(november, 1.35) is Season.ANY  # Singapore
    assert season(november, None) is Season.ANY


def test_photo_names_and_captions_mark_the_season() -> None:
    assert in_season("File:Kiyomizudera_Snow.JPG", Season.WINTER, 35.0)
    assert in_season("File:Kyoto_autumn.jpg", Season.AUTUMN, 35.0)
    assert in_season("Taken in November 2019", Season.AUTUMN, 35.0)
    assert in_season("Taken in November 2019", Season.SPRING, -33.9)  # south
    assert not in_season("Taken in November 2019", Season.SPRING, 35.0)
    assert not in_season("File:Kiyomizu.jpg", Season.WINTER, 35.0)
    assert not in_season("File:Snow.jpg", Season.ANY, 1.3)


def photo(title: str = "File:A.jpg", **changes: Any) -> Candidate:
    base: dict[str, Any] = {
        "title": title,
        "spot": "Kiyomizu-dera",
        "width": 3000,
        "height": 2000,
        "mime": "image/jpeg",
        "url": "https://thumb.wikimedia.org/x/1280px-A.jpg",
        "preview": "https://thumb.wikimedia.org/x/500px-A.jpg",
        "page": "https://commons.wikimedia.org/wiki/File:A.jpg",
        "author": "A. Photographer",
        "licence": "CC BY-SA 4.0",
        "licence_url": "https://creativecommons.org/licenses/by-sa/4.0",
        "seasonal": False,
    }
    base.update(changes)
    return Candidate(**base)


def test_only_wide_large_free_photographs_qualify() -> None:
    assert usable(photo())
    assert not usable(photo(width=800, height=500))  # small
    assert not usable(photo(width=2000, height=3000))  # portrait
    assert not usable(photo(width=6000, height=1000))  # a panorama strip
    assert not usable(photo(mime="image/svg+xml"))  # a drawing or map
    assert not usable(photo(licence="Fair use"))
    assert not usable(photo(author=""))
    assert usable(photo(licence="Public domain"))
    assert usable(photo(licence="CC0"))


def test_seasonal_photos_come_first_each_once() -> None:
    lead = photo("File:Lead.jpg")
    snowy = photo("File:Snow.jpg", seasonal=True)
    small = photo("File:Small.jpg", width=400, height=300, seasonal=True)
    assert ranked([lead, snowy, small, lead]) == [snowy, lead]


def test_authors_lose_their_markup() -> None:
    assert plain('<a href="//commons.wikimedia.org/wiki/User:X">X  Y</a>') == "X Y"
    assert plain(None) == ""


def test_model_answers_are_read_carefully() -> None:
    assert parse_spots('```json\n{"spots": ["Kiyomizu-dera", "Fushimi Inari-taisha"]}```', 3) == [
        "Kiyomizu-dera",
        "Fushimi Inari-taisha",
    ]
    assert parse_spots('{"spots": ["A", "A", 3, "B", "C", "D"]}', 3) == ["A", "B", "C"]
    assert parse_spots("no idea", 3) == []
    assert parse_pick('{"pick": 2}', 4) == 2
    assert parse_pick('{"pick": null}', 4) is None
    assert parse_pick('{"pick": 7}', 4) is None
    assert parse_pick('{"pick": true}', 4) is None
    assert parse_pick("the second one", 4) is None


# --- the Wikipedia client, against canned answers ---------------------------------------

SUMMARY = {"type": "standard", "title": "Kyoto", "coordinates": {"lat": 35.0116, "lon": 135.768}}
MEDIA = {
    "items": [
        {"title": "File:Kiyomizu.jpg", "leadImage": True, "type": "image"},
        {"title": "File:Old_map.svg", "leadImage": False, "type": "image"},
        {
            "title": "File:Kiyomizu_dera_in_snow.jpg",
            "leadImage": False,
            "type": "image",
            "caption": {"text": "The main hall"},
        },
        {"title": "File:Clip.webm", "type": "video"},
    ]
}


def info(title: str, **changes: Any) -> dict[str, Any]:
    name = title.removeprefix("File:").replace(" ", "_")
    first: dict[str, Any] = {
        "width": 3000,
        "height": 2000,
        "mime": "image/jpeg",
        "thumburl": f"https://thumb.wikimedia.org/wikipedia/commons/thumb/3/3c/{name}/1280px-{name}",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
        "extmetadata": {
            "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:Ann">Ann Lee</a>'},
            "LicenseShortName": {"value": "CC BY-SA 3.0"},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/3.0"},
        },
    }
    first.update(changes)
    return {"title": title, "imageinfo": [first]}


def wiki(handler: Any) -> tuple[WikipediaPhotos, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result: httpx.Response = handler(request)
        return result

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return WikipediaPhotos(http), seen


def answers(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.startswith("/api/rest_v1/page/summary/"):
        return httpx.Response(200, json=SUMMARY)
    if path.startswith("/api/rest_v1/page/media-list/"):
        return httpx.Response(200, json=MEDIA)
    if path == "/w/api.php":
        titles = request.url.params["titles"].split("|")
        pages = [info(t.replace("_", " ")) for t in titles]
        return httpx.Response(200, json={"query": {"pages": pages}})
    return httpx.Response(200, content=b"\xff\xd8photo", headers={"content-type": "image/jpeg"})


async def test_a_place_and_its_photos_from_wikipedia() -> None:
    source, seen = wiki(answers)
    place = await source.place("Kyoto")
    assert place is not None and place.title == "Kyoto" and place.latitude == 35.0116
    found = await source.candidates("Kiyomizu-dera", Season.WINTER, 35.0)
    assert [(c.title, c.seasonal) for c in found] == [
        ("File:Kiyomizu.jpg", False),
        ("File:Kiyomizu dera in snow.jpg", True),
    ]  # the lead photo and the snowy one; not the map or the video
    first = found[0]
    assert first.author == "Ann Lee" and first.licence == "CC BY-SA 3.0"
    assert first.url.endswith("/1280px-Kiyomizu.jpg")
    assert first.preview.endswith("/500px-Kiyomizu.jpg")
    assert all(r.headers["User-Agent"] == USER_AGENT for r in seen)
    data, mime = await source.download(first.url)
    assert (data, mime) == (b"\xff\xd8photo", "image/jpeg")


async def test_only_wikimedia_links_are_fetched() -> None:
    source, seen = wiki(answers)
    with pytest.raises(PhotoSourceError):
        await source.download("https://example.com/photo.jpg")
    with pytest.raises(PhotoSourceError):
        await source.download("http://upload.wikimedia.org/photo.jpg")
    assert seen == []


async def test_links_elsewhere_in_an_answer_are_dropped() -> None:
    def elsewhere(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/w/api.php":
            page = info("File:Kiyomizu.jpg", thumburl="https://example.com/x.jpg")
            return httpx.Response(200, json={"query": {"pages": [page]}})
        return answers(request)

    source, _ = wiki(elsewhere)
    assert await source.candidates("Kiyomizu-dera", Season.ANY, None) == []


async def test_disambiguation_and_missing_pages_are_no_place() -> None:
    source, _ = wiki(lambda r: httpx.Response(200, json={"type": "disambiguation"}))
    assert await source.place("Georgia") is None
    source, _ = wiki(lambda r: httpx.Response(404, json={}))
    assert await source.place("Nowhere") is None
    assert await source.candidates("Nowhere", Season.ANY, None) == []
    assert await source.place("a|b") is None  # not a title


async def test_busy_wikipedia_is_an_error_to_retry() -> None:
    source, _ = wiki(lambda r: httpx.Response(429, text="slow down"))
    with pytest.raises(PhotoSourceError):
        await source.place("Kyoto")
    source, _ = wiki(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(PhotoSourceError):
        await source.place("Kyoto")


async def test_a_page_that_is_not_an_image_is_refused() -> None:
    source, _ = wiki(
        lambda r: httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
    )
    with pytest.raises(PhotoSourceError):
        await source.download("https://upload.wikimedia.org/x.jpg")
