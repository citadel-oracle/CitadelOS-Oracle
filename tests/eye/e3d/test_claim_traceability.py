"""E3-D Claim Traceability & Causal Lineage Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom, compute_sha256
from src.eye.composer.contracts import SetupDefinition, PatternStep
from src.eye.composer.matcher import SetupComposer


def test_setup_candidate_has_causal_atomic_event_keys():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    sd = SetupDefinition(
        setup_id="TRACE_SETUP_V1", setup_version="1.0.0", setup_family="BREAKAWAY_FVG_CONTINUATION",
        name="Breakaway FVG Continuation", status="RESEARCH", provenance="TEST",
        steps=(
            PatternStep(step_id="S1", accepted_families=(EventFamily.STRUCTURE,), accepted_types=(EventType.BOS_BULLISH,)),
            PatternStep(step_id="S2", accepted_families=(EventFamily.IMBALANCE,), accepted_types=(EventType.FVG_BULLISH,)),
        ),
    )

    ctx1 = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    p1 = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BULLISH)
    e1 = EyeEventRecord.create(
        family=EventFamily.STRUCTURE, event_type=EventType.BOS_BULLISH,
        direction=EventDirection.BULLISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx1,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
    )

    now2 = now + timedelta(seconds=1)
    ctx2 = EvaluationContext(market_time=now2, available_at=now2, detected_at=now2, as_of=now2)
    e2 = EyeEventRecord.create(
        family=EventFamily.IMBALANCE, event_type=EventType.FVG_BULLISH,
        direction=EventDirection.BULLISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx2,
        observed_at=now2, detected_at=now2, source_bars=(), producer=prov,
    )

    composer = SetupComposer([sd])
    _ = composer.process_event(e1)
    cands = composer.process_event(e2)
    assert len(cands) == 1
    cand = cands[0]

    assert cand.atomic_event_keys == (e1.event_key, e2.event_key)
    assert cand.atomic_record_ids == (e1.record_id, e2.record_id)
    assert cand.ordered_step_bindings[0]["step_id"] == "S1"
    assert cand.ordered_step_bindings[0]["event_key"] == e1.event_key
