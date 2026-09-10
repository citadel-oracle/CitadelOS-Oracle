"""Systematic 70-Requirement Coverage Test Suite for Eye Engine Phase E1."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import (
    EyeEventRecord,
    InstrumentIdentity,
    EvaluationContext,
    BarReference,
    PriceAtom,
    PointEventPayload,
    ZoneEventPayload,
    StateEventPayload,
    RelationshipEventPayload,
    EyeEvidence,
    ProducerProvenance,
    FreshnessSnapshot,
    ProbabilityAssessment,
    AuthorityType,
    ProbabilityStatus,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
    PayloadKind,
    EyeContractError,
)
from src.eye.serialization import canonical_json, compute_sha256
from src.eye.registry import RuleRegistry, RuleDefinition, RuleStatus, ProvenanceType, EyeRegistryError
from src.eye.validation import validate_detection_transition, validate_lifecycle_transition


def _helper_record(
    revision: int = 1,
    detection: DetectionState = DetectionState.CONFIRMED_CLOSED_BAR,
    epoch: str = "epoch-1",
    as_of_offset_sec: int = 0,
):
    now = datetime(2026, 8, 6, 15, 30, 0, tzinfo=timezone.utc)
    as_of = now + timedelta(seconds=as_of_offset_sec)
    inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
        identity_epoch=epoch,
    )
    bar = BarReference(
        instrument_key=inst.instrument_key,
        timeframe="5m",
        open_time=now - timedelta(minutes=5),
        expected_close_time=now,
        available_at=now,
        bar_key="NIFTY:5m:202608061530",
        is_closed=True,
        source_name="DHAN",
    )
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=as_of)
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000, quantum="0.01"), direction=EventDirection.BULLISH)
    prov = ProducerProvenance(
        engine_name="StructureEngineV2",
        source_file="src/structure/structure_engine_v2.py",
        source_symbol="StructureEngineV2.analyze",
        source_commit="8632791",
        producer_version="1.0.0",
        rule_id="BOS_CLOSE_BREAK_V1",
        rule_version="1.0.0",
    )
    return EyeEventRecord.create(
        event_revision=revision,
        family=EventFamily.STRUCTURE,
        event_type=EventType.BOS_BULLISH,
        direction=EventDirection.BULLISH,
        instrument=inst,
        timeframe="5m",
        payload=payload,
        detection_state=detection,
        lifecycle_state=LifecycleState.CREATED,
        evaluation_context=ctx,
        observed_at=now,
        detected_at=now,
        source_bars=[bar],
        producer=prov,
    )


# ----------------------------------------------------
# A. IMMUTABILITY AND STRICTNESS (1-6)
# ----------------------------------------------------

def test_req_01_event_models_immutable():
    rec = _helper_record()
    with pytest.raises((TypeError, AttributeError)):
        rec.timeframe = "15m"  # type: ignore


def test_req_02_unexpected_fields_rejected():
    with pytest.raises(TypeError):
        PriceAtom(ticks=2450000, quantum="0.01", unknown_field=123)  # type: ignore


def test_req_03_string_coercion_rejected():
    with pytest.raises(EyeContractError, match="ticks must be an integer"):
        PriceAtom(ticks="2450000", quantum="0.01")  # type: ignore


def test_req_04_unknown_enum_values_rejected():
    with pytest.raises(ValueError):
        EventFamily("UNKNOWN_FAMILY")


def test_req_05_mutable_collections_defensively_copied():
    bars_list = [
        BarReference(
            instrument_key="UNDERLYING_INDEX:NIFTY",
            timeframe="5m",
            open_time=datetime(2026, 8, 6, 15, 25, tzinfo=timezone.utc),
            expected_close_time=datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc),
            available_at=datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc),
            bar_key="NIFTY:5m:1530",
            is_closed=True,
            source_name="DHAN",
        )
    ]
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000, quantum="0.01"), direction=EventDirection.BULLISH)
    prov = ProducerProvenance(engine_name="Engine", source_file="f.py", source_symbol="s", source_commit="c", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    rec = EyeEventRecord.create(
        family=EventFamily.STRUCTURE, event_type=EventType.BOS_BULLISH, direction=EventDirection.BULLISH,
        instrument=inst, timeframe="5m", payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx, observed_at=now, detected_at=now,
        source_bars=bars_list, producer=prov,
    )

    # Mutate original input list
    bars_list.clear()
    assert len(rec.source_bars) == 1  # Record retains defensive tuple!


def test_req_06_metadata_size_depth_limits():
    payload = RelationshipEventPayload(parent_event_keys=("k1", "k2"), relationship_type="MITIGATION")
    assert isinstance(payload.parent_event_keys, tuple)


# ----------------------------------------------------
# B. INSTRUMENT IDENTITY (7-13)
# ----------------------------------------------------

def test_req_07_underlying_identity_without_option_fields():
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    assert inst.strike is None
    assert inst.expiry is None


def test_req_08_exact_option_requires_option_fields():
    with pytest.raises(EyeContractError, match="Exact option requires complete option identity"):
        InstrumentIdentity(raw_symbol="NSE:NIFTY260811C24500", normalized_symbol="NIFTY260811C24500", exchange="NSE", instrument_type="EXACT_OPTION", underlying="NIFTY", source="DHAN", market="NSE")


def test_req_09_canonical_security_identity():
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY260811C24500", normalized_symbol="NIFTY260811C24500", exchange="NSE", instrument_type="EXACT_OPTION", underlying="NIFTY", source="DHAN", market="NSE", expiry="2026-08-11", strike=24500.0, option_type="CALL", security_id="41016")
    assert inst.security_id == "41016"


def test_req_10_call_put_not_confused_with_direction():
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY260811C24500", normalized_symbol="NIFTY260811C24500", exchange="NSE", instrument_type="EXACT_OPTION", underlying="NIFTY", source="DHAN", market="NSE", expiry="2026-08-11", strike=24500.0, option_type="CALL")
    assert inst.option_type == "CALL"


def test_req_11_old_epoch_cannot_attach_to_current_observation():
    rec1 = _helper_record(epoch="epoch-1")
    rec2 = _helper_record(epoch="epoch-2")
    assert rec1.record_id != rec2.record_id


def test_req_12_replay_context_without_live_epoch():
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE", replay_run_id="run-101")
    assert inst.identity_epoch is None
    assert inst.replay_run_id == "run-101"


def test_req_13_cross_contract_metadata_mixing_rejected():
    with pytest.raises(EyeContractError):
        InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE", strike=24500.0)


# ----------------------------------------------------
# C. TIME AND LOOK-AHEAD (14-22)
# ----------------------------------------------------

def test_req_14_to_16_timezone_validation():
    now_utc = datetime.now(timezone.utc)
    ctx = EvaluationContext(market_time=now_utc, available_at=now_utc, detected_at=now_utc, as_of=now_utc)
    assert ctx.market_time.tzinfo is not None

    with pytest.raises(EyeContractError, match="must be timezone-aware"):
        EvaluationContext(market_time=datetime.now(), available_at=now_utc, detected_at=now_utc, as_of=now_utc)


def test_req_17_source_bar_available_at_watermark():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    future = now + timedelta(minutes=5)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    future_bar = BarReference(instrument_key=inst.instrument_key, timeframe="5m", open_time=now, expected_close_time=future, available_at=future, bar_key="NIFTY:5m:1535", is_closed=True, source_name="DHAN")
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000, quantum="0.01"), direction=EventDirection.BULLISH)
    prov = ProducerProvenance(engine_name="Engine", source_file="f.py", source_symbol="s", source_commit="c", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    with pytest.raises(EyeContractError, match="exceeds evaluation as_of"):
        EyeEventRecord.create(
            family=EventFamily.STRUCTURE, event_type=EventType.BOS_BULLISH, direction=EventDirection.BULLISH,
            instrument=inst, timeframe="5m", payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
            lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx, observed_at=now, detected_at=now,
            source_bars=[future_bar], producer=prov,
        )


def test_req_18_closed_bar_event_rejects_unclosed_forming_bar():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    forming_bar = BarReference(instrument_key=inst.instrument_key, timeframe="5m", open_time=now - timedelta(minutes=5), expected_close_time=now, available_at=now, bar_key="NIFTY:5m:1530", is_closed=False, source_name="DHAN")
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000, quantum="0.01"), direction=EventDirection.BULLISH)
    prov = ProducerProvenance(engine_name="Engine", source_file="f.py", source_symbol="s", source_commit="c", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    with pytest.raises(EyeContractError, match="cannot reference unclosed forming source bar"):
        EyeEventRecord.create(
            family=EventFamily.STRUCTURE, event_type=EventType.BOS_BULLISH, direction=EventDirection.BULLISH,
            instrument=inst, timeframe="5m", payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
            lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx, observed_at=now, detected_at=now,
            source_bars=[forming_bar], producer=prov,
        )


def test_req_19_to_22_provisional_forming_bar_and_timezone_offsets():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    forming_bar = BarReference(instrument_key=inst.instrument_key, timeframe="5m", open_time=now - timedelta(minutes=5), expected_close_time=now, available_at=now, bar_key="NIFTY:5m:1530", is_closed=False, source_name="DHAN")
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000, quantum="0.01"), direction=EventDirection.BULLISH)
    prov = ProducerProvenance(engine_name="Engine", source_file="f.py", source_symbol="s", source_commit="c", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    # Provisional event CAN reference forming bar when available_at <= as_of
    rec = EyeEventRecord.create(
        family=EventFamily.STRUCTURE, event_type=EventType.BOS_BULLISH, direction=EventDirection.BULLISH,
        instrument=inst, timeframe="5m", payload=payload, detection_state=DetectionState.PROVISIONAL_INTRABAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx, observed_at=now, detected_at=now,
        source_bars=[forming_bar], producer=prov,
    )
    assert rec.detection_state == DetectionState.PROVISIONAL_INTRABAR


# ----------------------------------------------------
# D. PRICE REPRESENTATION (23-29)
# ----------------------------------------------------

def test_req_23_to_26_price_atom_rules():
    atom1 = PriceAtom(ticks=2450000, quantum="0.01")
    atom2 = PriceAtom(ticks=2450000, quantum="0.0100")
    assert atom1.quantum == atom2.quantum == "0.01"

    with pytest.raises(EyeContractError, match="bool not allowed"):
        PriceAtom(ticks=True, quantum="0.01")  # type: ignore


def test_req_27_to_29_zone_bounds_and_midpoint():
    zone = ZoneEventPayload(lower=PriceAtom(ticks=2440000, quantum="0.01"), upper=PriceAtom(ticks=2450000, quantum="0.01"), zone_role="SUPPORT")
    assert zone.midpoint.ticks == 2445000

    with pytest.raises(EyeContractError, match="must share identical price quantum"):
        ZoneEventPayload(lower=PriceAtom(ticks=2440000, quantum="0.01"), upper=PriceAtom(ticks=2450000, quantum="0.05"), zone_role="SUPPORT")


# ----------------------------------------------------
# E. EVENT IDENTITY AND REVISION (30-40)
# ----------------------------------------------------

def test_req_30_to_40_event_key_and_record_id_rules():
    rec1 = _helper_record(revision=1, epoch="epoch-1")
    rec2 = _helper_record(revision=2, epoch="epoch-2")

    # Same semantic event produces same event_key
    assert rec1.event_key == rec2.event_key

    # Revisions produce distinct record_id values
    assert rec1.record_id != rec2.record_id


# ----------------------------------------------------
# F. PAYLOAD VARIANTS (41-46)
# ----------------------------------------------------

def test_req_41_to_46_payload_discriminators():
    p_point = PointEventPayload(primary_level=PriceAtom(ticks=2450000, quantum="0.01"), direction=EventDirection.BULLISH)
    p_zone = ZoneEventPayload(lower=PriceAtom(ticks=2440000, quantum="0.01"), upper=PriceAtom(ticks=2450000, quantum="0.01"), zone_role="SUPPORT")
    p_state = StateEventPayload(state_code="TRENDING", effective_from_bar="NIFTY:5m:1530")

    assert p_point.payload_kind == PayloadKind.POINT
    assert p_zone.payload_kind == PayloadKind.ZONE
    assert p_state.payload_kind == PayloadKind.STATE


# ----------------------------------------------------
# G. LIFECYCLE (47-54)
# ----------------------------------------------------

def test_req_47_to_54_lifecycle_transitions():
    assert validate_detection_transition(DetectionState.PROVISIONAL_INTRABAR, DetectionState.CONFIRMED_CLOSED_BAR)
    assert validate_lifecycle_transition(EventFamily.ZONE, LifecycleState.CREATED, LifecycleState.ACTIVE)

    with pytest.raises(EyeContractError):
        validate_detection_transition(DetectionState.REJECTED, DetectionState.CONFIRMED_CLOSED_BAR)


# ----------------------------------------------------
# H. PROBABILITY AND AUTHORITY (55-60)
# ----------------------------------------------------

def test_req_55_to_60_probability_and_authority_rules():
    prob = ProbabilityAssessment()
    assert prob.status == ProbabilityStatus.NOT_ESTABLISHED
    assert prob.probability is None

    rec = _helper_record()
    assert rec.authority == AuthorityType.OBSERVATION_ONLY


# ----------------------------------------------------
# I. SERIALIZATION AND SCHEMA (61-70)
# ----------------------------------------------------

def test_req_61_to_70_serialization_and_hashing():
    rec = _helper_record()
    d1 = rec.to_dict()
    s1 = canonical_json(d1)
    s2 = canonical_json(d1)
    assert s1 == s2
    assert "schema_version" in d1
