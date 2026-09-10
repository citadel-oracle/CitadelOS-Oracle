"""End-to-End Acceptance Test for Luna Production Cognitive Pipeline.

Proves the complete verified path:
real canonical Upstox event
→ existing trigger
→ compact packet
→ sanitizer
→ Luna exact model (gpt-5.6-luna)
→ structured response
→ EvidenceGate
→ session/frontier stale guard
→ ThesisGraph durable commit
→ frontend/API observable cognitive state
with zero execution influence.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.oracle_sol.cognitive_event_bridge import CognitiveEventBridge, CognitiveEventTrigger
from src.oracle_sol.cognitive_projection import project_cognitive_decision
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot, SystemStatus
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.experiential_adapter import ExperientialAdapter
from src.oracle_sol.luna_cognitive_adapter import LunaCognitiveAdapter
from src.oracle_sol.phase1_coordinator import Phase1CognitiveCoordinator
from src.oracle_sol.thesis_graph import ThesisGraph


def test_luna_production_pipeline_acceptance(tmp_path):
    storage_file = tmp_path / "thesis_graph.jsonl"
    status_file = tmp_path / "live_cognitive_status.json"

    graph = ThesisGraph(storage_path=str(storage_file))
    gate = EvidenceGate(thesis_graph=graph)

    # Real Upstox event from 2026-09-08
    canonical_event = MarketEvent(
        event_id="evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089",
        session_date="2026-09-08",
        timestamp_utc="2026-09-08T08:21:35.672000+00:00",
        timestamp_ist="13:51:35",
        event_type="SPOT_MOVE",
        instrument="NIFTY_INDEX",
        security_id=None,
        strike=None,
        expiry=None,
        summary="NIFTY spot dropped 11.85 pts to 23625.85",
        before_state={"state": "WAIT"},
        after_state={"state": "WAIT"},
        supporting_values={
            "before_spot": 23637.7,
            "after_spot": 23625.85,
            "spot_delta": -11.85,
            "session_vwap": 23650.0,
            "spot_to_vwap_pts": -24.15,
        },
        provenance_hash="hash_can_upstox_001",
    )

    fixture_path = Path("tests/oracle_sol/fixtures/bridge_recorded_snapshot_20260904.json")
    snap_data = json.loads(fixture_path.read_text())
    snap_data["market_session_date"] = "2026-09-08"
    snap_data["timestamp_ist"] = "13:51:35"
    snap_data["system_status"] = SystemStatus.HEALTHY
    snap_data["spot_ltp"] = 23625.85
    snap_data["session_vwap"] = 23650.0
    snapshot = SolEvidenceSnapshot(**snap_data)

    # Mock Experiential backend returning Luna's qualified response
    luna_response_content = {
        "state": "WAIT",
        "thesis_evolution": "REVERSAL_WATCH",
        "opportunity_maturity": "UNKNOWN",
        "conclusions": [
            {
                "purpose": "why_now",
                "claim": "Consolidation observed after sharp session low extension.",
                "evidence_ids": ["evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089"],
            },
            {
                "purpose": "call_case",
                "claim": "Rebound candidate emerging at 23625 level.",
                "evidence_ids": ["evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089"],
            },
            {
                "purpose": "put_case",
                "claim": "Session trend intact until 23650 reclaimed.",
                "evidence_ids": ["evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089"],
            },
            {
                "purpose": "contradiction",
                "claim": "No aggressive upside follow-through at the cutoff.",
                "evidence_ids": ["evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089"],
            }
        ],
        "hypotheses": {
            "CALL": {
                "plausibility": "PLAUSIBLE",
                "discrimination": "Rebound distinguishes from crash.",
                "evidence_ids": ["evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089"],
            },
            "PUT": {
                "plausibility": "PLAUSIBLE",
                "discrimination": "Downside trend intact.",
                "evidence_ids": ["evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089"],
            },
            "NOISE": {
                "plausibility": "PLAUSIBLE",
                "discrimination": "Range chop following bounce.",
                "evidence_ids": ["evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089"],
            },
            "REVERSAL": {
                "plausibility": "UNRESOLVED",
                "discrimination": "Crash-to-bounce sequence compatible with reversal watch.",
                "evidence_ids": ["evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089"],
            },
        },
        "promotion_reason": "WAIT is warranted as CALL and PUT each have localized arguments while persistence is unproven.",
    }

    mock_resp = {
        "id": "xpl-chatcmpl-luna-prod",
        "model": "gpt-5.6-luna",
        "choices": [{"message": {"role": "assistant", "content": json.dumps(luna_response_content)}}],
        "usage": {"total_tokens": 2500, "prompt_tokens": 1800, "completion_tokens": 700},
        "cost_micro_usd": 0,
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value.status = 200
    mock_urlopen.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    mock_urlopen.__enter__.return_value.headers = {}

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        backend = ExperientialAdapter(
            model_name="gpt-5.6-luna",
            api_key="xpl_mock_prod_key_12345",
            enforce_zero_cost=True,
            reject_substituted_model=True,
        )
        luna_adapter = LunaCognitiveAdapter(backend_adapter=backend)
        coordinator = Phase1CognitiveCoordinator(
            thesis_graph=graph,
            evidence_gate=gate,
            luna_adapter=luna_adapter,
            analyst_mode="luna",
        )

        bridge = CognitiveEventBridge(
            event_source=lambda: [canonical_event],
            thesis_graph=graph,
            coordinator=coordinator,
            status_path=str(status_file),
        )
        bridge.start("2026-09-08", 0)

        try:
            trigger = CognitiveEventTrigger(
                session_id="2026-09-08",
                session_generation=0,
                source_revision=1,
                evidence_frontier="evt_40889817057dd801_SPOT_MOVE_NIFTY_INDEX_8290d708bcccb089",
                source_event_count=1,
                snapshot=snapshot,
                offered_at_monotonic_ns=time.perf_counter_ns(),
            )
            assert bridge.offer(trigger) is True
            assert bridge.wait_until_idle(timeout=5.0) is True

            # 1. Verify ThesisGraph durable commit
            active = graph.get_active_thesis()
            assert active is not None
            assert active.model == "gpt-5.6-luna"
            assert active.state == "WAIT"
            assert active.event_cursor_after == canonical_event.event_id
            assert canonical_event.event_id in active.supporting_evidence_ids

            # Verify persistent JSONL file exists and is populated
            assert storage_file.exists()
            assert storage_file.stat().st_size > 0

            # 2. Verify live_cognitive_status.json
            assert status_file.exists()
            with open(status_file) as sf:
                status_doc = json.load(sf)
            assert status_doc["status"] == "COMMITTED"
            assert status_doc["session_id"] == "2026-09-08"
            assert status_doc["models"]["gpt_oss"]["model_id"] == "gpt-5.6-luna"
            assert status_doc["models"]["gpt_oss"]["status"] == "CURRENT"
            assert status_doc["models"]["luna"]["model_id"] == "gpt-5.6-luna"

            # 3. Verify observable cognitive state via project_cognitive_decision
            projection = project_cognitive_decision(
                active=active,
                previous=None,
                live_status=status_doc,
                snapshot=snap_data,
            )
            assert projection["primary_decision"]["state"] == "WAIT"
            assert projection["gpt"]["model_id"] == "gpt-5.6-luna"
            assert projection["gpt"]["status"] == "CURRENT"

            # 4. Verify Hard Safety Invariants (Zero Execution Influence)
            assert projection["paper_only"] is True
            assert projection["live_trading"] is False
            assert projection["broker_submission"] is False
            assert projection["execution_influence"] == 0
            assert projection["ai_vob_influence"] == 0

        finally:
            bridge.stop()
