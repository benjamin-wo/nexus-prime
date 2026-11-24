"""Health safety, applied: the one door for targets, the current state, the profile gate and the
profile response. Every name and figure is made up."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application import health_safety as safety
from nexus.application.ports import UnitOfWork
from nexus.domain.health import Goal, SampleKind, Sex
from nexus.domain.health_safety import IntakeDay, ReasonCode, Signal
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import health_safety_events
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory
from tests.integration.test_web_api import OWNER, World

pytestmark = pytest.mark.integration

world = test_web_api.world

D = Decimal
WEIGHT = SampleKind.WEIGHT
BORN_ADULT = NOW.year - 36  # a safe age of 35


async def profile(
    uow: UowFactory, user: UserId, *, weight: str | None = "80", **fields: object
) -> health_cases.ProfileSaved:
    await gym_cases.give_consent(uow(), user, now=NOW)
    if weight is not None:
        await health_cases.log_sample(uow(), user, WEIGHT, D(weight), start_at=NOW, now=NOW)
    base: dict[str, object] = {
        "sex_for_equations": Sex.FEMALE,
        "birth_year": BORN_ADULT,
        "height_cm": D(170),
    }
    return await health_cases.save_profile_checked(uow(), user, now=NOW, **{**base, **fields})  # type: ignore[arg-type]


async def weigh(uow: UowFactory, user: UserId, kg: str, at: datetime) -> None:
    await health_cases.log_sample(uow(), user, WEIGHT, D(kg), start_at=at, now=NOW)


# --- the profile gate ---------------------------------------------------------------------------


async def test_a_loss_goal_is_kept_for_an_adult_with_a_healthy_bmi(
    uow: UowFactory, alice: UserId
) -> None:
    saved = await profile(uow, alice, goal=Goal.LOSE, target_rate_pct_per_week=D("0.5"))
    assert saved.profile.goal is Goal.LOSE
    assert (saved.gate.allowed, saved.gate.reason) == (True, ReasonCode.OK)
    assert saved.profile.target_rate_pct_per_week == D("0.50")


@pytest.mark.parametrize(
    ("fields", "weight", "reason"),
    [
        ({"birth_year": NOW.year - 18}, "80", ReasonCode.UNDER_18),  # could still be 17
        ({"birth_year": NOW.year - 19}, "50", ReasonCode.LOW_BMI),  # BMI 17.3
        ({"ed_history": True}, "80", ReasonCode.ED_HISTORY),
        ({"birth_year": None}, "80", ReasonCode.AGE_UNKNOWN),
        ({}, None, ReasonCode.BMI_UNKNOWN),
    ],
)
async def test_a_blocked_loss_goal_saves_the_profile_as_maintain(
    uow: UowFactory,
    alice: UserId,
    fields: dict[str, object],
    weight: str | None,
    reason: ReasonCode,
) -> None:
    saved = await profile(
        uow, alice, weight=weight, goal=Goal.LOSE, target_rate_pct_per_week=D("0.5"), **fields
    )
    assert saved.profile.goal is Goal.MAINTAIN
    assert saved.profile.target_rate_pct_per_week is None
    assert (saved.gate.allowed, saved.gate.reason) == (False, reason)
    stored = await health_cases.profile(uow(), alice, now=NOW)
    assert stored is not None and stored.goal is Goal.MAINTAIN
    assert stored.birth_year == fields.get("birth_year", BORN_ADULT)  # the rest was saved


async def test_ed_history_defaults_to_numbers_free_and_an_override_needs_a_confirm(
    uow: UowFactory, alice: UserId
) -> None:
    saved = await profile(uow, alice, ed_history=True)
    assert saved.profile.numbers_free is True
    kept = await profile(
        uow, alice, ed_history=True, numbers_free=False, goal=Goal.LOSE, confirm_ed_override=True
    )
    assert kept.profile.goal is Goal.LOSE
    assert kept.gate.reason is ReasonCode.ED_OVERRIDDEN


# --- assess -------------------------------------------------------------------------------------


async def test_a_plain_profile_has_nothing_suspended(uow: UowFactory, alice: UserId) -> None:
    await profile(uow, alice)
    state = await safety.assess(uow(), alice, now=NOW)
    assert (state.signals, state.suspended, state.signposts) == ((), False, ())
    assert state.floor_kcal == 1200 and state.weight_loss_gate.allowed


async def test_numbers_free_and_ed_history_suspend_and_show_signposts(
    uow: UowFactory, alice: UserId
) -> None:
    await profile(uow, alice, ed_history=True)
    state = await safety.assess(uow(), alice, now=NOW)
    assert state.suspended
    assert state.reasons == (ReasonCode.SUSPENDED_NUMBERS_FREE, ReasonCode.SUSPENDED_ED_HISTORY)
    assert next(s.name for s in state.signposts) == "SGH Eating Disorders Programme"
    assert len(state.signposts) == 2  # an adult: no KKH


async def test_under_18_signposts_include_kkh(uow: UowFactory, alice: UserId) -> None:
    await profile(uow, alice, ed_history=True, birth_year=NOW.year - 15)
    state = await safety.assess(uow(), alice, now=NOW)
    assert next(s.name for s in state.signposts).startswith("KK Women")


async def test_many_weigh_ins_in_a_day_is_a_signal_that_suspends(
    uow: UowFactory, alice: UserId
) -> None:
    await profile(uow, alice, weight=None)
    for minutes in (1, 2, 3):
        await weigh(uow, alice, "80.1", NOW - timedelta(minutes=minutes))
    assert not (await safety.assess(uow(), alice, now=NOW)).signals  # 3: not yet
    await weigh(uow, alice, "80.2", NOW - timedelta(minutes=4))
    state = await safety.assess(uow(), alice, now=NOW)
    assert state.signals == (Signal.MANY_WEIGH_INS,)
    assert state.suspended and state.reasons == (ReasonCode.SUSPENDED_ED_SIGNAL,)
    assert state.signposts


async def test_rapid_loss_from_stored_weights(uow: UowFactory, alice: UserId) -> None:
    await profile(uow, alice, weight=None)
    # weekly means 100, 98, 96, 94: about 2 percent a week, three weeks running
    for week, kg in enumerate(("94", "96", "98", "100")):
        for day in (0, 1):
            await weigh(uow, alice, kg, NOW - timedelta(days=7 * week + day, hours=1))
    state = await safety.assess(uow(), alice, now=NOW)
    assert Signal.RAPID_LOSS in state.signals


async def test_a_plugged_in_intake_provider_and_trend_are_used(
    uow: UowFactory, alice: UserId
) -> None:
    await profile(uow, alice)

    async def low_intake(
        uow: UnitOfWork, user_id: UserId, *, now: datetime, floor_kcal: int
    ) -> list[IntakeDay]:
        return [
            IntakeDay((now - timedelta(days=i)).date(), floor_kcal - 1, floor_kcal)
            for i in range(3)
        ]

    async def fast_trend(uow: UnitOfWork, user_id: UserId, now: datetime) -> list[Decimal | None]:
        return [D("-1.5"), D("-1.5")]

    state = await safety.assess(
        uow(),
        alice,
        now=NOW,
        intake=low_intake,
        weekly_trend=fast_trend,
    )
    assert state.signals == (Signal.INTAKE_BELOW_FLOOR, Signal.RAPID_LOSS)
    # the resting rate raises the floor the intake is judged against
    high = await safety.assess(uow(), alice, now=NOW, bmr_kcal=D(1700))
    assert high.floor_kcal == 1700


async def test_a_signal_is_recorded_once_for_a_check_in(
    uow: UowFactory, alice: UserId, bob: UserId, engine: AsyncEngine
) -> None:
    await profile(uow, alice)
    first = await safety.assess(uow(), alice, now=NOW, flagged_language=True, record=True)
    assert first.new_signals == (Signal.COMPENSATING_LANGUAGE,)
    again = await safety.assess(
        uow(), alice, now=NOW + timedelta(days=1), flagged_language=True, record=True
    )
    assert again.new_signals == () and again.signals == (Signal.COMPENSATING_LANGUAGE,)
    later = await safety.assess(
        uow(), alice, now=NOW + timedelta(days=31), flagged_language=True, record=True
    )
    assert later.new_signals == (Signal.COMPENSATING_LANGUAGE,)
    untouched = await safety.assess(uow(), alice, now=NOW, flagged_language=True)  # no record
    assert untouched.new_signals == ()
    async with engine.connect() as connection:
        count = await connection.scalar(select(func.count()).select_from(health_safety_events))
    assert count == 2
    assert (await safety.assess(uow(), bob, now=NOW, record=True)).new_signals == ()


# --- check_targets ------------------------------------------------------------------------------


async def test_check_targets_passes_a_safe_proposal_through(uow: UowFactory, alice: UserId) -> None:
    await profile(uow, alice)
    got = await safety.check_targets(
        uow(),
        alice,
        safety.TargetProposal(Goal.LOSE, D("0.5"), calories_kcal=1800),
        now=NOW,
    )
    assert (got.goal, got.rate_pct_per_week, got.calories_kcal) == (Goal.LOSE, D("0.5"), 1800)
    assert (got.protein_g, got.protein_g_per_kg, got.suspended) == (128, D("1.6"), False)
    assert got.reasons == ()


async def test_check_targets_applies_floor_cap_lean_limit_and_protein(
    uow: UowFactory, alice: UserId
) -> None:
    await profile(uow, alice)  # 80 kg, 170 cm: BMI 27.7, a woman: floor 1200
    got = await safety.check_targets(
        uow(),
        alice,
        safety.TargetProposal(Goal.LOSE, D("2"), calories_kcal=900, protein_g_per_kg=D("1.0")),
        now=NOW,
    )
    assert got.rate_pct_per_week == D("1.0") and got.calories_kcal == 1200
    assert got.protein_g_per_kg == D("1.4") and got.protein_g == 112
    assert got.reasons == (
        ReasonCode.RATE_HARD_CAP,
        ReasonCode.FLOOR_APPLIED,
        ReasonCode.PROTEIN_RAISED,
    )
    # a resting rate above the usual floor lifts the floor
    resting = await safety.check_targets(
        uow(),
        alice,
        safety.TargetProposal(Goal.MAINTAIN, calories_kcal=1300, bmr_kcal=D(1450)),
        now=NOW,
    )
    assert resting.calories_kcal == 1450 and resting.floor_kcal == 1450


async def test_check_targets_slows_the_rate_to_stay_on_the_floor(
    uow: UowFactory, alice: UserId
) -> None:
    await profile(uow, alice)
    got = await safety.check_targets(
        uow(),
        alice,
        safety.TargetProposal(Goal.LOSE, D("1.0"), tdee_kcal=D(1700)),
        now=NOW,
    )
    assert got.rate_pct_per_week is not None and got.rate_pct_per_week < D("1.0")
    assert got.calories_kcal is not None and got.calories_kcal >= 1200
    assert ReasonCode.RATE_SLOWED_FOR_FLOOR in got.reasons


async def test_check_targets_limits_a_lean_user(uow: UowFactory, alice: UserId) -> None:
    await profile(uow, alice, weight="60")  # BMI 20.8
    got = await safety.check_targets(
        uow(), alice, safety.TargetProposal(Goal.LOSE, D("0.75")), now=NOW
    )
    assert (got.rate_pct_per_week, got.reasons) == (D("0.5"), (ReasonCode.RATE_LEAN_LIMIT,))


async def test_check_targets_turns_a_blocked_loss_into_maintain(
    uow: UowFactory, alice: UserId
) -> None:
    await profile(uow, alice, weight="50")  # BMI 17.3
    got = await safety.check_targets(
        uow(), alice, safety.TargetProposal(Goal.LOSE, D("0.5"), calories_kcal=1500), now=NOW
    )
    assert got.goal is Goal.MAINTAIN and got.rate_pct_per_week is None
    assert got.reasons[0] is ReasonCode.LOW_BMI
    assert got.calories_kcal == 1500 and not got.suspended


async def test_check_targets_sets_no_numbers_while_suspended(
    uow: UowFactory, alice: UserId
) -> None:
    await profile(uow, alice, ed_history=True)
    got = await safety.check_targets(
        uow(), alice, safety.TargetProposal(Goal.LOSE, D("0.5"), calories_kcal=1500), now=NOW
    )
    assert got.suspended and got.goal is Goal.MAINTAIN
    assert (got.rate_pct_per_week, got.calories_kcal, got.protein_g) == (None, None, None)
    assert ReasonCode.SUSPENDED_ED_HISTORY in got.reasons and got.signposts
    # a confirmed override with numbers switched on can proceed; a signal never can
    await profile(uow, alice, ed_history=True, numbers_free=False)
    allowed = await safety.check_targets(
        uow(),
        alice,
        safety.TargetProposal(Goal.LOSE, D("0.5"), calories_kcal=1500, confirm_ed_override=True),
        now=NOW,
    )
    assert allowed.goal is Goal.LOSE and not allowed.suspended
    blocked = await safety.check_targets(
        uow(), alice, safety.TargetProposal(Goal.LOSE, D("0.5"), calories_kcal=1500), now=NOW
    )
    assert blocked.suspended
    for minutes in range(1, 5):
        await weigh(uow, alice, "80.1", NOW - timedelta(minutes=minutes))
    signalled = await safety.check_targets(
        uow(),
        alice,
        safety.TargetProposal(Goal.LOSE, D("0.5"), calories_kcal=1500, confirm_ed_override=True),
        now=NOW,
    )
    assert signalled.suspended and ReasonCode.SUSPENDED_ED_SIGNAL in signalled.reasons


def test_precheck_wraps_the_red_flags() -> None:
    flag = safety.precheck_message("I have chest pain")
    assert flag is not None and "995" in flag.text
    assert safety.precheck_message("chest day") is None


# --- over HTTP ----------------------------------------------------------------------------------


async def test_the_profile_response_carries_the_safety_block(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await owner.send("POST", "/api/health/consent")
    put = await owner.send(
        "PUT",
        "/api/health/profile",
        {"birth_year": 2015, "goal": "lose", "target_rate_pct_per_week": "0.5"},
    )
    body = put.json()
    assert body["goal"] == "maintain" and body["target_rate_pct_per_week"] is None
    assert body["safety"]["gates"] == [
        {"name": "weight_loss", "allowed": False, "reason": "under_18"}
    ]
    assert body["safety"]["suspended"] is False and body["safety"]["signposts"] == []
    again = (await owner.get("/api/health/profile")).json()
    assert again["safety"]["gates"][0]["reason"] == "under_18"

    ed = (
        await owner.send("PUT", "/api/health/profile", {"birth_year": 1990, "ed_history": True})
    ).json()
    assert ed["numbers_free"] is True and ed["safety"]["suspended"] is True
    names = [s["name"] for s in ed["safety"]["signposts"]]
    assert names == ["SGH Eating Disorders Programme", "Samaritans of Singapore"]
    assert (
        ed["safety"]["gates"][0]["reason"] == "age_unknown"
        or ed["safety"]["gates"][0]["reason"] == "bmi_unknown"
    )
