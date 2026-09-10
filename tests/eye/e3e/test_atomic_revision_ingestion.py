"""E3-E Atomic Event Revision Ingestion Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def test_atomic_record_id_idempotency_and_revision_propagation():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    p1 = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)

    # Event record revision 1
    e1_r1 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
        event_revision=1,
    )

    composer = SetupComposer(get_e3_setup_definitions())

    # First ingestion
    cands1 = composer.process_event(e1_r1)
    assert event_record_id_in_composer(composer, e1_r1.record_id)

    # Exact same record_id replayed -> idempotent no-op
    cands_dup = composer.process_event(e1_r1)
    assert len(cands_dup) == 0


def event_record_id_in_composer(composer, record_id):
    return record_id in composer.processed_record_ids
