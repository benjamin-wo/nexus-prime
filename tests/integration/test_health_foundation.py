"""Health foundation: samples, the profile and separate consents; the web API; and that one user
never sees or writes another's. Every name and figure is made up."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application import health_consent as consent_cases
from nexus.application.users import get_user, set_preferences
from nexus.domain.errors import Conflict, ConsentRequired, InvalidInput, NotFound
from nexus.domain.health import (
    WELLNESS_STATEMENT,
    ActivityLevel,
    ConsentScope,
    Goal,
    Sample,
    SampleKind,
    SampleSource,
    SampleUnit,
    Sex,
    UnitSystem,
)
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import health_consents, health_profiles, health_samples
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory
from tests.integration.test_web_api import MEMBER, OWNER, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

D = Decimal
WEIGHT = SampleKind.WEIGHT


async def consenting(uow: UowFactory, user: UserId) -> UserId:
    await gym_cases.give_consent(uow(), user, now=NOW)
    return user


async def weigh(uow: UowFactory, user: UserId, kg: str, *, at: datetime = NOW, **extra: object):  # type: ignore[no-untyped-def]
    return await health_cases.log_sample(uow(), user, WEIGHT, D(kg), start_at=at, now=NOW, **extra)  # type: ignore[arg-type]


# --- consent ------------------------------------------------------------------------------------


async def test_every_write_needs_the_master_consent(uow: UowFactory, alice: UserId) -> None:
    sample_id = uuid4()
    writes = [
        health_cases.log_sample(uow(), alice, WEIGHT, D("80"), now=NOW),
        health_cases.edit_sample(uow(), alice, sample_id, {"value": D("81")}, now=NOW),
        health_cases.save_profile(uow(), alice, now=NOW),
        consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW),
    ]
    for write in writes:
        with pytest.raises(ConsentRequired):
            await write
    assert await health_cases.samples(uow(), alice, now=NOW) == []
    assert (await get_user(uow(), alice)).show_health is None  # nothing was written


async def test_a_source_needs_its_own_scope_and_typed_entries_do_not(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    await weigh(uow, alice, "80")  # typed: the master consent is enough
    await health_cases.log_sample(
        uow(),
        alice,
        WEIGHT,
        D("80"),
        source=SampleSource.CHAT,
        now=NOW,
        start_at=NOW - timedelta(days=1),
    )
    for source, extra in (
        (SampleSource.HEALTHKIT, {}),
        (SampleSource.HEALTH_CONNECT, {}),
        (SampleSource.OAUTH, {"source_name": "Withings"}),
    ):
        with pytest.raises(ConsentRequired):
            await health_cases.log_sample(
                uow(),
                alice,
                WEIGHT,
                D("80"),
                source=source,
                external_id="e1",
                now=NOW,
                **extra,  # type: ignore[arg-type]
            )

    await consent_cases.grant(uow(), alice, ConsentScope.SOURCE_HEALTHKIT, now=NOW)
    kit = await health_cases.log_sample(
        uow(), alice, SampleKind.STEPS, D("5000"), source=SampleSource.HEALTHKIT,
        external_id="e1", now=NOW,
    )  # fmt: skip
    assert kit.source is SampleSource.HEALTHKIT
    with pytest.raises(ConsentRequired):  # a different source's scope isn't borrowed
        await health_cases.log_sample(
            uow(), alice, WEIGHT, D("80"), source=SampleSource.HEALTH_CONNECT, now=NOW
        )

    # Withdrawing the scope stops new samples from it but keeps the stored ones.
    await consent_cases.withdraw(uow(), alice, ConsentScope.SOURCE_HEALTHKIT, now=NOW)
    with pytest.raises(ConsentRequired):
        await health_cases.log_sample(
            uow(), alice, SampleKind.STEPS, D("6000"), source=SampleSource.HEALTHKIT,
            external_id="e2", now=NOW,
        )  # fmt: skip
    assert len(await health_cases.samples(uow(), alice, SampleKind.STEPS, now=NOW)) == 1


async def test_scopes_need_the_master_and_withdrawing_it_closes_them_all(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    first = await consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    again = await consent_cases.grant(
        uow(), alice, ConsentScope.AI_PROCESSING, now=NOW + timedelta(days=1)
    )
    assert first.active and again.granted_at == NOW  # the first date is kept

    gone = await consent_cases.withdraw(
        uow(), alice, ConsentScope.AI_PROCESSING, now=NOW + timedelta(days=2)
    )
    assert not gone.active and gone.withdrawn_at == NOW + timedelta(days=2)
    back = await consent_cases.grant(
        uow(), alice, ConsentScope.AI_PROCESSING, now=NOW + timedelta(days=3)
    )
    assert back.active and back.granted_at == NOW + timedelta(days=3) and not back.withdrawn_at
    never = await consent_cases.withdraw(uow(), alice, ConsentScope.MODEL_IMPROVEMENT, now=NOW)
    assert never.granted_at is None and not never.active

    overview = await consent_cases.overview(uow(), alice)
    assert overview.health_at == NOW
    assert [s.scope for s in overview.scopes] == list(ConsentScope)
    assert {s.scope for s in overview.scopes if s.active} == {ConsentScope.AI_PROCESSING}


async def test_the_ai_gate_needs_the_master_and_the_ai_scope_both_active(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    assert not await consent_cases.may_send_to_ai(uow(), alice)
    await consenting(uow, alice)
    assert not await consent_cases.may_send_to_ai(uow(), alice)  # master alone isn't enough
    await consent_cases.grant(uow(), alice, ConsentScope.SOURCE_HEALTHKIT, now=NOW)
    assert not await consent_cases.may_send_to_ai(uow(), alice)  # nor another scope
    await consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    assert await consent_cases.may_send_to_ai(uow(), alice)
    assert not await consent_cases.may_send_to_ai(uow(), bob)  # consent is per user

    await consent_cases.withdraw(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    assert not await consent_cases.may_send_to_ai(uow(), alice)
    await consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    await gym_cases.withdraw_consent(uow(), alice)  # the master consent closes it too
    assert not await consent_cases.may_send_to_ai(uow(), alice)


# --- samples ------------------------------------------------------------------------------------


async def test_a_sample_round_trips_with_its_unit_and_turns_health_on(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await consenting(uow, alice)
    await consenting(uow, bob)
    await set_preferences(uow(), bob, show_health=False)
    assert (await get_user(uow(), alice)).show_health is None
    logged = await health_cases.log_sample(
        uow(), alice, WEIGHT, D("176.4"), unit=SampleUnit.LB, now=NOW
    )
    assert (logged.unit, logged.value, logged.start_at, logged.end_at) == (
        SampleUnit.LB, D("176.400"), NOW, NOW,
    )  # fmt: skip
    assert (await get_user(uow(), alice)).show_health is True
    await weigh(uow, bob, "70")
    assert (await get_user(uow(), bob)).show_health is False  # their own choice sticks

    [stored] = await health_cases.samples(uow(), alice, WEIGHT, now=NOW)
    assert stored == logged and stored.weight_kg == D("176.4") * Decimal("0.45359237")
    latest = await health_cases.latest(uow(), alice, WEIGHT, now=NOW)
    assert latest == logged
    assert await health_cases.latest(uow(), alice, SampleKind.HRV, now=NOW) is None


async def test_validation_errors_leave_nothing_behind(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    for kind, value, unit in (
        (WEIGHT, "19", None),
        (WEIGHT, "401", None),
        (SampleKind.BODY_FAT, "1.9", None),
        (SampleKind.BODY_FAT, "71", None),
        (WEIGHT, "80", SampleUnit.BPM),
    ):
        with pytest.raises(InvalidInput):
            await health_cases.log_sample(uow(), alice, kind, D(value), unit=unit, now=NOW)
    with pytest.raises(InvalidInput, match="future"):
        await weigh(uow, alice, "80", at=NOW + timedelta(days=3))
    assert await health_cases.samples(uow(), alice, now=NOW) == []
    assert (await get_user(uow(), alice)).show_health is None


async def test_a_typed_entry_for_the_same_moment_replaces_the_value(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    first = await weigh(uow, alice, "80")
    second = await weigh(uow, alice, "79.5")
    chat = await health_cases.log_sample(
        uow(), alice, WEIGHT, D("79"), start_at=NOW, source=SampleSource.CHAT, now=NOW
    )
    assert first.id == second.id == chat.id
    [only] = await health_cases.samples(uow(), alice, WEIGHT, now=NOW)
    assert only.value == D("79.000")
    other_kind = await health_cases.log_sample(
        uow(), alice, SampleKind.BODY_FAT, D("20"), start_at=NOW, now=NOW
    )
    assert other_kind.id != first.id  # another kind at the same moment is its own entry
    await weigh(uow, alice, "78", at=NOW - timedelta(days=1))  # another moment too
    assert len(await health_cases.samples(uow(), alice, WEIGHT, now=NOW)) == 2


async def test_an_imported_sample_updates_by_source_and_external_id(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    for user in (alice, bob):
        await consenting(uow, user)
        await consent_cases.grant(uow(), user, ConsentScope.SOURCE_HEALTHKIT, now=NOW)
        await consent_cases.grant(uow(), user, ConsentScope.SOURCE_HEALTH_CONNECT, now=NOW)

    async def steps(user: UserId, count: str, source: SampleSource, external: str | None):  # type: ignore[no-untyped-def]
        return await health_cases.log_sample(
            uow(), user, SampleKind.STEPS, D(count), source=source, external_id=external,
            start_at=NOW, end_at=NOW + timedelta(hours=1), now=NOW,
        )  # fmt: skip

    first = await steps(alice, "1000", SampleSource.HEALTHKIT, "x1")
    again = await steps(alice, "1500", SampleSource.HEALTHKIT, "x1")  # a sync repeats itself
    assert again.id == first.id and again.value == D("1500.000")
    assert again.created_at == first.created_at
    assert (await steps(alice, "900", SampleSource.HEALTH_CONNECT, "x1")).id != first.id
    assert (await steps(alice, "800", SampleSource.HEALTHKIT, "x2")).id != first.id
    assert (await steps(bob, "700", SampleSource.HEALTHKIT, "x1")).id != first.id  # per user
    await steps(alice, "10", SampleSource.HEALTHKIT, None)  # no key: nothing to match
    await steps(alice, "20", SampleSource.HEALTHKIT, None)
    assert len(await health_cases.samples(uow(), alice, SampleKind.STEPS, now=NOW)) == 5
    assert len(await health_cases.samples(uow(), bob, SampleKind.STEPS, now=NOW)) == 1


async def test_two_oauth_brands_with_the_same_external_id_do_not_collide(
    uow: UowFactory, alice: UserId
) -> None:
    await consenting(uow, alice)
    await consent_cases.grant(uow(), alice, ConsentScope.SOURCE_OAUTH, now=NOW)

    async def brand(name: str, count: str) -> Sample:
        return await health_cases.log_sample(
            uow(), alice, SampleKind.STEPS, D(count), source=SampleSource.OAUTH,
            source_name=name, external_id="same", now=NOW,
        )  # fmt: skip

    a = await brand("Withings", "100")
    b = await brand("Oura", "200")
    assert a.id != b.id
    again = await brand("Withings", "150")  # the same brand's repeat updates its own row
    assert again.id == a.id and again.value == D("150.000")
    assert {s.source_name for s in await health_cases.samples(uow(), alice, now=NOW)} == {
        "Withings",
        "Oura",
    }


async def test_edit_and_delete(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    await consent_cases.grant(uow(), alice, ConsentScope.SOURCE_HEALTHKIT, now=NOW)
    mine = await weigh(uow, alice, "80")
    other = await weigh(uow, alice, "81", at=NOW - timedelta(days=1))
    edited = await health_cases.edit_sample(
        uow(), alice, mine.id, {"value": D("176"), "unit": SampleUnit.LB}, now=NOW
    )
    assert (edited.value, edited.unit, edited.source) == (D("176.000"), SampleUnit.LB, mine.source)
    moved = await health_cases.edit_sample(
        uow(), alice, mine.id, {"start_at": NOW - timedelta(hours=2)}, now=NOW
    )
    assert moved.start_at == moved.end_at == NOW - timedelta(hours=2)
    with pytest.raises(Conflict):
        await health_cases.edit_sample(uow(), alice, mine.id, {"start_at": other.start_at}, now=NOW)
    with pytest.raises(InvalidInput):
        await health_cases.edit_sample(uow(), alice, mine.id, {"value": D("900")}, now=NOW)
    with pytest.raises(InvalidInput):
        await health_cases.edit_sample(uow(), alice, mine.id, {"kind": "hrv"}, now=NOW)
    with pytest.raises(InvalidInput):
        await health_cases.edit_sample(uow(), alice, mine.id, {}, now=NOW)
    with pytest.raises(NotFound):
        await health_cases.edit_sample(uow(), alice, uuid4(), {"value": D("80")}, now=NOW)

    imported = await health_cases.log_sample(
        uow(), alice, SampleKind.STEPS, D("500"), source=SampleSource.HEALTHKIT,
        external_id="s1", now=NOW,
    )  # fmt: skip
    with pytest.raises(InvalidInput, match="where they came from"):
        await health_cases.edit_sample(uow(), alice, imported.id, {"value": D("600")}, now=NOW)

    # Deleting never needs consent, for any source.
    await gym_cases.withdraw_consent(uow(), alice)
    await health_cases.delete_sample(uow(), alice, imported.id, now=NOW)
    await health_cases.delete_sample(uow(), alice, other.id, now=NOW)
    with pytest.raises(NotFound):
        await health_cases.delete_sample(uow(), alice, other.id, now=NOW)
    assert [s.id for s in await health_cases.samples(uow(), alice, now=NOW)] == [mine.id]


async def test_samples_by_range_kind_and_newest_first(uow: UowFactory, alice: UserId) -> None:
    await consenting(uow, alice)
    for days, kg in ((0, "80"), (10, "81"), (40, "82")):
        await weigh(uow, alice, kg, at=NOW - timedelta(days=days))
    await health_cases.log_sample(uow(), alice, SampleKind.BODY_FAT, D("20"), now=NOW)

    recent = await health_cases.samples(uow(), alice, WEIGHT, now=NOW)  # the last 30 days
    assert [s.value for s in recent] == [D("80.000"), D("81.000")]
    wide = await health_cases.samples(
        uow(), alice, WEIGHT, start=NOW - timedelta(days=60), end=NOW + timedelta(days=1), now=NOW
    )
    assert [s.value for s in wide] == [D("80.000"), D("81.000"), D("82.000")]
    assert len(await health_cases.samples(uow(), alice, now=NOW)) == 3  # any kind
    assert len(await health_cases.samples(uow(), alice, WEIGHT, limit=1, now=NOW)) == 1
    with pytest.raises(InvalidInput):
        await health_cases.samples(uow(), alice, start=NOW, end=NOW - timedelta(days=1), now=NOW)
    # The latest is as of now: a sample logged for tomorrow doesn't count yet.
    await weigh(uow, alice, "90", at=NOW + timedelta(hours=5))
    latest = await health_cases.latest(uow(), alice, WEIGHT, now=NOW)
    assert latest is not None and latest.value == D("80.000")


# --- the profile --------------------------------------------------------------------------------


async def test_the_profile_is_one_row_per_user_and_numbers_follow_ed_history(
    uow: UowFactory, alice: UserId
) -> None:
    assert await health_cases.profile(uow(), alice, now=NOW) is None
    await consenting(uow, alice)
    saved = await health_cases.save_profile(
        uow(), alice, sex_for_equations=Sex.FEMALE, birth_year=1990, height_cm=D("168.25"),
        activity_level=ActivityLevel.LIGHT, goal=Goal.LOSE,
        target_rate_pct_per_week=D("0.5"), unit_system=UnitSystem.IMPERIAL, now=NOW,
    )  # fmt: skip
    assert (saved.height_cm, saved.numbers_free, saved.ed_history) == (D("168.3"), False, False)
    assert await health_cases.profile(uow(), alice, now=NOW) == saved
    assert (await get_user(uow(), alice)).show_health is True

    careful = await health_cases.save_profile(uow(), alice, ed_history=True, now=NOW)
    assert careful.numbers_free is True  # follows ed_history
    assert careful.birth_year is None and careful.goal is Goal.MAINTAIN  # a full replace
    explicit = await health_cases.save_profile(
        uow(), alice, ed_history=True, numbers_free=False, now=NOW
    )
    assert explicit.numbers_free is False
    with pytest.raises(InvalidInput):
        await health_cases.save_profile(uow(), alice, birth_year=1800, now=NOW)
    assert (await health_cases.profile(uow(), alice, now=NOW)) == explicit  # a refusal kept it


# --- isolation ----------------------------------------------------------------------------------


async def test_one_user_never_sees_or_writes_anothers_data(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await consenting(uow, alice)
    await consenting(uow, bob)
    await consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    mine = await weigh(uow, alice, "80")
    await health_cases.save_profile(uow(), alice, birth_year=1990, now=NOW)

    assert await health_cases.samples(uow(), bob, now=NOW) == []
    assert await health_cases.latest(uow(), bob, WEIGHT, now=NOW) is None
    assert await health_cases.profile(uow(), bob, now=NOW) is None
    assert not await consent_cases.may_send_to_ai(uow(), bob)
    assert not any(s.active for s in (await consent_cases.overview(uow(), bob)).scopes)
    with pytest.raises(NotFound):
        await health_cases.edit_sample(uow(), bob, mine.id, {"value": D("1")}, now=NOW)
    with pytest.raises(NotFound):
        await health_cases.delete_sample(uow(), bob, mine.id, now=NOW)
    # Bob's entry for the same moment is his own, not alice's.
    theirs = await weigh(uow, bob, "60")
    assert theirs.id != mine.id
    assert [s.value for s in await health_cases.samples(uow(), alice, WEIGHT, now=NOW)] == [
        D("80.000")
    ]


async def test_the_database_itself_hides_rows_and_refuses_cross_user_writes(
    uow: UowFactory, alice: UserId, bob: UserId, engine: AsyncEngine
) -> None:
    await consenting(uow, alice)
    await consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    await weigh(uow, alice, "80")
    await health_cases.save_profile(uow(), alice, now=NOW)

    async with engine.connect() as db:
        async with db.begin() as transaction:
            await db.execute(text("SELECT set_config('app.user_id', :id, true)"), {"id": str(bob)})
            for table in (health_samples, health_profiles, health_consents):
                assert await db.scalar(select(func.count()).select_from(table)) == 0
            with pytest.raises(DBAPIError):
                await db.execute(
                    health_consents.insert().values(
                        user_id=alice, scope="model_improvement", granted_at=NOW
                    )
                )
            await transaction.rollback()

    async with engine.connect() as db:  # the table's own checks and keys, whoever asks
        base = {
            "user_id": alice, "kind": "weight", "value": D("80"), "unit": "kg",
            "start_at": NOW, "end_at": NOW, "source": "manual", "created_at": NOW,
        }  # fmt: skip
        bad = (
            {"id": uuid4(), **base, "kind": "mood"},
            {"id": uuid4(), **base, "end_at": NOW - timedelta(seconds=1)},
            {"id": uuid4(), **base, "source": "oauth"},  # a brand needs its name
            {"id": uuid4(), **base, "start_at": NOW},  # same moment as alice's typed weight
        )
        for values in bad:
            async with db.begin() as transaction:
                with pytest.raises(IntegrityError):
                    await db.execute(health_samples.insert().values(**values))
                await transaction.rollback()


# --- the web API --------------------------------------------------------------------------------


async def test_health_body_endpoints_need_a_session(world: World) -> None:
    anonymous = world.browser()
    for method, path in (
        ("GET", "/api/health/samples"),
        ("GET", "/api/health/samples/latest?kind=weight"),
        ("POST", "/api/health/samples"),
        ("GET", "/api/health/profile"),
        ("PUT", "/api/health/profile"),
        ("GET", "/api/health/consents"),
        ("PUT", "/api/health/consents/ai_processing"),
        ("DELETE", "/api/health/consents/ai_processing"),
    ):
        response = await anonymous.send(method, path, {} if method in ("POST", "PUT") else None)
        assert response.status_code in (401, 403), path


async def test_consents_over_http(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    shown = (await owner.get("/api/health/consents")).json()
    assert shown["health_consented_at"] is None
    assert [s["scope"] for s in shown["scopes"]] == [s.value for s in ConsentScope]
    assert not any(s["active"] for s in shown["scopes"])
    assert shown["wellness_statement"] == WELLNESS_STATEMENT
    assert shown["ai_provider"] == {"name": "Google (Gemini)", "country": "United States"}

    refused = await owner.send("PUT", "/api/health/consents/ai_processing")
    assert refused.status_code == 403 and "agree" in refused.json()["detail"]
    assert (await owner.send("POST", "/api/health/consent")).status_code == 201
    granted = await owner.send("PUT", "/api/health/consents/source:healthkit")
    assert granted.status_code == 200
    assert granted.json()["scope"] == "source:healthkit" and granted.json()["active"] is True
    assert (await owner.send("PUT", "/api/health/consents/nope")).status_code == 404

    states = {s["scope"]: s for s in (await owner.get("/api/health/consents")).json()["scopes"]}
    assert states["source:healthkit"]["active"] and not states["ai_processing"]["active"]
    gone = await owner.send("DELETE", "/api/health/consents/source:healthkit")
    assert gone.status_code == 200 and gone.json()["active"] is False
    assert gone.json()["withdrawn_at"] is not None
    assert (await owner.send("DELETE", "/api/health/consents/nope")).status_code == 404
    no_csrf = await owner.send(
        "PUT", "/api/health/consents/ai_processing", **{"X-CSRF-Token": "wrong"}
    )
    assert no_csrf.status_code == 403


async def test_samples_and_profile_over_http(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    body = {"kind": "weight", "value": "80.5"}
    refused = await owner.send("POST", "/api/health/samples", body)
    assert refused.status_code == 403
    assert (await owner.get("/api/health/samples")).json() == []  # reading is fine
    assert (await owner.get("/api/health/profile")).json() is None
    assert (await owner.get("/api/health/samples/latest?kind=weight")).json() is None
    await owner.send("POST", "/api/health/consent")

    made = await owner.send("POST", "/api/health/samples", body)
    assert made.status_code == 201
    sample = made.json()
    assert (sample["value"], sample["unit"], sample["source"]) == ("80.500", "kg", "manual")
    assert sample["value_kg"] == "80.50" and sample["start_at"] == sample["end_at"]
    pounds = await owner.send(
        "POST",
        "/api/health/samples",
        {"kind": "weight", "value": "176,4", "unit": "lb", "start_at": "2020-01-01T08:00:00Z"},
    )
    assert pounds.status_code == 201, pounds.json()
    assert pounds.json()["value_kg"] == "80.01"  # converted in code, shown to two places
    assert (await owner.get("/api/me")).json()["preferences"]["show_health"] is True

    listed = (await owner.get("/api/health/samples?kind=weight")).json()
    assert listed[0]["id"] == sample["id"]  # newest first
    latest = (await owner.get("/api/health/samples/latest?kind=weight")).json()
    assert latest["id"] == sample["id"]

    assert (
        await owner.send("POST", "/api/health/samples", {**body, "value": "19"})
    ).status_code == 422
    assert (
        await owner.send("POST", "/api/health/samples", {**body, "value": "abc"})
    ).status_code == 422
    assert (
        await owner.send("POST", "/api/health/samples", {**body, "unit": "bpm"})
    ).status_code == 422
    assert (await owner.send("POST", "/api/health/samples", {**body, "x": 1})).status_code == 422
    healthkit = await owner.send(
        "POST", "/api/health/samples", {"kind": "steps", "value": "100", "source": "healthkit"}
    )
    assert healthkit.status_code == 403 and "healthkit" in healthkit.json()["detail"]

    path = f"/api/health/samples/{sample['id']}"
    patched = await owner.send("PATCH", path, {"value": "79"})
    assert patched.status_code == 200 and patched.json()["value"] == "79.000"
    assert (await owner.send("PATCH", path, {"value": None})).status_code == 422
    assert (await owner.send("PATCH", path, {})).status_code == 422
    assert (await owner.send("PATCH", path, {"value": "500"})).status_code == 422
    assert (
        await owner.send("PATCH", "/api/health/samples/nope", {"value": "79"})
    ).status_code == 404

    saved = await owner.send(
        "PUT",
        "/api/health/profile",
        {
            "sex_for_equations": "female", "birth_year": 1990, "height_cm": "168.25",
            "activity_level": "light", "goal": "lose", "target_rate_pct_per_week": "0.5",
            "ed_history": True, "unit_system": "imperial",
        },
    )  # fmt: skip
    assert saved.status_code == 200
    assert (saved.json()["numbers_free"], saved.json()["height_cm"]) == (True, "168.3")
    assert (await owner.get("/api/health/profile")).json()["goal"] == "lose"
    assert (await owner.send("PUT", "/api/health/profile", {"birth_year": 1700})).status_code == 422
    assert (await owner.send("PUT", "/api/health/profile", {"goal": "bulk"})).status_code == 422

    assert (await owner.send("DELETE", path)).status_code == 204
    assert (await owner.send("DELETE", path)).status_code == 404


async def test_two_users_over_http_never_meet(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite=invite)).status_code == 200
    for who in (owner, member):
        assert (await who.send("POST", "/api/health/consent")).status_code == 201
    assert (await owner.send("PUT", "/api/health/consents/ai_processing")).status_code == 200

    made = (
        await owner.send("POST", "/api/health/samples", {"kind": "weight", "value": "80"})
    ).json()
    await owner.send("PUT", "/api/health/profile", {"birth_year": 1990})

    assert (await member.get("/api/health/samples")).json() == []
    assert (await member.get("/api/health/samples/latest?kind=weight")).json() is None
    assert (await member.get("/api/health/profile")).json() is None
    assert not any(s["active"] for s in (await member.get("/api/health/consents")).json()["scopes"])
    path = f"/api/health/samples/{made['id']}"
    assert (await member.send("PATCH", path, {"value": "1"})).status_code == 404
    assert (await member.send("DELETE", path)).status_code == 404
    # The same moment is each user's own entry.
    theirs = await member.send(
        "POST",
        "/api/health/samples",
        {"kind": "weight", "value": "60", "start_at": made["start_at"]},
    )
    assert theirs.status_code == 201 and theirs.json()["id"] != made["id"]
    assert (await owner.get("/api/health/samples")).json()[0]["value"] == "80.000"

    await member.send("DELETE", "/api/health/consent")  # the member's consent is their own
    assert (await owner.get("/api/health/consents")).json()["health_consented_at"] is not None
