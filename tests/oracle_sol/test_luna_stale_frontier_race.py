"""Controlled Test Proving Stale-On-Arrival Race Protection for Luna Inference.

Luna inference averages 20-25 seconds latency. If new canonical evidence arrives
and advances the evidence frontier while Luna is reasoning in-flight, the old
response must NOT be committed as CURRENT. It must be rejected as
STALE_RESULT_NOT_PROMOTED, and the newest coalesced frontier evaluated.
"""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src.oracle_sol.cognitive_event_bridge import CognitiveEventBridge, CognitiveEventTrigger
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot, SystemStatus
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.luna_cognitive_adapter import LunaCognitiveAdapter
from src.oracle_sol.phase1_coordinator import Phase1CognitiveCoordinator
from src.oracle_sol.thesis_graph import ThesisGraph


def _make_snapshot(session_date: str = "2026-09-08") -> SolEvidenceSnapshot:
    fixture_path = Path("tests/oracle_sol/fixtures/bridge_recorded_snapshot_20260904.json")
    snap_data = json.loads(fixture_path.read_text())
    snap_data["market_session_date"] = session_date
    snap_data["timestamp_ist"] = "13:51:35"
    snap_data["system_status"] = SystemStatus.HEALTHY
    return SolEvidenceSnapshot(**snap_data)


def _make_event(event_id: str, ts_ist: str = "13:51:35") -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        session_date="2026-09-08",
        timestamp_utc="2026-09-08T08:21:35Z",
        timestamp_ist=ts_ist,
        event_type="SPOT_MOVE",
        instrument="NIFTY_INDEX",
        security_id=None,
        strike=None,
        expiry=None,
        summary=f"Event {event_id}",
        before_state={"state": "WAIT"},
        after_state={"state": "WAIT"},
        supporting_values={"before_spot": 23637.7, "after_spot": 23625.85, "spot_delta": -11.85},
        provenance_hash="hash_1",
    )


def test_in_flight_frontier_advance_rejects_stale_response(tmp_path):
    """Proves: In-flight frontier advance causes late response rejection as STALE_RESULT_NOT_PROMOTED."""
    storage_file = tmp_path / "thesis_graph.jsonl"
    graph = ThesisGraph(storage_path=str(storage_file))
    gate = EvidenceGate(thesis_graph=graph)

    # Synchronization primitives to control the in-flight race
    luna_started = threading.Event()
    frontier_advanced = threading.Event()

    class PausingLunaAdapter:
        def __init__(self):
            self.model_name = "gpt-5.6-luna"
            self.calls = []

        def analyze(self, packet, unseen_events=None, decision_cutoff_ist=None):
            self.calls.append(packet.revision)
            # Signal that Luna has started reasoning for this revision
            luna_started.set()

            # Wait until the main thread has advanced the evidence frontier
            assert frontier_advanced.wait(timeout=5.0), "Timed out waiting for frontier advance"

            # Return a valid structured response for this older revision
            eid = packet.unseen_event_ids[-1] if packet.unseen_event_ids else "evt_1"
            output = {
                "state": "WAIT",
                "thesis_evolution": "REVERSAL_WATCH",
                "opportunity_maturity": "UNKNOWN",
                "conclusions": [
                    {"purpose": "why_now", "claim": f"Analysis for {eid}", "evidence_ids": [eid]}
                ],
                "hypotheses": {
                    "CALL": {"plausibility": "PLAUSIBLE", "discrimination": "Test", "evidence_ids": [eid]},
                    "PUT": {"plausibility": "PLAUSIBLE", "discrimination": "Test", "evidence_ids": [eid]},
                    "NOISE": {"plausibility": "PLAUSIBLE", "discrimination": "Test", "evidence_ids": [eid]},
                    "REVERSAL": {"plausibility": "UNRESOLVED", "discrimination": "Test", "evidence_ids": [eid]},
                },
                "promotion_reason": f"Waiting on frontier {eid}",
            }
            telemetry = {
                "status": "CURRENT",
                "requested_model": "gpt-5.6-luna",
                "response_model": "gpt-5.6-luna",
                "cost_micro_usd": 0,
                "latency_ms": 23450.0,  # ~23.5s simulated latency
                "started_at": "2026-09-08T08:21:35Z",
            }
            return output, telemetry

    mock_luna = PausingLunaAdapter()
    coordinator = Phase1CognitiveCoordinator(
        thesis_graph=graph,
        evidence_gate=gate,
        luna_adapter=mock_luna,
        analyst_mode="luna",
    )

    events = [_make_event("evt_1", "13:51:35"), _make_event("evt_2", "13:53:36")]
    snapshot = _make_snapshot("2026-09-08")

    bridge = CognitiveEventBridge(
        event_source=lambda: list(events),
        thesis_graph=graph,
        coordinator=coordinator,
        status_path=str(tmp_path / "live_cognitive_status.json"),
    )
    bridge.start("2026-09-08", 0)

    try:
        # 1. Offer Trigger 1 at revision 10 (frontier = evt_1)
        trig1 = CognitiveEventTrigger(
            session_id="2026-09-08",
            session_generation=0,
            source_revision=10,
            evidence_frontier="evt_1",
            source_event_count=1,
            snapshot=snapshot,
            offered_at_monotonic_ns=time.perf_counter_ns(),
        )
        assert bridge.offer(trig1) is True

        # 2. Wait until Luna has started reasoning for Trigger 1
        assert luna_started.wait(timeout=3.0), "Luna did not start in time"

        # 3. While Luna is in-flight (~20s), newer canonical evidence arrives (frontier = evt_2)
        trig2 = CognitiveEventTrigger(
            session_id="2026-09-08",
            session_generation=0,
            source_revision=20,
            evidence_frontier="evt_2",
            source_event_count=2,
            snapshot=snapshot,
            offered_at_monotonic_ns=time.perf_counter_ns(),
        )
        # Offer Trigger 2 to bridge: frontier advances to evt_2
        assert bridge.offer(trig2) is True

        # 4. Now release Luna to finish reasoning for Trigger 1 (frontier evt_1)
        frontier_advanced.set()

        # 5. Wait for the bridge worker to complete both cycles
        assert bridge.wait_until_idle(timeout=5.0) is True

        # 6. Verify stale-on-arrival rejection!
        telemetry = bridge.get_telemetry()
        assert telemetry["stale_results_not_promoted"] >= 1, (
            f"Expected at least 1 stale result rejection, got {telemetry['stale_results_not_promoted']}"
        )

        # 7. Verify the active thesis in ThesisGraph is NOT the stale Trigger 1!
        active = graph.get_active_thesis()
        if active:
            assert active.input_revision != 10, "Stale revision 10 was promoted to active thesis!"
            assert active.event_cursor_after != "evt_1", "Stale frontier evt_1 was promoted!"

    finally:
        bridge.stop()
