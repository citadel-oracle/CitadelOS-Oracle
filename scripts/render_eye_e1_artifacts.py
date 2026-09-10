"""Artifact Generator for Eye Engine Phase E1."""

import os
import json
from datetime import datetime, timezone
from pathlib import Path

from src.eye.contracts import (
    EyeEventRecord,
    InstrumentIdentity,
    EvaluationContext,
    BarReference,
    PriceAtom,
    PointEventPayload,
    ZoneEventPayload,
    ProducerProvenance,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
)
from src.eye.registry import RuleRegistry, RuleDefinition, RuleStatus, ProvenanceType
from src.eye.serialization import canonical_json, compute_sha256

OUT_DIR = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery")
TIMESTAMP = "20260806"


def render_artifacts():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Valid Example Record
    now = datetime(2026, 8, 6, 15, 30, 0, tzinfo=timezone.utc)
    inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
        identity_epoch="epoch-20260806-001",
    )
    bar = BarReference(
        instrument_key=inst.instrument_key,
        timeframe="5m",
        open_time=now,
        expected_close_time=now,
        available_at=now,
        bar_key="NIFTY:5m:202608061530",
        is_closed=True,
        source_name="DHAN",
    )
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
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
    rec = EyeEventRecord.create(
        event_revision=1,
        family=EventFamily.STRUCTURE,
        event_type=EventType.BOS_BULLISH,
        direction=EventDirection.BULLISH,
        instrument=inst,
        timeframe="5m",
        payload=payload,
        detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
        lifecycle_state=LifecycleState.CREATED,
        evaluation_context=ctx,
        observed_at=now,
        detected_at=now,
        source_bars=[bar],
        producer=prov,
    )

    valid_json = rec.to_dict()

    # Write JSON Artifacts
    (OUT_DIR / f"EYE_ENGINE_E1_VALID_EXAMPLES_{TIMESTAMP}.json").write_text(json.dumps([valid_json], indent=2))

    invalid_examples = [
        {"reason": "Underlying index with option strike", "data": {"instrument_type": "UNDERLYING_INDEX", "strike": 24500.0}},
        {"reason": "Naive datetime timestamp", "data": {"market_time": "2026-08-06T15:30:00"}},
        {"reason": "Float ticks in PriceAtom", "data": {"ticks": 24500.0, "quantum": "0.01"}},
    ]
    (OUT_DIR / f"EYE_ENGINE_E1_INVALID_EXAMPLES_{TIMESTAMP}.json").write_text(json.dumps(invalid_examples, indent=2))

    # Registry Artifact
    registry = RuleRegistry()
    registry.register(RuleDefinition(
        rule_id="BOS_CLOSE_BREAK_V1",
        rule_version="1.0.0",
        event_type="BOS_BULLISH",
        event_family="STRUCTURE",
        status=RuleStatus.ACTIVE,
        provenance=ProvenanceType.EXISTING_CITADEL_RULE,
        source_file="src/structure/structure_engine_v2.py",
        source_symbol="StructureEngineV2.analyze",
        source_commit="8632791",
        effective_parameters={"swing_window": 2, "break_type": "CLOSE"},
        description="Close break above previous 2-bar swing high",
    ))
    reg_json = [r.to_dict() for r in registry.list_all()]

    (OUT_DIR / f"EYE_ENGINE_E1_RULE_SCHEMA_{TIMESTAMP}.json").write_text(json.dumps(reg_json, indent=2))

    # Markdown Reports
    report_md = f"""# CITADEL EYE ENGINE — PHASE E1 CANONICAL CONTRACT REPORT

**Date:** 2026-08-06  
**Schema Version:** 0.1.0  
**Modelling Stack:** `@dataclass(frozen=True, kw_only=True, slots=True)` + custom validators & canonical JSON serialization  

## Summary
Phase E1 delivers strict, deterministic, and immutable market-event contracts (`EyeEventRecord`, `InstrumentIdentity`, `EvaluationContext`, `BarReference`, `PriceAtom`, Payload variants) and a SemVer-validated `RuleRegistry`.

## Dual Identity Architecture
- **Semantic `event_key`:** Hash of instrument_key, event_type, timeframe, source_bar_keys, primary level/zone geometry, rule_id, rule_version. Stable across reconnects and publication retries.
- **Immutable `record_id`:** Hash of event_key, event_revision, detection_state, lifecycle_state, identity_epoch, producer_version. Updates monotonically on lifecycle state changes.

## Safety & Authority Lock
- Authority in E1: `OBSERVATION_ONLY`
- Paper Trading Safety: `paper_only=true`, `live_trading_enabled=false`, `execution_influence=ZERO`
"""
    (OUT_DIR / f"EYE_ENGINE_E1_CONTRACT_REPORT_{TIMESTAMP}.md").write_text(report_md)

    print("Artifact generation SUCCESS!")


if __name__ == "__main__":
    render_artifacts()
