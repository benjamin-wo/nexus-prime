"""Food logging against a real database: loading the foods, meals and their snapshots, consent,
isolation between users, the intake provider that feeds the energy estimate, the web API
(numbers-free mode included) and the helpers the agent tools use. Every name is made up."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import energy as energy_cases
from nexus.application import food_entry as entry_cases
from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application import health_consent as consent_cases
from nexus.application import nutrition as nutrition_cases
from nexus.application.nutrition import ItemInput
from nexus.domain.energy import SafeTargets, TargetProposal
from nexus.domain.errors import ConsentRequired, InvalidInput, NotFound
from nexus.domain.health import ActivityLevel, ConsentScope, SampleKind
from nexus.domain.ledger import MenuSection, UserId
from nexus.domain.nutrition import (
    EN_DASH,
    Cooking,
    EntrySource,
    EstimateKind,
    Food,
    FoodSource,
    MealSlot,
    Nutrients,
    Portion,
)
from nexus.infra.db.tables import foods, meal_items
from nexus.infra.foods import load_foods
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, make_user
from tests.integration.test_health_energy import ready, weigh_in
from tests.integration.test_web_api import MEMBER, OWNER, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world

D = Decimal
RICE = "usda:168878"  # Rice, white, long-grain, regular, enriched, cooked: 130 kcal per 100 g
CHICKEN = "usda:171477"  # chicken breast, meat only, cooked, roasted: 165 kcal, 3.57 g fat

FEAST = Food(  # a made-up food that is exactly 100 kcal per 100 g, so day totals are easy
    "custom:feast",
    FoodSource.CUSTOM,
    "Test Feast",
    ("banquet",),
    Nutrients(D(100), D(10), D(10), D(2), None),
    (Portion("1 plate", D(400)),),
)


async def stocked(uow: UowFactory) -> None:
    await nutrition_cases.sync_foods(uow(), [*load_foods(), FEAST])


def item(
    food_id: str, grams: str, kind: EstimateKind = EstimateKind.WEIGHED, **kw: object
) -> ItemInput:
    return ItemInput(food_id, D(grams), f"{grams} g", kind, **kw)  # type: ignore[arg-type]


# --- the food database ----------------------------------------------------------------------


def test_the_bundled_files_load_and_are_sane() -> None:
    loaded = load_foods()
    assert len(loaded) > 7000
    assert {f.source for f in loaded} == {FoodSource.USDA}
    by_id = {f.id: f for f in loaded}
    assert by_id[RICE].per_100g.kcal == D(130) and by_id[CHICKEN].per_100g.fat_g == D("3.57")
    assert all(f.per_100g.kcal >= 0 and f.id.startswith("usda:") for f in loaded)


async def test_sync_is_idempotent_updates_changes_and_keeps_removed_foods(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    catalogue = load_foods()
    assert await nutrition_cases.sync_foods(uow(), catalogue) == len(catalogue)
    assert await nutrition_cases.sync_foods(uow(), catalogue) == 0
    async with engine.begin() as connection:
        await connection.execute(update(foods).where(foods.c.id == RICE).values(kcal_100g=1))
    assert await nutrition_cases.sync_foods(uow(), catalogue[1:]) == 1
    assert (await nutrition_cases.food(uow(), RICE)).per_100g.kcal == D(130)
    assert await nutrition_cases.sync_foods(uow(), catalogue[:5]) == 0
    async with engine.connect() as connection:
        count = (await connection.execute(select(func.count()).select_from(foods))).scalar_one()
    assert count == len(catalogue)


async def test_the_round_trip_keeps_every_field(uow: UowFactory) -> None:
    catalogue = [*load_foods(), FEAST]
    await nutrition_cases.sync_foods(uow(), catalogue)
    for wanted in (catalogue[0], catalogue[3000], FEAST):
        assert await nutrition_cases.food(uow(), wanted.id) == wanted
    with pytest.raises(NotFound):
        await nutrition_cases.food(uow(), "usda:0")


async def test_find_foods_ranks_in_code(uow: UowFactory) -> None:
    await stocked(uow)
    found = await nutrition_cases.find_foods(uow(), "rice white long-grain cooked", limit=5)
    assert found and all("cooked" in f.name.casefold() for f in found[:3])
    assert (await nutrition_cases.find_foods(uow(), "banquet"))[0].id == "custom:feast"
    assert await nutrition_cases.find_foods(uow(), "zzzz nothing") == []
    assert len(await nutrition_cases.find_foods(uow(), "chicken", limit=7)) == 7


# --- meals ----------------------------------------------------------------------------------


async def agree(uow: UowFactory, user: UserId) -> None:
    await gym_cases.give_consent(uow(), user, now=NOW)


async def test_a_meal_needs_consent_computes_in_code_and_keeps_a_snapshot(
    uow: UowFactory, alice: UserId
) -> None:
    await stocked(uow)
    items = [item(RICE, "200"), item(CHICKEN, "100", EstimateKind.PORTION, cooking=Cooking.FRIED)]
    with pytest.raises(ConsentRequired):
        await nutrition_cases.log_meal(
            uow(), alice, items, MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW
        )
    await agree(uow, alice)
    async with uow() as u:
        assert (await u.ledger.get_user(alice)).show_health is not True  # type: ignore[union-attr]
    made = await nutrition_cases.log_meal(
        uow(), alice, items, MealSlot.LUNCH, None, EntrySource.VOICE, note="  at work ", now=NOW
    )
    assert made.eaten_at == NOW and made.note == "at work" and made.source is EntrySource.VOICE
    assert made.totals.point.kcal == D("425.000")  # 260 + 165
    assert made.totals.high.kcal > made.totals.point.kcal > made.totals.low.kcal
    stored = await nutrition_cases.meal(uow(), alice, made.id)
    assert stored.items[0].nutrients.kcal == D("260.000") and stored.totals == made.totals
    assert stored.items[1].cooking is Cooking.FRIED and stored.items[1].kind is EstimateKind.PORTION
    async with uow() as u:
        user = await u.ledger.get_user(alice)
        assert user is not None and user.show_health is True
        assert MenuSection.HEALTH in {
            s for s in MenuSection if getattr(user, f"show_{s.value}", None)
        }

    # Later updates to the shared table never rewrite what was eaten.
    changed = Food(
        "usda:168878", FoodSource.USDA, "Rice", (), Nutrients(D(999), D(1), D(1), D(1), None), ()
    )
    await nutrition_cases.sync_foods(uow(), [changed])
    again = await nutrition_cases.meal(uow(), alice, made.id)
    assert again.totals.point.kcal == D("425.000")


async def test_bad_meals_are_refused(uow: UowFactory, alice: UserId) -> None:
    await stocked(uow)
    await agree(uow, alice)
    log = nutrition_cases.log_meal
    with pytest.raises(InvalidInput, match="at least one"):
        await log(uow(), alice, [], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW)
    with pytest.raises(InvalidInput, match="no such food"):
        await log(
            uow(), alice, [item("usda:0", "5")], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW
        )
    with pytest.raises(InvalidInput, match="grams"):
        await log(uow(), alice, [item(RICE, "0")], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW)
    with pytest.raises(InvalidInput, match="future"):
        await log(
            uow(), alice, [item(RICE, "5")], MealSlot.LUNCH, NOW + timedelta(days=3),
            EntrySource.CHAT, now=NOW,
        )  # fmt: skip
    with pytest.raises(InvalidInput, match="at most"):
        await log(
            uow(), alice, [item(RICE, "5")], MealSlot.LUNCH, None, EntrySource.CHAT,
            note="x" * 501, now=NOW,
        )  # fmt: skip


async def test_edit_and_delete(uow: UowFactory, alice: UserId, engine: AsyncEngine) -> None:
    await stocked(uow)
    await agree(uow, alice)
    made = await nutrition_cases.log_meal(
        uow(), alice, [item(RICE, "100")], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW
    )
    later = NOW + timedelta(minutes=5)
    edited = await nutrition_cases.edit_meal(
        uow(),
        alice,
        made.id,
        items=[item(CHICKEN, "200")],
        meal=MealSlot.DINNER,
        note="x",
        now=later,
    )
    assert edited.meal is MealSlot.DINNER and edited.updated_at == later
    assert edited.created_at == NOW and edited.totals.point.kcal == D("330.000")
    kept = await nutrition_cases.edit_meal(uow(), alice, made.id, meal=MealSlot.SNACK, now=later)
    assert kept.items == edited.items and kept.note == "x"
    cleared = await nutrition_cases.edit_meal(uow(), alice, made.id, clear_note=True, now=later)
    assert cleared.note is None
    with pytest.raises(InvalidInput, match="nothing"):
        await nutrition_cases.edit_meal(uow(), alice, made.id, now=later)
    with pytest.raises(NotFound):
        await nutrition_cases.edit_meal(uow(), alice, uuid4(), meal=MealSlot.LUNCH, now=later)

    # Withdrawing consent blocks writes but never a delete.
    await gym_cases.withdraw_consent(uow(), alice)
    with pytest.raises(ConsentRequired):
        await nutrition_cases.edit_meal(uow(), alice, made.id, meal=MealSlot.LUNCH, now=later)
    await nutrition_cases.delete_meal(uow(), alice, made.id)
    with pytest.raises(NotFound):
        await nutrition_cases.meal(uow(), alice, made.id)
    with pytest.raises(NotFound):
        await nutrition_cases.delete_meal(uow(), alice, made.id)
    async with engine.connect() as connection:  # the items went with the meal
        count = select(func.count()).select_from(meal_items)
        assert (await connection.execute(count)).scalar_one() == 0


async def test_meals_by_local_day_and_range(uow: UowFactory, alice: UserId) -> None:
    await stocked(uow)
    await agree(uow, alice)
    for days_ago in (0, 1, 1, 3):
        await nutrition_cases.log_meal(
            uow(), alice, [item(RICE, "100")], MealSlot.SNACK, NOW - timedelta(days=days_ago),
            EntrySource.MANUAL, now=NOW,
        )  # fmt: skip
    today = NOW.date()
    assert len(await nutrition_cases.meals(uow(), alice, now=NOW)) == 1
    assert (
        len(await nutrition_cases.meals(uow(), alice, day=today - timedelta(days=1), now=NOW)) == 2
    )
    both = await nutrition_cases.meals(
        uow(), alice, first=today - timedelta(days=3), last=today, now=NOW
    )
    assert len(both) == 4 and both == sorted(both, key=lambda e: e.eaten_at)
    with pytest.raises(InvalidInput):
        await nutrition_cases.meals(
            uow(), alice, first=today, last=today - timedelta(days=1), now=NOW
        )


async def test_users_never_see_each_others_meals(uow: UowFactory, alice: UserId) -> None:
    await stocked(uow)
    bob = await make_user(uow, 2002)
    await agree(uow, alice)
    await agree(uow, bob)
    made = await nutrition_cases.log_meal(
        uow(), alice, [item(RICE, "100")], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW
    )
    assert await nutrition_cases.meals(uow(), bob, now=NOW) == []
    with pytest.raises(NotFound):
        await nutrition_cases.meal(uow(), bob, made.id)
    with pytest.raises(NotFound):
        await nutrition_cases.delete_meal(uow(), bob, made.id)
    with pytest.raises(NotFound):
        await nutrition_cases.edit_meal(uow(), bob, made.id, meal=MealSlot.DINNER, now=NOW)
    assert (await nutrition_cases.day_summary(uow(), bob, now=NOW)).entries == []
    assert len((await nutrition_cases.day_summary(uow(), alice, now=NOW)).entries) == 1


async def test_row_security_stops_a_meal_item_pointing_at_someone_elses_entry(
    uow: UowFactory, alice: UserId, engine: AsyncEngine
) -> None:
    await stocked(uow)
    bob = await make_user(uow, 2002)
    await agree(uow, alice)
    made = await nutrition_cases.log_meal(
        uow(), alice, [item(RICE, "100")], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW
    )
    async with engine.begin() as connection:
        from sqlalchemy import text

        await connection.execute(
            text("SELECT set_config('app.user_id', :u, true)"), {"u": str(bob)}
        )
        seen = (await connection.execute(select(func.count()).select_from(meal_items))).scalar_one()
        assert seen == 0
        from sqlalchemy.exc import DBAPIError

        with pytest.raises(DBAPIError):
            await connection.execute(
                meal_items.insert().values(
                    id=uuid4(),
                    user_id=bob,
                    entry_id=made.id,
                    position=0,
                    food_id=RICE,
                    grams=1,
                    portion_label="x",
                    estimate_kind="weighed",
                    kcal=1,
                    protein_g=1,
                    carbs_g=1,
                    fat_g=1,
                )
            )


# --- the day, targets, and energy -----------------------------------------------------------


async def test_day_summary_totals_and_remaining(uow: UowFactory, alice: UserId) -> None:
    from nexus.domain.energy import Targets

    await stocked(uow)
    await agree(uow, alice)
    await nutrition_cases.log_meal(
        uow(), alice, [item("custom:feast", "500")], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW
    )
    targets = Targets(D(2000), D(120), D(30), (D(1900), D(2100)), D(0), ())
    today = await nutrition_cases.day_summary(uow(), alice, targets=targets, now=NOW)
    assert today.totals.point.kcal == D("500.000") and today.hidden is False
    assert today.remaining is not None and today.remaining.kcal == D("1500.000")
    assert today.remaining.protein_g == D("70.000") and today.remaining.fibre_g == D(30)
    other = await nutrition_cases.day_summary(
        uow(), alice, NOW.date() - timedelta(days=1), targets=targets, now=NOW
    )
    assert other.entries == [] and other.remaining is None and other.totals.point.kcal == 0


async def log_days(uow: UowFactory, user: UserId, days: range, kcal: int) -> None:
    for days_ago in days:
        await nutrition_cases.log_meal(
            uow(), user, [item("custom:feast", str(kcal))], MealSlot.DINNER,
            NOW - timedelta(days=days_ago), EntrySource.MANUAL, now=NOW,
        )  # fmt: skip


async def test_the_intake_provider_counts_only_days_the_user_logged(
    uow: UowFactory, alice: UserId
) -> None:
    await stocked(uow)
    await agree(uow, alice)
    await log_days(uow, alice, range(1, 4), 1800)
    await log_days(uow, alice, range(2, 3), 200)  # a second meal on one of the days
    got = await nutrition_cases.intake_provider(uow)(
        alice, NOW.date() - timedelta(days=10), NOW.date()
    )
    assert got == {
        NOW.date() - timedelta(days=1): D("1800.000"),
        NOW.date() - timedelta(days=2): D("2000.000"),
        NOW.date() - timedelta(days=3): D("1800.000"),
    }  # nothing for the unlogged days, and nothing for today
    narrow = await nutrition_cases.intake_provider(uow)(
        alice, NOW.date() - timedelta(days=2), NOW.date() - timedelta(days=2)
    )
    assert list(narrow) == [NOW.date() - timedelta(days=2)]
    assert (
        await nutrition_cases.intake_provider(uow)(
            UserId(uuid4()), NOW.date() - timedelta(days=9), NOW.date()
        )
        == {}
    )


async def test_logged_food_feeds_the_adaptive_expenditure(uow: UowFactory, alice: UserId) -> None:
    await stocked(uow)
    await agree(uow, alice)
    for days_ago in range(28, 0, -1):
        await health_cases.log_sample(
            uow(),
            alice,
            SampleKind.WEIGHT,
            D("80"),
            start_at=NOW - timedelta(days=days_ago),
            now=NOW,
        )
    await health_cases.save_profile(
        uow(), alice, birth_year=1990, height_cm=D(180),
        activity_level=ActivityLevel.MODERATE, now=NOW,
    )  # fmt: skip
    provider = nutrition_cases.intake_provider(uow)

    none = await energy_cases.expenditure(uow(), alice, now=NOW, intake_provider=provider)
    assert none.basis == energy_cases.BASIS_PROFILE  # nothing logged yet

    await log_days(uow, alice, range(1, 15), 2600)
    got = await energy_cases.expenditure(uow(), alice, now=NOW, intake_provider=provider)
    assert got.basis == energy_cases.BASIS_LOGGED and got.estimate is not None
    assert got.estimate.paused_reason is None and got.estimate.days_used == 14
    # A steady weight on 2600 kcal a day: the estimate moves toward 2600.
    assert abs(got.estimate.kcal - D(2600)) < abs(none.estimate.kcal - D(2600))  # type: ignore[union-attr]

    def safety(p: TargetProposal) -> SafeTargets:
        return SafeTargets(p.kcal, p.rate_pct_per_week)

    t = await energy_cases.current_targets(
        uow(), alice, now=NOW, intake_provider=provider, apply_safety=safety
    )
    assert t.energy.basis == energy_cases.BASIS_LOGGED


# --- the agent tools' helpers ---------------------------------------------------------------


async def test_resolve_picks_matches_portions_and_asks_when_unsure(
    uow: UowFactory, alice: UserId
) -> None:
    await stocked(uow)
    req = entry_cases.FoodRequest
    # An exact alias, a database portion, and a model-estimated weight.
    r = await entry_cases.resolve(
        uow,
        [
            req("banquet", portion="half a plate"),
            req(RICE, grams=D(150)),
            req(
                "Rice, white, long-grain, regular, enriched, cooked",
                portion="1 plate",
                grams=D(300),
            ),
            req("Test Feast", grams=D(350), estimated=True, modifiers=("less rice",)),
        ],
    )
    a, b, c, d = r.inputs
    assert (a.food_id, a.grams, a.kind) == ("custom:feast", D(200), EstimateKind.PORTION)
    assert (b.grams, b.kind, b.label) == (D(150), EstimateKind.WEIGHED, "150 g")
    assert (c.grams, c.kind, c.label) == (D(300), EstimateKind.ESTIMATED, "1 plate")
    assert d.kind is EstimateKind.ESTIMATED and d.extra_uncertainty > 0 and d.note == "less rice"
    assert r.notes == ["Test Feast: less rice"]

    with pytest.raises(entry_cases.NeedsAnswer, match="no food matching"):
        await entry_cases.resolve(uow, [req("zzzz qqqq", grams=D(5))])
    with pytest.raises(entry_cases.NeedsAnswer) as ambiguous:
        await entry_cases.resolve(uow, [req("chicken", grams=D(100))])
    text = str(ambiguous.value)
    assert text.startswith("Error:") and "several foods" in text and text.count("(id usda:") == 5
    with pytest.raises(entry_cases.NeedsAnswer, match="How much of Test Feast"):
        await entry_cases.resolve(uow, [req("banquet")])
    with pytest.raises(entry_cases.NeedsAnswer, match="not a portion I know") as unknown:
        await entry_cases.resolve(uow, [req("banquet", portion="a bucket")])
    assert "1 plate" in str(unknown.value)


async def test_confirm_text_is_built_from_code_and_hides_numbers_when_asked(
    uow: UowFactory, alice: UserId
) -> None:
    await stocked(uow)
    r = await entry_cases.resolve(
        uow,
        [
            entry_cases.FoodRequest(
                "banquet", portion="a big bowl", grams=D(350), modifiers=("extra",)
            )
        ],
    )
    text = entry_cases.confirm_text(r, MealSlot.LUNCH, hidden=False)
    # 350 g of a 100 kcal food is 350 kcal; an estimate with a modifier is +-45%: 192.5 to 507.5.
    assert text == (
        f"Log lunch: test feast (a big bowl, about 190{EN_DASH}510 kcal)? I estimated the portion. "
        "Noted: Test Feast: extra (the range is wider for it)."
    )
    assert "I estimated the portion." in text
    quiet = entry_cases.confirm_text(r, MealSlot.LUNCH, hidden=True)
    assert "kcal" not in quiet and not any(ch.isdigit() for ch in quiet.replace("a big bowl", ""))
    two = await entry_cases.resolve(
        uow,
        [
            entry_cases.FoodRequest(RICE, grams=D(100)),
            entry_cases.FoodRequest("banquet", grams=D(100)),
        ],
    )
    assert "in all" in entry_cases.confirm_text(two, MealSlot.SNACK, hidden=False)


async def test_the_ai_gate_and_the_day_text(uow: UowFactory, alice: UserId) -> None:
    await stocked(uow)
    assert await entry_cases.ai_may_read(uow(), alice) is False
    await agree(uow, alice)
    assert await entry_cases.ai_may_read(uow(), alice) is False  # the master consent isn't enough
    await consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    assert await entry_cases.ai_may_read(uow(), alice) is True
    assert entry_cases.AI_OFF.startswith("Error:") and "AI processing" in entry_cases.AI_OFF
    await nutrition_cases.log_meal(
        uow(), alice, [item("custom:feast", "300")], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW
    )
    summary = await nutrition_cases.day_summary(uow(), alice, now=NOW)
    names = {"custom:feast": "Test Feast"}
    shown = entry_cases.day_text(summary, names)
    assert "lunch: Test Feast (300 g)" in shown and "Total: about" in shown
    empty = await nutrition_cases.day_summary(uow(), alice, NOW.date() - timedelta(days=1), now=NOW)
    assert "nothing logged" in entry_cases.day_text(empty, names)
    await health_cases.save_profile(uow(), alice, ed_history=True, now=NOW)
    quiet = entry_cases.day_text(await nutrition_cases.day_summary(uow(), alice, now=NOW), names)
    assert "Test Feast (300 g)" in quiet and "kcal" not in quiet and "Total" not in quiet


# --- the web API ----------------------------------------------------------------------------

MEAL = {
    "meal": "lunch",
    "items": [
        {"food_id": RICE, "grams": "200"},
        {"food_id": CHICKEN, "grams": "100", "kind": "portion", "cooking": "fried"},
    ],
}


async def test_food_endpoints(world: World) -> None:
    anonymous = world.browser()
    for path in ("/api/health/foods?text=rice", f"/api/health/foods/{RICE}", "/api/health/day"):
        assert (await anonymous.get(path)).status_code == 401
    owner = world.browser()
    await owner.login(OWNER)
    found = (
        await owner.get("/api/health/foods", params={"text": "rice white cooked", "limit": 3})
    ).json()
    assert len(found) == 3 and all("cooked" in f["name"].lower() for f in found)
    paged = (
        await owner.get("/api/health/foods", params={"text": "rice", "limit": 2, "offset": 2})
    ).json()
    first = (await owner.get("/api/health/foods", params={"text": "rice", "limit": 4})).json()
    assert [f["id"] for f in paged] == [f["id"] for f in first[2:]]
    one = (await owner.get(f"/api/health/foods/{RICE}")).json()
    assert one["kcal_per_100g"] == "130" and one["source"] == "usda" and one["portions"]
    assert (await owner.get("/api/health/foods/usda:0")).status_code == 404
    for bad in ({}, {"text": ""}, {"text": "rice", "limit": 0}, {"text": "rice", "offset": 101}):
        assert (await owner.get("/api/health/foods", params=bad)).status_code == 422


async def test_meals_endpoints_end_to_end(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    refused = await owner.send("POST", "/api/health/meals", MEAL)
    assert refused.status_code == 403  # no consent yet
    await owner.send("POST", "/api/health/consent")
    made = await owner.send(
        "POST", "/api/health/meals", {**MEAL, "source": "voice", "note": "desk"}
    )
    assert made.status_code == 201, made.json()
    meal = made.json()
    assert meal["meal"] == "lunch" and meal["source"] == "voice" and meal["note"] == "desk"
    assert meal["totals"]["point"]["kcal"] == "425"  # 260 + 165
    assert int(meal["totals"]["high"]["kcal"]) > 425 > int(meal["totals"]["low"]["kcal"])
    assert (
        meal["items"][0]["name"].startswith("Rice, white")
        and meal["items"][0]["nutrients"]["kcal"] == "260"
    )
    assert meal["items"][1]["cooking"] == "fried" and meal["items"][0]["label"] == "200 g"

    listed = (await owner.get("/api/health/meals")).json()
    assert [m["id"] for m in listed] == [meal["id"]]
    assert (await owner.get(f"/api/health/meals/{meal['id']}")).json()["totals"] == meal["totals"]
    assert (await owner.get("/api/health/meals", params={"date": "2020-01-01"})).json() == []
    ranged = await owner.get(
        "/api/health/meals", params={"start": "2026-09-27", "end": "2026-09-28"}
    )
    assert len(ranged.json()) == 1

    patched = await owner.send(
        "PATCH", f"/api/health/meals/{meal['id']}",
        {"meal": "dinner", "items": [{"food_id": RICE, "grams": "100"}], "note": ""},
    )  # fmt: skip
    assert patched.status_code == 200, patched.json()
    assert patched.json()["meal"] == "dinner" and patched.json()["note"] is None
    assert patched.json()["totals"]["point"]["kcal"] == "130"
    assert (await owner.send("PATCH", f"/api/health/meals/{meal['id']}", {})).status_code == 422
    assert (
        await owner.send("PATCH", f"/api/health/meals/{meal['id']}", {"meal": None})
    ).status_code == 422

    day = (await owner.get("/api/health/day")).json()
    assert day["hidden"] is False and day["totals"]["point"]["kcal"] == "130"
    assert day["remaining"] is None  # no profile, so no targets
    assert day["meals"][0]["id"] == meal["id"]

    for bad in (
        {**MEAL, "items": []},
        {**MEAL, "meal": "brunch"},
        {**MEAL, "items": [{"food_id": RICE, "grams": "abc"}]},
        {**MEAL, "items": [{"food_id": RICE, "grams": "-5"}]},
        {**MEAL, "items": [{"food_id": "usda:0", "grams": "5"}]},
        {**MEAL, "extra": 1},
    ):
        assert (await owner.send("POST", "/api/health/meals", bad)).status_code == 422, bad
    assert (await owner.send("DELETE", f"/api/health/meals/{meal['id']}")).status_code == 204
    assert (await owner.get(f"/api/health/meals/{meal['id']}")).status_code == 404
    assert (await owner.send("DELETE", f"/api/health/meals/{meal['id']}")).status_code == 404
    assert (await owner.get("/api/health/meals/nonsense")).status_code == 404


async def test_numbers_free_mode_shows_foods_but_no_figures(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await ready(owner, ed_history=True)  # numbers-free follows the history flag
    made = (await owner.send("POST", "/api/health/meals", MEAL)).json()
    assert made["totals"] is None and made["items"][0]["nutrients"] is None
    assert made["items"][0]["name"].startswith("Rice") and made["items"][0]["label"] == "200 g"
    listed = (await owner.get("/api/health/meals")).json()
    assert listed[0]["totals"] is None
    day = (await owner.get("/api/health/day")).json()
    assert day["hidden"] is True and day["totals"] is None and day["remaining"] is None
    assert day["targets_kcal"] is None and day["meals"][0]["totals"] is None
    assert all(
        i["nutrients"] is None for m in day["meals"] for i in m["items"]
    )  # no ids to trip on
    stored = (await owner.get(f"/api/health/meals/{made['id']}")).json()
    assert stored["totals"] is None


async def test_two_users_never_see_each_others_meals_over_http(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite=invite)).status_code == 200
    await owner.send("POST", "/api/health/consent")
    await member.send("POST", "/api/health/consent")
    meal = (await owner.send("POST", "/api/health/meals", MEAL)).json()
    assert (await member.get("/api/health/meals")).json() == []
    assert (await member.get(f"/api/health/meals/{meal['id']}")).status_code == 404
    assert (await member.send("DELETE", f"/api/health/meals/{meal['id']}")).status_code == 404
    patch = await member.send("PATCH", f"/api/health/meals/{meal['id']}", {"meal": "snack"})
    assert patch.status_code == 404
    assert (await member.get("/api/health/day")).json()["meals"] == []
    assert (await owner.get(f"/api/health/meals/{meal['id']}")).json()["meal"] == "lunch"


async def test_the_energy_endpoint_uses_logged_food(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await ready(owner)
    for days_ago in range(28, 7, -1):
        await weigh_in(owner, "80", days_ago)
    before = (await owner.get("/api/health/energy")).json()
    assert before["label"] == "estimated from your profile"
    from tests.fakes import NOW as now

    for days_ago in range(1, 15):
        when = (now - timedelta(days=days_ago)).isoformat()
        body = {"meal": "dinner", "eaten_at": when, "items": [{"food_id": RICE, "grams": "1500"}]}
        assert (await owner.send("POST", "/api/health/meals", body)).status_code == 201
    after = (await owner.get("/api/health/energy")).json()
    assert after["label"] == "worked out from your logged food and weight"
    assert after["days_used"] == 14
