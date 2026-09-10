#!/usr/bin/env python3
"""Create explicit HISTORICAL Phase-2 perception proof records.

This command reads the durable context cache and writes only advisory perception
proof artifacts.  It cannot call risk, execution, Dhan or OpenAlgo.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.oracle.context import ContextEngine
from src.oracle.contracts.perception import (
    Availability, CompletionStatus, FreshnessState, VisualClaimCandidate, seal,
)
from src.oracle.visual import TradingViewMCPAdapter, VisualClaimVerifier, VisualObservationStore


def main() -> int:
    state_root = Path(os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs"))
    perception = state_root / "oracle_perception"
    context = ContextEngine(perception / "context", candle_path=state_root / "vob_1m_candles.json")
    snapshot = context.latest_snapshot() or context.bootstrap_from_persisted(correlation_id="phase2-runtime-proof")
    if snapshot is None:
        raise RuntimeError("CONTEXT_UNAVAILABLE")
    lane = context.latest_lane("3m")
    if lane is None or lane.candle is None:
        raise RuntimeError("3M_CONTEXT_UNAVAILABLE")
    candle = lane.candle
    now = datetime.now(timezone.utc)
    common = dict(
        correlation_id="phase2-runtime-proof", instrument_id=candle.instrument_id, symbol=candle.symbol,
        timeframe="3m", source_timestamp=candle.source_timestamp, generated_at=now.isoformat(), as_of=candle.as_of,
        availability=Availability.HISTORICAL, freshness_state=FreshnessState.STALE,
        source_ids={"context_snapshot": snapshot.snapshot_id, "candle": candle.candle_id},
        dependency_versions={"context_hash": snapshot.content_hash, "proof": "1.0.0"},
        completion_status=CompletionStatus.COMPLETE,
        provenance={"mode": "HISTORICAL_RUNTIME_PROOF", "visual_source": "UNAVAILABLE",
                    "advisory_only": True, "execution_influence": "ZERO"},
        observation_id="tvobs_phase2_mcp_unavailable",
    )
    candidates = (
        seal(VisualClaimCandidate(**common, claim_id="phase2_verified_structure_break", claim_type="STRUCTURE_BREAK",
                                  direction="BULLISH", predicates={"level": candle.close - 0.5}, declared_tolerance=0.0)),
        seal(VisualClaimCandidate(**common, claim_id="phase2_rejected_structure_break", claim_type="STRUCTURE_BREAK",
                                  direction="BEARISH", predicates={"level": candle.low - 1.0}, declared_tolerance=0.0)),
    )
    verifier = VisualClaimVerifier()
    store = VisualObservationStore(perception / "visual")
    results = [verifier.verify(candidate, [candle], allow_historical=True) for candidate in candidates]
    for result in results:
        store.save_claim(result)
    unavailable = TradingViewMCPAdapter(lambda *_: (_ for _ in ()).throw(TimeoutError("MCP_UNRESPONSIVE"))).capture(
        correlation_id="phase2-runtime-proof", instrument_id=candle.instrument_id, symbol=candle.symbol, timeframe="3m")
    store.save_observation(unavailable)
    print(json.dumps({
        "context_snapshot_id": snapshot.snapshot_id,
        "context_hash": snapshot.content_hash,
        "claims": [{"claim_id": row.claim_id, "status": row.status, "availability": row.availability.value,
                    "freshness": row.freshness_state.value, "actionable_evidence_weight": row.actionable_evidence_weight}
                   for row in results],
        "visual_failure": {"observation_id": unavailable.observation_id, "availability": unavailable.availability.value,
                           "reason": unavailable.failure_reason},
        "safety": {"paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                   "advisory_only": True, "execution_influence": "ZERO"},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
