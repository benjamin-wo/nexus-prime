"""Weight trend and energy over HTTP and the use cases: numbers-free mode and isolation
between users. Every name and figure is made up."""

from datetime import timedelta
from decimal import Decimal

import pytest

from nexus.application import energy as energy_cases
from nexus.application import gym as gym_cases
from nexus.domain.energy import SafeTargets, TargetProposal
from nexus.domain.health import ActivityLevel
from nexus.domain.ledger import UserId
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory
from tests.integration.test_web_api import MEMBER, OWNER, Browser, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world

PROFILE = {
    "sex_for_equations": "male", "birth_year": 1990, "height_cm": "180",
    "activity_level": "moderate", "goal": "maintain",
}  # fmt: skip


async def weigh_in(who: Browser, kg: str, days_ago: int) -> None:
    when = (NOW - timedelta(days=days_ago)).isoformat()
    made = await who.send(
        "POST", "/api/health/samples", {"kind": "weight", "value": kg, "start_at": when}
    )
    assert made.status_code == 201, made.json()


async def ready(who: Browser, **profile: object) -> None:
    await who.send("POST", "/api/health/consent")
    for days_ago in range(7, 0, -1):  # a steady 80 kg for a week
        await weigh_in(who, "80", days_ago)
    saved = await who.send("PUT", "/api/health/profile", {**PROFILE, **profile})
    assert saved.status_code == 200, saved.json()


async def test_weight_endpoint_gives_the_trend_and_a_worded_rate(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    empty = (await owner.get("/api/health/weight")).json()
    assert empty["points"] == [] and empty["rate_text"] is None and empty["trend_kg"] is None
    await ready(owner)
    body = (await owner.get("/api/health/weight?days=30")).json()
    assert body["hidden"] is False and body["trend_words"] == "steady"
    assert body["trend_kg"] == "80.000" and len(body["points"]) == 7
    assert body["rate_kg_per_week"] == "0.000"
    assert body["rate_text"] == "about steady over the last 2 weeks"
    assert body["last_weigh_in"]["kg"] == "80.000"
    # Losing: 80 then 79 in the last week reads as slowly down, in words built from numbers.
    await weigh_in(owner, "78", 0)
    await weigh_in(owner, "78", 0)  # the same moment: replaces, not a second entry
    down = (await owner.get("/api/health/weight")).json()
    assert down["trend_words"] == "slowly down"
    assert (
        down["rate_text"].startswith("about ")
        and "kg a week down over the last 2 weeks" in down["rate_text"]
    )
    assert (await owner.get("/api/health/weight?days=0")).status_code == 422
    assert (await owner.get("/api/health/weight?days=400")).status_code == 422


async def test_energy_is_estimated_from_the_profile_without_logged_food(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    assert (await owner.get("/api/health/energy")).json()["available"] is False
    await ready(owner)
    body = (await owner.get("/api/health/energy")).json()
    # Age 36 in 2026: 800 + 1125 - 180 + 5 = 1750 x 1.55 = 2712.5 -> 2713; no food logged,
    # so 15% either side.
    assert body["label"] == "estimated from your profile" and body["kcal"] == "2713"
    assert (body["kcal_low"], body["kcal_high"]) == ("2306", "3120")
    assert body["paused_reason"] is not None
    assert body["targets"]["kcal"] == "2713" and body["targets"]["protein_g"] == "128"
    assert body["targets"]["fibre_g"] == "38"
    assert body["hidden"] is False


async def test_numbers_free_mode_omits_every_figure(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await ready(owner, ed_history=True)  # numbers-free follows the history flag
    weight = (await owner.get("/api/health/weight")).json()
    assert weight["hidden"] is True and weight["trend_words"] == "steady"
    assert weight["points"] is None and weight["trend_kg"] is None
    assert weight["rate_text"] is None and weight["last_weigh_in"] is None
    energy = (await owner.get("/api/health/energy")).json()
    assert energy["hidden"] is True and energy["trend_words"] == "steady"
    for key in ("kcal", "kcal_low", "kcal_high", "targets", "confidence", "days_used"):
        assert energy[key] is None
    assert "2713" not in str(energy) and "80" not in str(weight)


async def test_two_users_never_see_each_others_weight_or_energy(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite=invite)).status_code == 200
    await ready(owner)
    assert (await member.send("POST", "/api/health/consent")).status_code == 201
    mine = (await member.get("/api/health/weight")).json()
    assert mine["points"] == [] and mine["last_weigh_in"] is None
    assert (await member.get("/api/health/energy")).json()["available"] is False
    assert len((await owner.get("/api/health/weight")).json()["points"]) == 7


async def test_endpoints_need_a_session(world: World) -> None:
    anon = world.browser()
    assert (await anon.get("/api/health/weight")).status_code == 401
    assert (await anon.get("/api/health/energy")).status_code == 401


async def test_use_cases_numbers_free_and_the_injected_providers(
    uow: UowFactory, alice: UserId
) -> None:
    from nexus.application import health as health_cases
    from nexus.domain.health import SampleKind

    await gym_cases.give_consent(uow(), alice, now=NOW)
    for days_ago in range(21, 0, -1):
        await health_cases.log_sample(
            uow(),
            alice,
            SampleKind.WEIGHT,
            Decimal("80"),
            start_at=NOW - timedelta(days=days_ago),
            now=NOW,
        )
    await health_cases.save_profile(
        uow(), alice, birth_year=1990, height_cm=Decimal(180),
        activity_level=ActivityLevel.MODERATE, ed_history=True, now=NOW,
    )  # fmt: skip
    overview = await energy_cases.weight_overview(uow(), alice, now=NOW, days=7)
    assert overview.hidden is True and overview.trend_kg == Decimal("80.000")  # still computed
    assert len(overview.points) == 6  # the series ends at the last weigh-in, yesterday

    async def eaten(user: UserId, first, last):  # type: ignore[no-untyped-def]
        assert user == alice
        return {first + timedelta(days=i): Decimal(2600) for i in range(1, 22)}

    seen: list[TargetProposal] = []

    def safety(p: TargetProposal) -> SafeTargets:
        seen.append(p)
        return SafeTargets(p.kcal, p.rate_pct_per_week)

    got = await energy_cases.current_targets(
        uow(), alice, now=NOW, intake_provider=eaten, apply_safety=safety
    )
    assert got.hidden is True and got.energy.basis == "logged"
    assert got.energy.estimate is not None and got.energy.estimate.kcal == Decimal(2600)
    assert got.targets is not None and got.targets.kcal == Decimal(2600)
    assert seen[0].profile.user_id == alice
