"""E3 Incremental vs Full Sequence Replay Parity Test Suite."""

import pytest
from datetime import datetime, timezone
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.replay import OfflineSetupReplayHarness


def test_incremental_and_full_replay_parity():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
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

    harness = OfflineSetupReplayHarness(get_e3_setup_definitions())
    cands_inc = harness.replay_incremental([e1, e2])
    cands_batch = harness.replay_batch([e1, e2])

    assert len(cands_inc) == len(cands_batch)
    if cands_inc:
        assert cands_inc[0].setup_key == cands_batch[0].setup_key
        assert cands_inc[0].record_id == cands_batch[0].record_id
