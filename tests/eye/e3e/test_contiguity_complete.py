"""E3-E Complete Contiguity Policies Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.contracts import SetupDefinition, PatternStep, ContiguityPolicy
from src.eye.composer.matcher import SetupComposer


def _create_event(ev_type, t):
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")
    ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)
    p1 = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)
    fam = EventFamily.LIQUIDITY if ev_type in (EventType.LIQUIDITY_POOL_HIGH, EventType.LIQUIDITY_SWEEP_HIGH) else EventFamily.STRUCTURE
    return EyeEventRecord.create(
        family=fam, event_type=ev_type,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
        observed_at=t, detected_at=t, source_bars=(), producer=prov,
    )


def test_contiguity_policies_produce_distinct_results():
    t0 = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    e_pool = _create_event(EventType.LIQUIDITY_POOL_HIGH, t0)
    e_bos = _create_event(EventType.BOS_BEARISH, t0 + timedelta(seconds=1))
    e_sweep = _create_event(EventType.LIQUIDITY_SWEEP_HIGH, t0 + timedelta(seconds=2))

    # 1. STRICT_NEXT setup definition
    sd_strict = SetupDefinition(
        setup_id="STRICT_DEF", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Strict Setup", status="RESEARCH", provenance="TEST",
        contiguity_policy=ContiguityPolicy.STRICT_NEXT,
        steps=(
            PatternStep(step_id="S1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,), contiguity=ContiguityPolicy.STRICT_NEXT),
            PatternStep(step_id="S2", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_SWEEP_HIGH,), contiguity=ContiguityPolicy.STRICT_NEXT),
        ),
    )

    # 2. RELAXED_NEXT setup definition
    sd_relaxed = SetupDefinition(
        setup_id="RELAXED_DEF", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Relaxed Setup", status="RESEARCH", provenance="TEST",
        contiguity_policy=ContiguityPolicy.RELAXED_NEXT,
        steps=(
            PatternStep(step_id="S1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,), contiguity=ContiguityPolicy.RELAXED_NEXT),
            PatternStep(step_id="S2", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_SWEEP_HIGH,), contiguity=ContiguityPolicy.RELAXED_NEXT),
        ),
    )

    comp_strict = SetupComposer([sd_strict])
    _ = comp_strict.process_event(e_pool)
    _ = comp_strict.process_event(e_bos)
    cands_strict = comp_strict.process_event(e_sweep)

    comp_relaxed = SetupComposer([sd_relaxed])
    _ = comp_relaxed.process_event(e_pool)
    _ = comp_relaxed.process_event(e_bos)
    cands_relaxed = comp_relaxed.process_event(e_sweep)

    # STRICT_NEXT rejects due to intervening BOS event; RELAXED_NEXT allows
    assert len(cands_strict) == 0
    assert len(cands_relaxed) == 1
