"""Trip header photos: found once per place and season, shared by every trip there,
and looked for again when a trip changes where or when it goes. Wikipedia and the
models are fakes; every name here is made up or a public place."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import destination_photos as photo_cases
from nexus.application import trips as trip_cases
from nexus.domain.destination_photos import Candidate, Season
from nexus.domain.errors import InvalidInput
from nexus.domain.money import Money
from nexus.domain.packing import Outlook, PackItem
from nexus.infra.db.tables import destination_photos, jobs
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 6, 9, tzinfo=UTC)
JPEG = b"\xff\xd8 made-up photo"


def candidate(title: str, spot: str, *, seasonal: bool = False) -> Candidate:
    name = title.removeprefix("File:")
    return Candidate(
        title=title,
        spot=spot,
        width=3000,
        height=2000,
        mime="image/jpeg",
        url=f"https://thumb.wikimedia.org/x/1280px-{name}",
        preview=f"https://thumb.wikimedia.org/x/500px-{name}",
        page=f"https://commons.wikimedia.org/wiki/{title}",
        author="Ann Lee",
        licence="CC BY-SA 4.0",
        licence_url="https://creativecommons.org/licenses/by-sa/4.0",
        seasonal=seasonal,
    )


class FakeWikipedia:
    def __init__(self, latitude: float | None = 35.0) -> None:
        self.latitude = latitude
        self.asked: list[str] = []
        self.downloads: list[str] = []
        self.fail = False

    async def place(self, name: str) -> photo_cases.PlaceInfo | None:
        self.asked.append(name)
        if self.fail:
            raise photo_cases.PhotoSourceError("busy")
        return photo_cases.PlaceInfo(name.title(), self.latitude)

    async def candidates(self, spot: str, of: Season, latitude: float | None) -> list[Candidate]:
        return [
            candidate(f"File:{spot}.jpg", spot),
            candidate(f"File:{spot}_{of.value}.jpg", spot, seasonal=of is not Season.ANY),
        ]

    async def download(self, url: str) -> tuple[bytes, str]:
        self.downloads.append(url)
        return JPEG, "image/jpeg"


class FakeSpotter:
    async def spots(self, place: str, of: Season) -> list[str]:
        return [f"{place} Tower", f"{place} Temple"]


class FakeChooser:
    def __init__(self, pick: int | None = 0) -> None:
        self.pick = pick
        self.shown = 0

    async def choose(self, place: str, of: Season, previews: list[bytes]) -> int | None:
        self.shown = len(previews)
        return self.pick


def finder(source: FakeWikipedia, chooser: FakeChooser | None = None) -> photo_cases.PhotoFinder:
    return photo_cases.PhotoFinder(source, FakeSpotter(), chooser or FakeChooser())


async def test_found_once_then_shared_by_every_trip_there(uow: UowFactory) -> None:
    source, chooser = FakeWikipedia(), FakeChooser(pick=0)
    first = await photo_cases.photo_for(
        uow, finder(source, chooser), "Kyoto, Osaka", date(2026, 11, 20), now=NOW
    )
    assert first is not None and first.found
    assert first.season is Season.AUTUMN and first.place_key == "kyoto"
    # The seasonal photo of the most famous spot is shown first and chosen.
    assert first.spot == "Kyoto Tower" and chooser.shown == 4
    kept = [u for u in source.downloads if "/1280px-" in u]
    assert kept[0].endswith("1280px-Kyoto Tower_autumn.jpg")  # the chosen one first
    assert len(kept) == 4  # and three runners-up a trip can switch to
    assert first.credit == "Photo: Ann Lee, CC BY-SA 4.0, via Wikimedia Commons"

    again = await photo_cases.photo_for(
        uow, finder(source), "kyoto", date(2026, 10, 1), now=NOW + timedelta(days=3)
    )
    assert again is not None and again.id == first.id
    assert source.asked == ["Kyoto"]  # the second trip didn't ask Wikipedia

    async with uow() as tx:
        assert await tx.trips.photo_file(first.id) == (JPEG, "image/jpeg")


async def test_another_season_is_looked_for_but_falls_back(uow: UowFactory) -> None:
    source = FakeWikipedia()
    autumn = await photo_cases.photo_for(uow, finder(source), "Kyoto", date(2026, 11, 1), now=NOW)
    nothing = FakeChooser(pick=None)
    winter = await photo_cases.photo_for(
        uow, finder(source, nothing), "Kyoto", date(2027, 1, 10), now=NOW
    )
    # Nothing suited winter: the autumn photo stands in, and winter isn't searched
    # again until the note is old.
    assert autumn is not None and winter is not None and winter.id == autumn.id
    await photo_cases.photo_for(uow, finder(source), "Kyoto", date(2027, 1, 12), now=NOW)
    assert len(source.asked) == 2
    later = NOW + timedelta(days=31)
    found = await photo_cases.photo_for(uow, finder(source), "Kyoto", date(2027, 1, 12), now=later)
    assert found is not None and found.season is Season.WINTER
    async with uow() as tx:
        seasons = {p.season: p.found for p in await tx.trips.place_photos("kyoto")}
    assert seasons == {Season.AUTUMN: True, Season.WINTER: True}


async def test_the_tropics_have_one_photo(uow: UowFactory) -> None:
    source = FakeWikipedia(latitude=1.35)
    june = await photo_cases.photo_for(uow, finder(source), "Singapore", date(2027, 6, 1), now=NOW)
    december = await photo_cases.photo_for(
        uow, finder(source), "Singapore", date(2027, 12, 1), now=NOW
    )
    assert june is not None and december is not None
    assert june.season is Season.ANY and december.id == june.id


async def test_without_models_the_lead_photo_is_taken(uow: UowFactory) -> None:
    source = FakeWikipedia()
    found = await photo_cases.photo_for(
        uow, photo_cases.PhotoFinder(source), "Kyoto", date(2026, 11, 1), now=NOW
    )
    assert found is not None and found.spot == "Kyoto"
    assert source.downloads[0] == "https://thumb.wikimedia.org/x/1280px-Kyoto_autumn.jpg"


async def test_the_sweep_gives_trips_photos_and_edits_look_again(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    draft = trip_cases.TripDraft(
        destination="Kyoto",
        start=date(2026, 11, 10),
        end=date(2026, 11, 14),
        currency="JPY",
        budget=Money.of("3000", "SGD"),
    )
    trip = await trip_cases.create_trip(uow(), user, draft, now=NOW)
    async with engine.connect() as db:
        queued = await db.execute(select(jobs.c.kind).where(jobs.c.kind == photo_cases.PHOTOS_JOB))
        assert queued.all()  # a search was queued with the new trip

    source = FakeWikipedia()
    assert await photo_cases.sweep(uow, finder(source), now=NOW) == 1
    got = await trip_cases.get_trip(uow(), user.id, trip.id)
    assert got.photo_id is not None
    assert await photo_cases.sweep(uow, finder(source), now=NOW) == 0  # nothing left

    # Changing only the budget keeps the photo; going somewhere else looks again.
    budget = replace(trip_cases.draft_of(got), budget=Money.of("3500", "SGD"))
    kept = await trip_cases.update_trip(uow(), user, trip.id, budget, now=NOW)
    assert kept.photo_id == got.photo_id
    moved = replace(trip_cases.draft_of(got), destination="Sapporo")
    await trip_cases.update_trip(uow(), user, trip.id, moved, now=NOW)
    assert (await trip_cases.get_trip(uow(), user.id, trip.id)).photo_id is None
    assert await photo_cases.sweep(uow, finder(source), now=NOW) == 1
    after = await trip_cases.get_trip(uow(), user.id, trip.id)
    assert after.photo_id is not None and after.photo_id != got.photo_id


async def test_a_busy_wikipedia_waits_and_tries_again(uow: UowFactory, engine: AsyncEngine) -> None:
    user = await person(uow)
    draft = trip_cases.TripDraft(
        destination="Kyoto", start=date(2026, 11, 10), end=date(2026, 11, 14), currency="JPY"
    )
    trip = await trip_cases.create_trip(uow(), user, draft, now=NOW)
    source = FakeWikipedia()
    source.fail = True
    assert await photo_cases.sweep(uow, finder(source), now=NOW) == 1
    assert (await trip_cases.get_trip(uow(), user.id, trip.id)).photo_id is None
    async with engine.connect() as db:
        assert (await db.execute(select(destination_photos.c.id))).all() == []
    source.fail = False
    assert await photo_cases.sweep(uow, finder(source), now=NOW + timedelta(hours=1)) == 0
    assert await photo_cases.sweep(uow, finder(source), now=NOW + timedelta(hours=7)) == 1
    assert (await trip_cases.get_trip(uow(), user.id, trip.id)).photo_id is not None


async def test_a_trip_switches_photos_or_shows_none(uow: UowFactory) -> None:
    user = await person(uow)
    draft = trip_cases.TripDraft(
        destination="Kyoto", start=date(2026, 11, 10), end=date(2026, 11, 14), currency="JPY"
    )
    trip = await trip_cases.create_trip(uow(), user, draft, now=NOW)
    await photo_cases.sweep(uow, finder(FakeWikipedia(), FakeChooser(pick=2)), now=NOW)
    first = (await trip_cases.get_trip(uow(), user.id, trip.id)).photo_id
    assert first is not None
    async with uow() as tx:
        ranks = {p.id: p.rank for p in await tx.trips.place_photos("kyoto")}
    assert ranks[first] == 0 and sorted(ranks.values()) == [0, 1, 2, 3]

    seen: list[UUID | None] = [first]
    for _ in range(4):
        moved = await trip_cases.choose_photo(
            uow(), user, trip.id, trip_cases.PhotoChoice.NEXT, now=NOW
        )
        seen.append(moved.photo_id)
    assert [ranks[s] for s in seen if s] == [0, 1, 2, 3, 0]  # round and back to the first

    off = await trip_cases.choose_photo(uow(), user, trip.id, trip_cases.PhotoChoice.OFF, now=NOW)
    assert off.photo_off and off.photo_id == first
    stored = await trip_cases.get_trip(uow(), user.id, trip.id)
    assert stored.photo_off and stored.photo_id == first
    on = await trip_cases.choose_photo(uow(), user, trip.id, trip_cases.PhotoChoice.ON, now=NOW)
    assert not on.photo_off and on.photo_id == first


async def test_no_photo_to_switch_to_says_so(uow: UowFactory) -> None:
    user = await person(uow)
    draft = trip_cases.TripDraft(
        destination="Nowhere", start=date(2026, 11, 10), end=date(2026, 11, 14), currency="JPY"
    )
    trip = await trip_cases.create_trip(uow(), user, draft, now=NOW)
    with pytest.raises(InvalidInput):
        await trip_cases.choose_photo(uow(), user, trip.id, trip_cases.PhotoChoice.NEXT, now=NOW)


async def test_the_packing_list_is_kept_and_suggested(uow: UowFactory) -> None:
    user = await person(uow)  # home currency SGD
    draft = trip_cases.TripDraft(
        destination="Sapporo", start=date(2027, 1, 10), end=date(2027, 1, 14), currency="JPY"
    )
    trip = await trip_cases.create_trip(uow(), user, draft, now=NOW)
    items = [
        PackItem("Passport X1234567", done=True),
        PackItem("  thermal   socks "),
        PackItem("THERMAL SOCKS"),
        PackItem("   "),
    ]
    kept = await trip_cases.set_packing(uow(), user, trip.id, items, now=NOW)
    assert [(i.text, i.done) for i in kept.packing] == [
        ("Passport •••", True),  # the number isn't kept
        ("thermal socks", False),
    ]
    cold = Outlook(low=-4.0, high=2.0, rain=False)
    suggested = await trip_cases.suggest_packing(
        uow(), user, trip.id, latitude=43.06, outlook=cold, now=NOW
    )
    texts = [i.text for i in suggested.packing]
    assert texts[:2] == ["Passport •••", "thermal socks"]  # what was there stays first
    assert "Travel adapter" in texts and "Warm jacket" in texts and "Gloves and a hat" in texts
    assert "Sunscreen" not in texts and "Passport" not in texts  # it's there as "Passport •••"
    again = await trip_cases.suggest_packing(
        uow(), user, trip.id, latitude=43.06, outlook=cold, now=NOW
    )
    assert len(again.packing) == len(suggested.packing)  # nothing added twice
    edited = await trip_cases.update_trip(
        uow(), user, trip.id, replace(trip_cases.draft_of(again), notes="Ski day"), now=NOW
    )
    assert edited.packing == again.packing  # editing the trip keeps the list
    with pytest.raises(InvalidInput):
        await trip_cases.set_packing(
            uow(), user, trip.id, [PackItem(f"thing {n}") for n in range(81)], now=NOW
        )


async def test_a_trip_with_no_photo_is_not_searched(uow: UowFactory) -> None:
    user = await person(uow)
    draft = trip_cases.TripDraft(
        destination="Kyoto", start=date(2026, 11, 10), end=date(2026, 11, 14), currency="JPY"
    )
    trip = await trip_cases.create_trip(uow(), user, draft, now=NOW)
    with pytest.raises(InvalidInput):  # nothing to switch to yet
        await trip_cases.choose_photo(uow(), user, trip.id, trip_cases.PhotoChoice.NEXT, now=NOW)
    await trip_cases.choose_photo(uow(), user, trip.id, trip_cases.PhotoChoice.OFF, now=NOW)
    assert await photo_cases.sweep(uow, finder(FakeWikipedia()), now=NOW) == 0
