"""E3-E Negative Cancellation & Expiry Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.contracts import SetupDefinition, PatternStep
from src.eye.composer.matcher import SetupComposer


def test_prune_expired_removes_from_active_matches():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    sd = SetupDefinition(
        setup_id="EXP_DEF", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Expiry Setup", status="RESEARCH", provenance="TEST",
        steps=(
            PatternStep(step_id="S1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,), max_elapsed_minutes=1),
            PatternStep(step_id="S2", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_SWEEP_HIGH,)),
        ),
    )

    ctx1 = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    p1 = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)
    e1 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx1,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
    )

    now2 = now + timedelta(minutes=5)
    ctx2 = EvaluationContext(market_time=now2, available_at=now2, detected_at=now2, as_of=now2)
    e2 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_SWEEP_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx2,
        observed_at=now2, detected_at=now2, source_bars=(), producer=prov,
    )

    comp = SetupComposer([sd])
    _ = comp.process_event(e1)
    cands = comp.process_event(e2)
    assert len(cands) == 0
    assert len(comp.trackers["EXP_DEF"].active_matches) == 0
    assert len(comp.trackers["EXP_DEF"].expired_matches) == 1
