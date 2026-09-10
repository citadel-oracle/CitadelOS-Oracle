"""E3-E Multi-Step Definition Truth Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer
from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from datetime import datetime, timezone


def test_all_research_setup_definitions_have_at_least_two_mandatory_steps():
    defs = get_e3_setup_definitions()
    research_defs = [d for d in defs if d.status in ("HISTORICALLY_SUPPORTED_RESEARCH", "SYNTHETICALLY_TESTABLE_RESEARCH")]
    assert len(research_defs) == 8
    for d in research_defs:
        mandatory_steps = [s for s in d.steps if not s.optional_step]
        assert len(mandatory_steps) >= 2, f"Setup {d.setup_id} must have at least 2 mandatory steps"


def test_single_atomic_event_cannot_confirm_multistep_setup():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    p1 = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)
    e1 = EyeEventRecord.create(
        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
        direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
        payload=p1, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
        observed_at=now, detected_at=now, source_bars=(), producer=prov,
    )

    composer = SetupComposer(get_e3_setup_definitions())
    cands = composer.process_event(e1)
    assert len(cands) == 0, "A single atomic event MUST NOT confirm any multi-step setup candidate"
