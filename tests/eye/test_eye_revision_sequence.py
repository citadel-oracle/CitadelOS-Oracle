"""Tests for Semantic event_key and Immutable record_id Revision Sequence."""

import pytest
from datetime import datetime, timezone
from src.eye.contracts import (
    EyeEventRecord,
    InstrumentIdentity,
    EvaluationContext,
    BarReference,
    PriceAtom,
    PointEventPayload,
    ProducerProvenance,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
    EyeContractError,
)


def _build_test_record(revision: int = 1, detection: DetectionState = DetectionState.PROVISIONAL_INTRABAR, epoch: str = "epoch-1"):
    now_utc = datetime.now(timezone.utc)
    inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
        identity_epoch=epoch,
    )
    bar = BarReference(
        instrument_key=inst.instrument_key,
        timeframe="5m",
        open_time=now_utc,
        expected_close_time=now_utc,
        available_at=now_utc,
        bar_key="NIFTY:5m:202608061530",
        is_closed=True,
        source_name="DHAN",
    )
    ctx = EvaluationContext(market_time=now_utc, available_at=now_utc, detected_at=now_utc, as_of=now_utc)
    payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000, quantum="0.01"), direction=EventDirection.BULLISH)
    prov = ProducerProvenance(
        engine_name="StructureEngineV2",
        source_file="src/structure/structure_engine_v2.py",
        source_symbol="StructureEngineV2.analyze",
        source_commit="8632791",
        producer_version="1.0.0",
        rule_id="BOS_CLOSE_BREAK_V1",
        rule_version="1.0.0",
    )

    return EyeEventRecord.create(
        event_revision=revision,
        family=EventFamily.STRUCTURE,
        event_type=EventType.BOS_BULLISH,
        direction=EventDirection.BULLISH,
        instrument=inst,
        timeframe="5m",
        payload=payload,
        detection_state=detection,
        lifecycle_state=LifecycleState.CREATED,
        evaluation_context=ctx,
        observed_at=now_utc,
        detected_at=now_utc,
        source_bars=[bar],
        producer=prov,
    )


def test_event_key_stability_across_epochs():
    rec1 = _build_test_record(revision=1, epoch="epoch-1")
    rec2 = _build_test_record(revision=1, epoch="epoch-2")

    # Semantic event_key remains STABLE despite identity_epoch change
    assert rec1.event_key == rec2.event_key

    # Immutable record_id MUST be distinct due to epoch difference
    assert rec1.record_id != rec2.record_id


def test_monotonic_revision_sequence():
    rec_v1 = _build_test_record(revision=1, detection=DetectionState.PROVISIONAL_INTRABAR)
    rec_v2 = _build_test_record(revision=2, detection=DetectionState.CONFIRMED_CLOSED_BAR)

    assert rec_v1.event_key == rec_v2.event_key
    assert rec_v1.event_revision == 1
    assert rec_v2.event_revision == 2
    assert rec_v1.record_id != rec_v2.record_id
