"""E3-D Contiguity Policy Truth Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.contracts import SetupDefinition, PatternStep, ContiguityPolicy
from src.eye.composer.matcher import SetupComposer


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def test_strict_next_contiguity_fails_on_intervening_event():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = _sample_identity()
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    # Strict setup definition
    sd = SetupDefinition(
        setup_id="STRICT_SETUP_V1", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Strict Sweep Reclaim", status="RESEARCH", provenance="TEST",
        contiguity_policy=ContiguityPolicy.STRICT_NEXT,
        steps=(
            PatternStep(step_id="S1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,), contiguity=ContiguityPolicy.STRICT_NEXT),
            PatternStep(step_id="S2", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_SWEEP_HIGH,), contiguity=ContiguityPolicy.STRICT_NEXT),
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

    # Intervening non-matching event (Structure break)
    now2 = now + timedelta(seconds=1)
    ctx2 = EvaluationContext(market_time=now2, available_at=now2, detected_at=now2, as_of=now2)
    e_intervening = EyeEventRecord.create(
        family=EventFamily.STRUCTURE, event_type=EventType.BOS_BEARISH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx2,
        observed_at=now2, detected_at=now2, source_bars=(), producer=prov,
    )

    # Step 2 target event
    now3 = now + timedelta(seconds=2)
    ctx3 = EvaluationContext(market_time=now3, available_at=now3, detected_at=now3, as_of=now3)
    e2 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_SWEEP_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx3,
        observed_at=now3, detected_at=now3, source_bars=(), producer=prov,
    )

    composer = SetupComposer([sd])
    _ = composer.process_event(e1)
    _ = composer.process_event(e_intervening)
    cands = composer.process_event(e2)

    # Under STRICT_NEXT, the intervening event MUST cancel/fail the active partial match!
    assert len(cands) == 0, "STRICT_NEXT must reject match when an intervening non-matching event occurs"
