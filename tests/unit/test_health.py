"""Health foundation rules: sample validation and units, profile checks, consent rules.
Every name and figure is made up."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from nexus.domain.errors import ConsentRequired, InvalidInput
from nexus.domain.gym_training import LB_IN_KG
from nexus.domain.health import (
    KIND_UNITS,
    WELLNESS_STATEMENT,
    ConsentScope,
    Goal,
    HealthProfile,
    Sample,
    SampleKind,
    SampleSource,
    SampleUnit,
    Sex,
    UnitSystem,
    check_consent,
    clean_unit,
    edited,
    provider_disclosure,
    scope_for,
)
from nexus.domain.ledger import UserId

USER = UserId(uuid4())
T0 = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)
D = Decimal


def sample(
    kind: SampleKind = SampleKind.WEIGHT,
    value: str = "80",
    unit: SampleUnit | None = None,
    *,
    start_at: datetime = T0,
    end_at: datetime = T0,
    source: SampleSource = SampleSource.MANUAL,
    source_name: str | None = None,
    external_id: str | None = None,
) -> Sample:
    return Sample(
        uuid4(),
        USER,
        kind,
        D(value),
        unit or clean_unit(kind, None),
        start_at,
        end_at,
        source,
        T0,
        source_name,
        external_id,
    )


def test_every_kind_has_units_and_a_default_among_them() -> None:
    assert set(KIND_UNITS) == set(SampleKind)
    for kind in SampleKind:
        assert clean_unit(kind, None) in KIND_UNITS[kind]
    assert clean_unit(SampleKind.WEIGHT, SampleUnit.LB) is SampleUnit.LB


@pytest.mark.parametrize(
    ("kind", "unit"),
    [
        (SampleKind.WEIGHT, SampleUnit.PERCENT),
        (SampleKind.HRV, SampleUnit.BPM),
        (SampleKind.SLEEP, SampleUnit.KCAL),
        (SampleKind.STEPS, SampleUnit.KG),
    ],
)
def test_a_unit_must_suit_the_kind(kind: SampleKind, unit: SampleUnit) -> None:
    with pytest.raises(InvalidInput, match="measured in"):
        sample(kind, "50", unit)


@pytest.mark.parametrize(
    ("kind", "low", "high"),
    [
        (SampleKind.WEIGHT, "20", "400"),
        (SampleKind.BODY_FAT, "2", "70"),
        (SampleKind.STEPS, "0", "200000"),
        (SampleKind.ACTIVE_ENERGY, "0", "20000"),
        (SampleKind.RESTING_HEART_RATE, "20", "250"),
        (SampleKind.HRV, "1", "500"),
        (SampleKind.SLEEP, "1", "1440"),
        (SampleKind.WORKOUT, "1", "1440"),
    ],
)
def test_bounds_are_inclusive_per_kind(kind: SampleKind, low: str, high: str) -> None:
    assert sample(kind, low).value == D(low)
    assert sample(kind, high).value == D(high)
    for out in (D(low) - 1, D(high) + 1):
        with pytest.raises(InvalidInput, match="expected"):
            sample(kind, str(out))


def test_weight_bounds_apply_in_kilograms_whatever_the_unit() -> None:
    assert sample(value="44.1", unit=SampleUnit.LB)  # 20.0 kg
    with pytest.raises(InvalidInput):
        sample(value="44", unit=SampleUnit.LB)  # 19.96 kg
    assert sample(value="880", unit=SampleUnit.LB)  # 399.2 kg
    with pytest.raises(InvalidInput):
        sample(value="890", unit=SampleUnit.LB)  # 403.7 kg


def test_a_weight_keeps_its_unit_and_converts_with_gyms_rule() -> None:
    pounds = sample(value="176.4", unit=SampleUnit.LB)
    assert pounds.value == D("176.4") and pounds.unit is SampleUnit.LB
    assert pounds.weight_kg == D("176.4") * LB_IN_KG
    assert sample(value="80").weight_kg == D("80")
    assert sample(SampleKind.STEPS, "100").weight_kg is None


def test_values_must_be_finite_numbers_and_steps_whole() -> None:
    for bad in ("NaN", "Infinity"):
        with pytest.raises(InvalidInput):
            sample(value=bad)
    with pytest.raises(InvalidInput, match="whole"):
        sample(SampleKind.STEPS, "10.5")
    assert sample(value="80.12345").value == D("80.123")


def test_times_need_a_zone_and_an_order() -> None:
    with pytest.raises(InvalidInput, match="time zone"):
        sample(start_at=datetime(2026, 11, 24, 8), end_at=datetime(2026, 11, 24, 8))
    with pytest.raises(InvalidInput, match="before it starts"):
        sample(end_at=T0 - timedelta(minutes=1))
    with pytest.raises(InvalidInput, match="span"):
        sample(SampleKind.SLEEP, "60", end_at=T0 + timedelta(days=40))
    assert sample(SampleKind.SLEEP, "450", end_at=T0 + timedelta(hours=8)).end_at > T0


def test_source_name_goes_with_oauth_only() -> None:
    brand = sample(source=SampleSource.OAUTH, source_name="  Withings ", external_id="w-1")
    assert brand.source_name == "Withings"
    with pytest.raises(InvalidInput, match="source name"):
        sample(source=SampleSource.OAUTH)
    with pytest.raises(InvalidInput, match="source name"):
        sample(source=SampleSource.HEALTHKIT, source_name="Withings")


def test_typed_and_chat_entries_have_no_external_id() -> None:
    for source in (SampleSource.MANUAL, SampleSource.CHAT):
        with pytest.raises(InvalidInput, match="external id"):
            sample(source=source, external_id="x")
    kit = sample(source=SampleSource.HEALTHKIT, external_id=" abc ")
    assert kit.external_id == "abc" and not kit.is_manual
    assert sample(source=SampleSource.HEALTHKIT, external_id="  ").external_id is None


def test_an_edit_is_validated_again_and_a_point_moves_whole() -> None:
    original = sample()
    moved = edited(original, start_at=T0 + timedelta(hours=1))
    assert moved.start_at == moved.end_at == T0 + timedelta(hours=1)
    span = sample(SampleKind.SLEEP, "60", end_at=T0 + timedelta(hours=1))
    assert edited(span, start_at=T0 - timedelta(hours=1)).end_at == span.end_at
    with pytest.raises(InvalidInput):
        edited(original, value=D("500"))
    with pytest.raises(InvalidInput):
        edited(original, unit=SampleUnit.BPM)


def test_the_dedupe_key_parts_are_what_the_database_enforces() -> None:
    a = sample(source=SampleSource.HEALTHKIT, external_id="e1")
    b = replace(a, id=uuid4(), value=D("81"))
    assert (a.user_id, a.source, a.external_id) == (b.user_id, b.source, b.external_id)
    assert sample().is_manual and sample(source=SampleSource.CHAT).is_manual


# --- profile ------------------------------------------------------------------------------------


def profile(**changes: object) -> HealthProfile:
    base = HealthProfile(
        USER, Sex.UNSPECIFIED, 1990, D("175"), None, Goal.MAINTAIN, None, False, False,
        UnitSystem.METRIC, T0,
    )  # fmt: skip
    return replace(base, **changes).check(this_year=2026)  # type: ignore[arg-type]


def test_a_profile_checks_its_figures_and_rounds_them() -> None:
    assert profile(height_cm=D("175.46")).height_cm == D("175.5")
    assert profile(target_rate_pct_per_week=D("0.456")).target_rate_pct_per_week == D("0.46")
    assert profile(birth_year=None, height_cm=None).birth_year is None
    for bad in ({"birth_year": 1899}, {"birth_year": 2027}, {"height_cm": D("30")},
                {"height_cm": D("300")}, {"target_rate_pct_per_week": D("-1")},
                {"target_rate_pct_per_week": D("4")}, {"height_cm": D("NaN")}):  # fmt: skip
        with pytest.raises(InvalidInput):
            profile(**bad)


# --- consent ------------------------------------------------------------------------------------


def test_each_outside_source_needs_its_own_scope_and_typed_ones_none() -> None:
    assert scope_for(SampleSource.MANUAL) is None and scope_for(SampleSource.CHAT) is None
    assert scope_for(SampleSource.HEALTHKIT) is ConsentScope.SOURCE_HEALTHKIT
    assert scope_for(SampleSource.HEALTH_CONNECT) is ConsentScope.SOURCE_HEALTH_CONNECT
    assert scope_for(SampleSource.OAUTH) is ConsentScope.SOURCE_OAUTH


def test_check_consent_needs_the_master_and_the_scope() -> None:
    none: frozenset[ConsentScope] = frozenset()
    kit = frozenset({ConsentScope.SOURCE_HEALTHKIT})
    check_consent(T0, none, None)
    check_consent(T0, kit, ConsentScope.SOURCE_HEALTHKIT)
    with pytest.raises(ConsentRequired):
        check_consent(None, kit, ConsentScope.SOURCE_HEALTHKIT)  # scope alone isn't enough
    with pytest.raises(ConsentRequired):
        check_consent(None, none, None)
    with pytest.raises(ConsentRequired, match="source:healthkit"):
        check_consent(T0, none, ConsentScope.SOURCE_HEALTHKIT)


def test_the_statement_and_provider_disclosure() -> None:
    assert WELLNESS_STATEMENT.startswith("This product is not intended to diagnose")
    assert WELLNESS_STATEMENT.endswith("qualified healthcare professional.")
    assert provider_disclosure("gemini", None, None) == ("Google (Gemini)", "United States")
    assert provider_disclosure("gemini", "Acme AI", "Singapore") == ("Acme AI", "Singapore")
    assert provider_disclosure("openrouter", None, "Germany") == (
        "OpenRouter (routes to the model's provider)",
        "Germany",
    )
    assert provider_disclosure("other", None, None) == ("other", "unknown")
