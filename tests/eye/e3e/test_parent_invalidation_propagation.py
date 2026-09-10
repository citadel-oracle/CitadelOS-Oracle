"""E3-E Parent Invalidation Propagation Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom, compute_sha256
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer
from src.eye.composer.contracts import CandidateStatus


def test_parent_atomic_invalidation_emits_invalidated_candidate_revision():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    ctx1 = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    p1 = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)

    # Step 0: Pool
    e1 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx1,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
        event_revision=1,
    )

    # Step 1: Sweep
    now2 = now + timedelta(seconds=1)
    ctx2 = EvaluationContext(market_time=now2, available_at=now2, detected_at=now2, as_of=now2)
    e2 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_SWEEP_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx2,
        observed_at=now2, detected_at=now2, source_bars=(), producer=prov,
        event_revision=1,
    )

    composer = SetupComposer(get_e3_setup_definitions())
    _ = composer.process_event(e1)
    cands_conf = composer.process_event(e2)
    assert len(cands_conf) == 1
    conf_cand = cands_conf[0]
    assert conf_cand.status == CandidateStatus.CONFIRMED
    assert conf_cand.setup_revision == 1

    # Invalidation event for parent sweep event e2 (event_revision 2 with LifecycleState.INVALIDATED)
    now3 = now + timedelta(seconds=2)
    ctx3 = EvaluationContext(market_time=now3, available_at=now3, detected_at=now3, as_of=now3)
    rec2_id = compute_sha256(f"{e2.event_key}:2:{LifecycleState.INVALIDATED.value}")[:16]
    e2_inv = EyeEventRecord(
        schema_version="0.1.0",
        event_key=e2.event_key,
        record_id=rec2_id,
        event_revision=2,
        family=EventFamily.LIQUIDITY,
        event_type=EventType.LIQUIDITY_SWEEP_HIGH,
        direction=EventDirection.BEARISH,
        instrument=inst,
        timeframe="5m",
        payload=p1,
        detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.INVALIDATED,
        evaluation_context=ctx3,
        observed_at=now3,
        detected_at=now3,
        source_bars=(),
        producer=prov,
    )

    cands_inv = composer.process_event(e2_inv)
    assert len(cands_inv) == 1
    inv_cand = cands_inv[0]

    # Verify two-identity revision linkage
    assert inv_cand.setup_key == conf_cand.setup_key
    assert inv_cand.record_id != conf_cand.record_id
    assert inv_cand.setup_revision == 2
    assert inv_cand.previous_record_id == conf_cand.record_id
    assert inv_cand.status == CandidateStatus.INVALIDATED
    assert inv_cand.invalidated_at == now3
