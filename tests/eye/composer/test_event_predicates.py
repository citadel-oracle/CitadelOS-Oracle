"""E3 Event Predicates Test Suite."""

import pytest
from datetime import datetime, timezone
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.contracts import PatternStep
from src.eye.composer.predicates import match_event_predicate


def test_match_event_predicate_family_and_type():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="RULE1", rule_version="1.0.0")
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)

    rec = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
    )

    step_match = PatternStep(
        step_id="STEP1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,),
    )
    step_mismatch = PatternStep(
        step_id="STEP2", accepted_families=(EventFamily.STRUCTURE,), accepted_types=(EventType.BOS_BULLISH,),
    )

    assert match_event_predicate(rec, step_match) is True
    assert match_event_predicate(rec, step_mismatch) is False
