"""E2B-D Event Identity Semantics Test Suite."""

import pytest
from datetime import datetime, timezone
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, AuthorityType, PriceAtom


def test_event_key_vs_record_id_revision_monotonicity():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="RULE1", rule_version="1.0.0", authority=AuthorityType.OBSERVATION_ONLY)
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BULLISH)

    rec1 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.ACTIVE, evaluation_context=ctx,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
        event_revision=1,
    )

    rec2 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.BROKEN, evaluation_context=ctx,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
        event_revision=2, previous_record_id=rec1.record_id,
    )

    # Event keys MUST be identical across revisions of same semantic event
    assert rec1.event_key == rec2.event_key
    # Record IDs MUST be distinct for each immutable revision
    assert rec1.record_id != rec2.record_id
    assert rec2.previous_record_id == rec1.record_id
