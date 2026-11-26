"""Daily targets with the safety layer wired in: gates, the calorie floor, and suspension when
logged intake or the weight trend raises a signal. Every name and figure is made up."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application import health_targets as targets_cases
from nexus.domain.health import ActivityLevel, Goal, SampleKind, Sex
from nexus.domain.health_safety import Signal
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import health_profiles
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory
from tests.integration.test_health_energy import ready
from tests.integration.test_nutrition import agree, log_days, stocked
from tests.integration.test_web_api import OWNER, World

pytestmark = pytest.mark.integration

world = test_web_api.world
D = Decimal


async def set_up(
    uow: UowFactory, user: UserId, *, kg: str = "80", height: int = 180, **fields: object
) -> None:
    await gym_cases.give_consent(uow(), user, now=NOW)
    for days_ago in range(14, 0, -1):
        await health_cases.log_sample(
            uow(), user, SampleKind.WEIGHT, D(kg),
            start_at=NOW - timedelta(days=days_ago), now=NOW,
        )  # fmt: skip
    base: dict[str, object] = {
        "sex_for_equations": Sex.MALE,
        "birth_year": NOW.year - 36,
        "height_cm": D(height),
        "activity_level": ActivityLevel.MODERATE,
    }
    await health_cases.save_profile_checked(uow(), user, now=NOW, **{**base, **fields})  # type: ignore[arg-type]


async def force_goal(engine: AsyncEngine, user: UserId, goal: Goal) -> None:
    """Store a goal the profile gate would refuse, as an old row or another writer could."""
    async with engine.begin() as connection:
        await connection.execute(
            update(health_profiles).where(health_profiles.c.user_id == user).values(goal=goal)
        )


@pytest.mark.parametrize(
    ("born_offset", "kg", "height"), [(16, "80", 180), (36, "50", 180)], ids=["under_18", "low_bmi"]
)
async def test_a_gated_profile_gets_no_deficit(
    uow: UowFactory, engine: AsyncEngine, alice: UserId, born_offset: int, kg: str, height: int
) -> None:
    await set_up(uow, alice, kg=kg, height=height, birth_year=NOW.year - born_offset)
    await force_goal(engine, alice, Goal.LOSE)
    found = await targets_cases.safe_targets(uow, alice, now=NOW)
    estimate = found.overview.energy.estimate
    assert estimate is not None and not found.suspended
    got = found.overview.targets
    assert got is not None
    assert got.kcal >= estimate.kcal and got.rate_pct_per_week == 0  # maintenance, no deficit
    assert any("weight-loss" in note for note in got.notes)


async def test_a_plain_adult_loss_goal_still_gets_its_deficit(
    uow: UowFactory, engine: AsyncEngine, alice: UserId
) -> None:
    await set_up(uow, alice, goal=Goal.LOSE)
    found = await targets_cases.safe_targets(uow, alice, now=NOW)
    got, estimate = found.overview.targets, found.overview.energy.estimate
    assert got is not None and estimate is not None
    assert got.kcal < estimate.kcal and got.rate_pct_per_week < 0


async def test_targets_never_go_below_the_floor(uow: UowFactory, alice: UserId) -> None:
    # A small woman asking for the fastest allowed loss: the deficit would cut under her resting
    # rate (1,209 kcal), so the pace slows and calories sit on the floor.
    await set_up(
        uow, alice, kg="55", height=160, sex_for_equations=Sex.FEMALE,
        activity_level=ActivityLevel.SEDENTARY, goal=Goal.LOSE, target_rate_pct_per_week=D(1),
    )  # fmt: skip
    found = await targets_cases.safe_targets(uow, alice, now=NOW)
    got = found.overview.targets
    assert got is not None and not found.suspended
    floor = D(1209)
    assert got.kcal >= floor and got.kcal_range[0] >= floor
    assert got.rate_pct_per_week > D("-0.5")  # slower than even the lean limit
    assert any("minimum" in note for note in got.notes)


async def test_floor_breaches_on_three_of_seven_logged_days_suspend_targets(
    uow: UowFactory, alice: UserId
) -> None:
    await stocked(uow)
    await set_up(uow, alice)
    await agree(uow, alice)
    await log_days(uow, alice, range(1, 5), 2200)  # four days at a healthy intake
    await log_days(uow, alice, range(5, 8), 900)  # three days under the floor
    again = await targets_cases.safe_targets(uow, alice, now=NOW)
    assert again.suspended and again.overview.targets is None
    assert again.new_signals == (Signal.INTAKE_BELOW_FLOOR,) and again.check_in
    assert again.signposts  # where to get help
    second = await targets_cases.safe_targets(uow, alice, now=NOW)
    assert second.suspended and second.new_signals == () and not second.check_in  # one check-in


async def test_two_floor_breaches_do_not_suspend(uow: UowFactory, alice: UserId) -> None:
    await stocked(uow)
    await set_up(uow, alice)
    await agree(uow, alice)
    await log_days(uow, alice, range(1, 6), 2200)
    await log_days(uow, alice, range(6, 8), 900)
    found = await targets_cases.safe_targets(uow, alice, now=NOW)
    assert not found.suspended and found.overview.targets is not None
    assert found.new_signals == ()


async def test_today_half_logged_is_not_a_breach(uow: UowFactory, alice: UserId) -> None:
    await stocked(uow)
    await set_up(uow, alice)
    await agree(uow, alice)
    await log_days(uow, alice, range(0, 1), 300)  # breakfast so far
    await log_days(uow, alice, range(1, 3), 900)
    found = await targets_cases.safe_targets(uow, alice, now=NOW)
    assert not found.suspended


async def test_numbers_free_and_ed_history_suspend_targets(uow: UowFactory, alice: UserId) -> None:
    await set_up(uow, alice, ed_history=True)
    found = await targets_cases.safe_targets(uow, alice, now=NOW)
    assert found.suspended and found.overview.targets is None and found.signposts


async def test_the_weekly_history_reads_the_trend() -> None:
    from nexus.domain.energy import TrendPoint

    start = NOW.date() - timedelta(days=40)
    points = [
        TrendPoint(start + timedelta(days=i), D(100) - D(i) * D("0.2"), D(100) - D(i) * D("0.2"))
        for i in range(41)
    ]
    history = targets_cases.weekly_pct_history(points, NOW.date())
    assert len(history) == 4 and all(h is not None and h < 0 for h in history)
    assert targets_cases.weekly_pct_history([], NOW.date()) == [None] * 4


async def test_the_web_reads_carry_the_safety_note(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await ready(owner)
    for path in ("/api/health/energy", "/api/health/day"):
        body = (await owner.get(path)).json()
        assert body["safety"] == {
            "suspended": False, "signposts": [], "new_signals": [], "check_in": None,
        }  # fmt: skip
