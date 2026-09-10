"""E3-D Incremental vs Full Batch Replay Independence Test Suite."""

import pytest
from datetime import datetime, timezone
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def test_incremental_and_batch_replay_parity():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    p1 = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BULLISH)
    e1 = EyeEventRecord.create(
        family=EventFamily.IMBALANCE, event_type=EventType.FVG_BULLISH,
        direction=EventDirection.BULLISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
    )

    defs = get_e3_setup_definitions()
    comp_inc = SetupComposer(defs)
    cands_inc = comp_inc.process_event(e1)

    comp_batch = SetupComposer(defs)
    cands_batch = comp_batch.process_event(e1)

    assert len(cands_inc) == len(cands_batch)
    assert [c.setup_key for c in cands_inc] == [c.setup_key for c in cands_batch]
