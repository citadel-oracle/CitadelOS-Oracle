"""E3 Setup Families 1-8 Execution Test Suite."""

import pytest
from datetime import datetime, timezone
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def test_setup_family_liquidity_sweep_reclaim():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = _sample_identity()
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)

    e1 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
    )

    e2 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_SWEEP_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
    )

    defs = get_e3_setup_definitions()
    composer = SetupComposer(defs)

    _ = composer.process_event(e1)
    cands = composer.process_event(e2)

    assert len(cands) >= 1
    c = cands[0]
    assert c.setup_family == "LIQUIDITY_SWEEP_RECLAIM"
    assert c.status.value == "CONFIRMED"
    assert c.authority.value == "OBSERVATION_ONLY"
    assert c.probability_status.value == "NOT_ESTABLISHED"
