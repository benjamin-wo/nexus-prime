"""Food logging maths: nutrients from grams, ranges, the fat adjustment, daily totals, search and
portion matching. Every food and figure is made up; the real data is tested in the loader test."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.nutrition import (
    COOKING_UPLIFT_FRIED,
    COOKING_UPLIFT_GRAVY,
    EN_DASH,
    MODIFIER_WIDEN,
    UNCERTAINTY_AI_ESTIMATE,
    UNCERTAINTY_ESTIMATED,
    UNCERTAINTY_PORTION,
    UNCERTAINTY_WEIGHED,
    Cooking,
    EntrySource,
    EstimateKind,
    Food,
    FoodItem,
    FoodSource,
    MealEntry,
    MealSlot,
    Nutrients,
    Portion,
    check_ai_estimate,
    daily_totals,
    item_totals,
    kcal_range_words,
    make_estimated_item,
    make_item,
    meal_totals,
    modifier_scale,
    nutrients_for,
    portion_grams,
    search,
)

D = Decimal


def food(
    name: str, kcal: str = "200", fat: str = "10", portions: tuple[Portion, ...] = (), **kw: object
) -> Food:
    n = Nutrients(D(kcal), D("20"), D("30"), D(fat), D("2"))
    return Food(
        id=f"custom:{name.casefold().replace(' ', '-')}",
        source=FoodSource.CUSTOM,
        name=name,
        aliases=tuple(kw.get("aliases", ())),  # type: ignore[arg-type]
        per_100g=n,
        portions=portions,
    )


RICE = food("Rice, white, cooked", "130", "0.3", (Portion("1 cup", D("158")),))


def test_nutrients_scale_from_per_100g() -> None:
    n = nutrients_for(RICE, D(200))
    assert n.kcal == D("260.000") and n.protein_g == D("40.000") and n.fibre_g == D("4.000")
    with pytest.raises(InvalidInput):
        nutrients_for(RICE, D(0))
    with pytest.raises(InvalidInput):
        nutrients_for(RICE, D(100000))


def test_unknown_fibre_stays_unknown_and_sums_keep_what_is_known() -> None:
    plain = Food(
        "custom:x", FoodSource.CUSTOM, "X", (), Nutrients(D(100), D(1), D(1), D(1), None), ()
    )
    assert nutrients_for(plain, D(50)).fibre_g is None
    both = nutrients_for(plain, D(50)) + nutrients_for(RICE, D(100))
    assert both.fibre_g == D("2.000")


def test_each_kind_of_portion_has_its_own_range() -> None:
    for kind, half in (
        (EstimateKind.WEIGHED, UNCERTAINTY_WEIGHED),
        (EstimateKind.PORTION, UNCERTAINTY_PORTION),
        (EstimateKind.ESTIMATED, UNCERTAINTY_ESTIMATED),
    ):
        t = item_totals(make_item(RICE, D(100), "x", kind))
        assert t.point.kcal == D("130.000")
        assert t.low.kcal == D("130") * (1 - half)
        assert t.high.kcal == D("130") * (1 + half)
    assert UNCERTAINTY_WEIGHED < UNCERTAINTY_PORTION < UNCERTAINTY_ESTIMATED


def test_the_range_of_a_meal_is_the_sum_of_the_item_ranges() -> None:
    a = make_item(RICE, D(100), "100 g", EstimateKind.WEIGHED)
    b = make_item(RICE, D(100), "1 plate", EstimateKind.ESTIMATED)
    t = meal_totals([a, b])
    assert t.point.kcal == D("260.000")
    assert t.low.kcal == D("130") * D("0.95") + D("130") * D("0.7")
    assert t.high.kcal == D("130") * D("1.05") + D("130") * D("1.3")


def test_oily_cooking_widens_only_upward_and_never_moves_the_point() -> None:
    plain = make_item(RICE, D(100), "x", EstimateKind.PORTION)
    fried = make_item(RICE, D(100), "x", EstimateKind.PORTION, cooking=Cooking.FRIED)
    gravy = make_item(RICE, D(100), "x", EstimateKind.PORTION, cooking=Cooking.GRAVY)
    p, f, g = item_totals(plain), item_totals(fried), item_totals(gravy)
    assert f.point == p.point and f.low == p.low
    assert f.high.kcal == p.high.kcal + D("130") * COOKING_UPLIFT_FRIED
    assert f.high.fat_g == p.high.fat_g + D("0.3") * COOKING_UPLIFT_FRIED
    assert f.high.protein_g == p.high.protein_g  # only kcal and fat
    assert g.high.kcal - p.high.kcal > f.high.kcal - p.high.kcal
    assert COOKING_UPLIFT_GRAVY > COOKING_UPLIFT_FRIED


def test_an_unapplied_modifier_widens_both_sides() -> None:
    plain = item_totals(make_item(RICE, D(100), "x", EstimateKind.PORTION))
    mod = item_totals(
        make_item(RICE, D(100), "x", EstimateKind.PORTION, extra_uncertainty=MODIFIER_WIDEN)
    )
    assert mod.point == plain.point and mod.low.kcal < plain.low.kcal < plain.high.kcal
    assert mod.high.kcal > plain.high.kcal


def test_modifier_words() -> None:
    assert modifier_scale("less rice") == D("0.7")
    assert modifier_scale("extra gravy") == D("1.3")
    assert modifier_scale("no chilli") == D(0)
    assert modifier_scale("with egg") is None


def test_kcal_range_words_round_to_ten() -> None:
    t = meal_totals([make_item(RICE, D(300), "x", EstimateKind.PORTION)])
    assert kcal_range_words(t) == f"330{EN_DASH}450 kcal"  # 331.5 and 448.5
    assert (
        kcal_range_words(meal_totals([make_item(RICE, D(300), "x", EstimateKind.WEIGHED)]), 100)
        == "400 kcal"
    )


def entry(when: datetime, *items: FoodItem) -> MealEntry:
    return MealEntry(
        uuid4(), UserId(uuid4()), MealSlot.LUNCH, when, EntrySource.CHAT, None,
        tuple(items), when, when,
    )  # fmt: skip


def test_daily_totals_group_by_the_users_local_day() -> None:
    item = make_item(RICE, D(100), "x", EstimateKind.WEIGHED)
    sg = ZoneInfo("Asia/Singapore")
    late = datetime(2026, 9, 28, 17, 0, tzinfo=UTC)  # 01:00 on the 29th in Singapore
    early = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)  # 10:00 on the 28th
    days = daily_totals([entry(late, item), entry(early, item, item)], sg)
    assert [d.isoformat() for d in days] == ["2026-09-28", "2026-09-29"]
    assert days[next(iter(days))].point.kcal == D("260.000")
    assert list(daily_totals([entry(late, item), entry(early, item)], UTC)) == [early.date()]
    assert daily_totals([], sg) == {}


def test_a_meal_needs_a_time_zone() -> None:
    with pytest.raises(InvalidInput):
        entry(datetime(2026, 9, 28, 2, 0))


CATALOGUE = [
    food("Chicken, breast, cooked, roasted"),
    food("Chicken, breast, raw"),
    food("Chicken"),
    food("Chicken rice"),
    food("Rice, white, cooked"),
    food("Fried chicken"),
    food("Soy sauce", aliases=("shoyu",)),
]


def names(text: str, **kw: int) -> list[str]:
    return [f.name for f in search(CATALOGUE, text, **kw)]


def test_search_ranks_exact_then_prefix_then_word_starts() -> None:
    assert names("chicken")[:2] == ["Chicken", "Chicken rice"]
    assert names("chicken")[-1] == "Fried chicken"  # a word start, after the prefixes
    assert names("chicken rice")[0] == "Chicken rice"
    assert names("rice chicken") == ["Chicken rice"]  # words in any order
    assert names("rice")[0] == "Rice, white, cooked"
    assert names("shoyu") == ["Soy sauce"]  # aliases count
    assert names("zzz") == []


def test_search_prefers_the_state_the_query_names() -> None:
    assert names("chicken breast raw")[0] == "Chicken, breast, raw"
    assert names("chicken breast cooked")[0] == "Chicken, breast, cooked, roasted"
    assert names("chicken breast")[0] == "Chicken, breast, raw"  # neutral: the shorter name


def test_search_limits_and_rejects_bad_input() -> None:
    assert len(names("chicken", limit=2)) == 2
    for bad in ("", "   !!"):
        with pytest.raises(InvalidInput):
            search(CATALOGUE, bad)
    with pytest.raises(InvalidInput):
        search(CATALOGUE, "x", limit=0)


OATS = food(
    "Oats",
    portions=(
        Portion("1 cup", D("81")),
        Portion("1 cup, cooked", D("234")),
        Portion("2 tablespoon", D("20")),
        Portion('1 slice (3-1/8" long)', D("30")),
        Portion("1 serving", D("40")),
    ),
)


@pytest.mark.parametrize(
    ("text", "label", "grams"),
    [
        ("1 cup", "1 cup", "81"),
        ("2 cups", "1 cup", "162"),
        ("half a cup", "1 cup", "40.5"),
        ("1 cup cooked", "1 cup, cooked", "234"),
        ("1 tbsp", "2 tablespoon", "10"),
        ("3 tablespoons", "2 tablespoon", "30"),
        ("a slice", '1 slice (3-1/8" long)', "30"),
        ("1/2 cup", "1 cup", "40.5"),
        ("serving", "1 serving", "40"),
    ],
)
def test_portion_matching(text: str, label: str, grams: str) -> None:
    found = portion_grams(OATS, text)
    assert found is not None
    assert found[0].label == label and found[1] == D(grams)


@pytest.mark.parametrize("text", ["1 plate", "a bowl", "", "0 cups", "cooked bowl"])
def test_portion_matching_gives_up_rather_than_guess(text: str) -> None:
    assert portion_grams(OATS, text) is None


def test_food_from_dict_validates() -> None:
    data = {
        "id": "usda:1", "source": "usda", "name": "X", "aliases": [], "kcal": D("1.5"),
        "protein_g": D(1), "carbs_g": D(1), "fat_g": D(1), "fibre_g": None,
        "portions": [{"label": "1 cup", "grams": D(5)}],
    }  # fmt: skip
    assert Food.from_dict(data).portions[0].grams == D(5)
    bads: list[dict[str, object]] = [
        {"source": "nope"},
        {"id": "custom:1"},
        {"kcal": D(-1)},
        {"portions": [{}]},
    ]
    for bad in bads:
        with pytest.raises(InvalidInput):
            Food.from_dict({**data, **bad})


def test_an_ai_estimate_inside_the_bounds_is_kept_and_has_the_widest_range() -> None:
    n = check_ai_estimate(D(600), D(25), D(70), D(25))  # 100 + 280 + 225 = 605 kcal
    assert n.kcal == D(600)
    item = make_estimated_item(n, "1 bowl", name="laksa")
    assert item.food_id is None and item.source_detail == "ai_estimate"
    assert item.kind is EstimateKind.AI_ESTIMATE
    t = item_totals(item)
    assert UNCERTAINTY_AI_ESTIMATE > UNCERTAINTY_ESTIMATED
    assert (t.low.kcal, t.high.kcal) == (D(360), D(840))  # plus or minus 40%


@pytest.mark.parametrize(
    "figures",
    [
        (0, 0, 0, 0),  # no energy
        (-100, 10, 10, 10),
        (2501, 100, 300, 130),  # over 2,500 kcal for one item
        (600, -1, 100, 25),  # a negative macro
        (600, 5, 5, 5),  # the macros give 85 kcal, not 600
        (600, 100, 100, 100),  # the macros give 1,700 kcal
    ],
)
def test_an_ai_estimate_out_of_bounds_is_rejected(figures: tuple[int, int, int, int]) -> None:
    with pytest.raises(InvalidInput):
        check_ai_estimate(*(D(f) for f in figures))


def test_the_energy_check_allows_a_quarter_either_way() -> None:
    check_ai_estimate(D(500), D(25), D(50), D(25))  # 525 kcal: 5% over
    check_ai_estimate(D(500), D(25), D(50), D(12))  # 408 kcal: 18% under
    with pytest.raises(InvalidInput):
        check_ai_estimate(D(500), D(25), D(50), D(0))  # 300 kcal: 40% under


def test_an_item_without_a_food_must_say_it_is_an_estimate() -> None:
    item = make_estimated_item(Nutrients(D(100), D(5), D(15), D(2), None), "1 serving")
    with pytest.raises(InvalidInput):
        FoodItem(None, D(1), "x", item.nutrients, source_detail="db")


def test_search_leaves_out_baby_food_unless_asked() -> None:
    from nexus.domain.nutrition import search

    baby = food("Babyfood, dinner, chicken and rice")
    assert search([baby, RICE], "chicken rice") == []
    assert search([baby, RICE], "baby chicken rice") == [baby]


def test_strong_match_is_the_name_or_an_everyday_name_word_for_word() -> None:
    from nexus.domain.nutrition import strong_match

    egg = food("Egg, whole, cooked, hard-boiled", aliases=("egg", "boiled egg"))
    assert strong_match(egg, "Egg")
    assert strong_match(egg, "boiled egg")
    assert not strong_match(egg, "egg fried rice")
