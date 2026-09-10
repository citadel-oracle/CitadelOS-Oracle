"""Tests for CITADEL Multi-Model Live Shadow Implementation V1.3.

Covers:
- Gemini Fast Scout & Sol Option Specialist schema validation
- Immutable persistence of challenger receipts
- LiveShadowOrchestrator bounded concurrency (1 in-flight per model)
- Stale result dropping from cockpit projection
- Hardened safety invariants (zero execution influence)
- Cockpit projection integration
"""

from __future__ import annotations

import json
from dataclasses import replace
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.cognitive_projection import project_cognitive_decision
from src.oracle_sol.shadow_orchestrator import (
    AI_EXECUTION_INFLUENCE,
    AI_VOB_INFLUENCE,
    BROKER_SUBMISSION,
    GEMINI_SCOUT_MODEL_ID,
    PRIMARY_MODEL_ID,
    SOL_CHALLENGER_MODEL_ID,
    CanonicalShadowReceipt,
)
from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator
from src.oracle_sol.shadow_specialists import (
    GEMINI_SEMANTIC_STATES,
    SOL_BUYING_STATES,
    GeminiScoutAdapter,
    GeminiScoutOutput,
    SolOptionSpecialistAdapter,
    SolOptionSpecialistOutput,
    persist_challenger_artifact,
)


# =====================================================================
# FIXTURES
# =====================================================================

def make_sample_payload(
    revision: int = 100,
    basis: float = 28.5,
    spot: float = 23550.0,
    cvd: Optional[float] = -120.0,
    mlofi: Optional[float] = 0.25,
) -> Dict[str, Any]:
    return {
        "packet_id": f"pkt_test_{revision}",
        "session_date": "2026-09-09",
        "decision_cutoff_ist": "13:35:09",
        "revision": revision,
        "evidence_frontier": [f"evt_{revision}"],
        "known_missing_inputs": ["flow_net_delta"] if cvd is not None else ["flow_net_delta", "cvd", "mlofi_5l"],
        "current_facts": {
            "spot_price": {"value": spot, "availability": "AVAILABLE"},
            "futures_price": {"value": spot + basis, "availability": "AVAILABLE"},
            "basis": {"value": basis, "availability": "AVAILABLE"},
            "session_vwap": {"value": spot - 10.0, "availability": "AVAILABLE"},
            "atm_strike": {"value": 23550.0, "availability": "AVAILABLE"},
            "ce_atm_premium": {"value": 145.0, "availability": "AVAILABLE"},
            "pe_atm_premium": {"value": 98.0, "availability": "AVAILABLE"},
            "atm_iv": {"value": 11.2, "availability": "AVAILABLE"},
            "straddle_price": {"value": 243.0, "availability": "AVAILABLE"},
            "total_net_gex_inr_cr": {"value": -14.2, "availability": "AVAILABLE"},
            "dealer_regime": {"value": "SHORT_GAMMA_AMPLIFY", "availability": "AVAILABLE"},
            "zero_gamma": {"value": 23520.0, "availability": "AVAILABLE"},
            "flow_net_delta": {"value": None, "availability": "UNAVAILABLE"},
            "cvd": {"value": cvd, "availability": "AVAILABLE" if cvd is not None else "UNAVAILABLE"},
            "mlofi_5l": {"value": mlofi, "availability": "AVAILABLE" if mlofi is not None else "UNAVAILABLE"},
        },
    }


def make_sample_packet(revision: int = 100, basis: float = 28.5) -> BrainPacket:
    payload = make_sample_payload(revision=revision, basis=basis)
    return BrainPacket(packet_id=f"test-{revision}", session_id="2026-09-09", revision=revision,
        compiled_at="2026-09-09T08:05:09Z", canonical_state={k: v["value"] for k, v in payload["current_facts"].items()},
        what_changed={}, unseen_event_ids=[], unseen_events_summary=[], previous_thesis=None,
        verified_external_events=[], external_quotes=[], valid_evidence_ids=[],
        evidence_registry={f"metric:{k}": {"value": v["value"], "timestamp": "2026-09-09T08:05:09Z", "availability": v["availability"]}
                           for k, v in payload["current_facts"].items()})


# =====================================================================
# 1. SPECIALIST SCHEMAS & IMMUTABLE PERSISTENCE
# =====================================================================

class TestSpecialistSchemas:
    def test_gemini_scout_output_contract(self):
        output = GeminiScoutOutput(
            receipt_id="rcpt_001",
            revision=100,
            semantic_state="POSSIBLE_REVERSAL",
            headline="Selling volume failed to break key support at 23540.",
            bullets=[
                "Selling increased, but price is not falling.",
                "Buyers absorbing at 23540.",
                "Straddle holding firm.",
            ],
            missing_evidence=["flow_net_delta"],
            deserves_luna_review=True,
        )
        d = output.to_dict()
        assert d["schema_version"] == "1.3.0-fast-scout"
        assert d["role"] == "FAST_SCOUT"
        assert d["model_id"] == GEMINI_SCOUT_MODEL_ID
        assert d["semantic_state"] in GEMINI_SEMANTIC_STATES
        assert len(d["bullets"]) <= 3
        assert d["deserves_luna_review"] is True

    def test_sol_option_specialist_output_contract(self):
        output = SolOptionSpecialistOutput(
            receipt_id="rcpt_002",
            revision=100,
            buying_state="AVOID_CHASE",
            headline="23550 CE IV stretched after fast premium expansion.",
            bullets=[
                "23550 CE IV up 1.8 vol pts in 5m.",
                "Premium already expanded 14%.",
                "Risk/reward poor for fresh longs here.",
            ],
            missing_evidence=["flow_net_delta"],
            direction_vs_trade_quality_conflict=True,
        )
        d = output.to_dict()
        assert d["schema_version"] == "1.3.0-option-specialist"
        assert d["role"] == "OPTION_SPECIALIST"
        assert d["model_id"] == SOL_CHALLENGER_MODEL_ID
        assert d["buying_state"] in SOL_BUYING_STATES
        assert len(d["bullets"]) <= 3
        assert d["direction_vs_trade_quality_conflict"] is True

    def test_immutable_artifact_persistence(self, tmp_path):
        payload = {"headline": "Test headline", "bullets": ["b1"]}
        path_str = persist_challenger_artifact(
            role="GEMINI_SCOUT",
            receipt_id="abcdef1234567890",
            revision=42,
            session_date="2026-09-09",
            payload=payload,
            base_dir=str(tmp_path),
        )
        saved = Path(path_str)
        assert saved.exists()
        with open(saved, "r") as f:
            data = json.load(f)
        assert data["parent_receipt_id"] == "abcdef1234567890"
        assert data["parent_revision"] == 42
        assert data["payload"] == payload


# =====================================================================
# 2. ADAPTERS & EVIDENCE GUARDS
# =====================================================================

class TestSpecialistAdapters:
    def test_gemini_scout_adapter_missing_evidence_guard(self):
        mock_backend = MagicMock()
        mock_backend.invoke_reasoning.return_value = (
            {
                "schema_version": "1.3.0-fast-scout",
                "role": "FAST_SCOUT",
                "semantic_state": "ABSORPTION",
                "headline": "Aggressive sellers absorbed at 23540.",
                "bullets": ["Aggressive selling met by deep bids."],
                "missing_evidence": ["flow_net_delta"],
                "deserves_luna_review": False,
            },
            {"status": "CURRENT", "latency_ms": 120.0},
        )
        adapter = GeminiScoutAdapter(backend=mock_backend)
        # Payload where flow is UNAVAILABLE
        payload = make_sample_payload(revision=10, cvd=None, mlofi=None)
        receipt = CanonicalShadowReceipt.from_packet_payload(payload, revision=10)

        out, tel = adapter.analyze(receipt)
        assert out is None
        assert tel["status"] == "CANONICAL_PACKET_REQUIRED"
        mock_backend.invoke_reasoning.assert_not_called()

    def test_sol_specialist_adapter_max_bullets_and_state(self):
        mock_backend = MagicMock()
        mock_backend.invoke_reasoning.return_value = (
            {
                "schema_version": "1.3.0-option-specialist",
                "role": "OPTION_SPECIALIST",
                "buying_state": "CALL_ATTRACTIVE",
                "headline": "23550 CE offers clean risk-defined entry.",
                "bullets": ["IV subdued at 10.4%", "Basis compressed", "Clean asymmetry", "Extra bullet"],
                "missing_evidence": [],
                "direction_vs_trade_quality_conflict": False,
            },
            {"status": "CURRENT", "latency_ms": 250.0},
        )
        adapter = SolOptionSpecialistAdapter(backend=mock_backend)
        payload = make_sample_payload(revision=12)
        receipt = CanonicalShadowReceipt.from_packet_payload(payload, revision=12)

        out, tel = adapter.analyze(receipt)
        assert out is None
        assert tel["status"] == "CANONICAL_PACKET_REQUIRED"
        mock_backend.invoke_reasoning.assert_not_called()


# =====================================================================
# 3. LIVE SHADOW ORCHESTRATOR RUNTIME & CONCURRENCY
# =====================================================================

class TestLiveShadowOrchestrator:
    def test_safety_invariants_hardened(self):
        assert AI_EXECUTION_INFLUENCE == 0.0
        assert BROKER_SUBMISSION is False
        assert AI_VOB_INFLUENCE == 0.0

    def test_bounded_concurrency_one_in_flight(self, tmp_path):
        mock_gemini = MagicMock(spec=GeminiScoutAdapter)
        mock_sol = MagicMock(spec=SolOptionSpecialistAdapter)

        def slow_gemini(*args, **kwargs):
            time.sleep(0.1)
            return (
                GeminiScoutOutput(
                    receipt_id="r1",
                    revision=10,
                    semantic_state="FLOW_SHIFT",
                    headline="Shift in flow",
                    bullets=["b1"],
                ),
                {"status": "CURRENT"},
            )

        mock_gemini.analyze.side_effect = slow_gemini
        status_file = tmp_path / "shadow_status.json"
        orch = LiveShadowOrchestrator(
            gemini_adapter=mock_gemini,
            sol_adapter=mock_sol,
            status_path=str(status_file),
            gemini_enabled=True,
        )

        packet1 = make_sample_packet(revision=10, basis=28.5)
        # First call triggers Gemini (since basis changed / first cycle)
        with patch.object(orch.router, "evaluate_routing") as mock_route:
            mock_route.return_value = MagicMock(
                invoke_luna=False,
                invoke_gemini=True,
                invoke_sol=False,
            )
            res1 = orch.process_live_packet(packet1)
            assert res1["dispatched_gemini"] is True

            # Immediate second call while in flight: should NOT dispatch a duplicate
            packet2 = make_sample_packet(revision=11, basis=28.5)
            res2 = orch.process_live_packet(packet2)
            assert res2["dispatched_gemini"] is False

    def test_stale_result_dropped_from_projection(self, tmp_path):
        status_file = tmp_path / "shadow_status.json"
        orch = LiveShadowOrchestrator(status_path=str(status_file))

        receipt = CanonicalShadowReceipt.from_packet_payload(
            make_sample_payload(revision=10), revision=10
        )
        packet = make_sample_packet(revision=10)

        # Simulate that latest revision has advanced way past rev 10 (e.g. to 20)
        orch._latest_revision = 20

        # Simulate Gemini completion for rev 10
        mock_out = GeminiScoutOutput(
            receipt_id=receipt.receipt_id,
            revision=10,
            semantic_state="CONTROL_STABLE",
            headline="Old state",
            bullets=["b1"],
        )
        orch.gemini_adapter.analyze = MagicMock(return_value=(mock_out, {"status": "CURRENT"}))

        orch._run_gemini_async(receipt, packet)

        # Stale count increased
        assert orch.metrics["gemini_stale_dropped"] == 1
        # Not promoted to latest view
        assert orch._latest_gemini_view is None


# =====================================================================
# 4. COGNITIVE PROJECTION INTEGRATION
# =====================================================================

class TestCognitiveProjection:
    def test_project_cognitive_decision_rejects_unbound_specialists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(LiveShadowOrchestrator, "_instance", None)
        # Write dummy shadow status
        status_file = Path("data/sol_shadow/live_shadow_status.json")
        status_file.parent.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(timezone.utc).isoformat()
        dummy_status = {
            "gemini_scout": {
                "semantic_state": "POSSIBLE_REVERSAL",
                "headline": "Selling paused at 23540.",
                "bullets": ["Selling paused.", "Straddle holding."],
                "missing_evidence": [],
                "updated_at": now_iso,
            },
            "sol_option_specialist": {
                "buying_state": "AVOID_CHASE",
                "headline": "Option stretch.",
                "bullets": ["IV high.", "Decay risk."],
                "missing_evidence": [],
                "updated_at": now_iso,
            },
        }
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(dummy_status, f)

        res = project_cognitive_decision(
            active=None,
            previous=None,
            live_status={},
            snapshot={"system_status": "HEALTHY"},
        )

        assert "gemini_scout" in res
        assert "sol_option_specialist" in res
        assert res["gemini_scout"] is None
        assert res["sol_option_specialist"] is None


# =====================================================================
# 5. PHASE 13 — FAILURE ISOLATION TESTS
# =====================================================================

class TestFailureIsolation:
    def test_gemini_timeout_isolation(self, tmp_path):
        """Gemini timeout: Luna continues, Sol continues, deterministic Oracle continues."""
        status_file = tmp_path / "shadow_status.json"
        mock_gemini = MagicMock(spec=GeminiScoutAdapter)
        mock_gemini.analyze.side_effect = TimeoutError("Gemini timed out after 30s")

        mock_sol = MagicMock(spec=SolOptionSpecialistAdapter)
        sol_out = SolOptionSpecialistOutput(
            receipt_id="r_sol",
            revision=10,
            buying_state="AVOID_CHASE",
            headline="Sol evaluated successfully",
            bullets=["b1"],
        )
        mock_sol.analyze.return_value = (sol_out, {"status": "CURRENT"})

        orch = LiveShadowOrchestrator(
            gemini_adapter=mock_gemini,
            sol_adapter=mock_sol,
            status_path=str(status_file),
        )

        receipt = CanonicalShadowReceipt.from_packet_payload(
            make_sample_payload(revision=10), revision=10
        )
        packet = make_sample_packet(revision=10)

        # Execute both
        mock_sol.analyze.return_value = (replace(sol_out, receipt_id=receipt.receipt_id), {"status": "CURRENT"})
        orch._latest_receipt_id, orch._latest_session = receipt.receipt_id, receipt.session_date
        orch._run_gemini_async(receipt, packet)
        orch._run_sol_async(receipt, packet)

        # Gemini recorded failure, in_flight reset
        assert orch.metrics["gemini_failures"] == 1
        assert orch._gemini_in_flight is False
        assert orch._latest_gemini_view is None

        # Sol completed successfully despite Gemini failure
        assert orch.metrics["sol_completions"] == 1
        assert orch._sol_in_flight is False
        assert orch._latest_sol_view is not None
        assert orch._latest_sol_view["buying_state"] == "AVOID_CHASE"

        # Invariants preserved
        assert AI_EXECUTION_INFLUENCE == 0.0
        assert BROKER_SUBMISSION is False
        assert AI_VOB_INFLUENCE == 0.0

    def test_sol_timeout_isolation(self, tmp_path):
        """Sol timeout: Luna continues, Gemini continues."""
        status_file = tmp_path / "shadow_status.json"
        mock_sol = MagicMock(spec=SolOptionSpecialistAdapter)
        mock_sol.analyze.side_effect = TimeoutError("Sol timed out after 45s")

        mock_gemini = MagicMock(spec=GeminiScoutAdapter)
        gem_out = GeminiScoutOutput(
            receipt_id="r_gem",
            revision=10,
            semantic_state="FLOW_SHIFT",
            headline="Gemini evaluated successfully",
            bullets=["b1"],
        )
        mock_gemini.analyze.return_value = (gem_out, {"status": "CURRENT"})

        orch = LiveShadowOrchestrator(
            gemini_adapter=mock_gemini,
            sol_adapter=mock_sol,
            status_path=str(status_file),
        )

        receipt = CanonicalShadowReceipt.from_packet_payload(
            make_sample_payload(revision=10), revision=10
        )
        packet = make_sample_packet(revision=10)

        mock_gemini.analyze.return_value = (replace(gem_out, receipt_id=receipt.receipt_id), {"status": "CURRENT"})
        orch._latest_receipt_id, orch._latest_session = receipt.receipt_id, receipt.session_date
        orch._run_gemini_async(receipt, packet)
        orch._run_sol_async(receipt, packet)

        assert orch.metrics["sol_failures"] == 1
        assert orch._sol_in_flight is False
        assert orch._latest_sol_view is None

        assert orch.metrics["gemini_completions"] == 1
        assert orch._gemini_in_flight is False
        assert orch._latest_gemini_view is not None
        assert orch._latest_gemini_view["semantic_state"] == "FLOW_SHIFT"

    def test_luna_timeout_does_not_promote_specialists_to_official_state(self):
        """When Luna fails or times out, specialists do NOT become official state, execution remains zero."""
        # Simulated projection when Luna has no accepted output
        res = project_cognitive_decision(
            active=None,
            previous=None,
            live_status={
                "status": "TIMEOUT",
                "error_category": "PROVIDER_TIMEOUT",
            },
            snapshot={"system_status": "HEALTHY"},
        )

        # Primary decision must not take specialist values
        assert res["primary_decision"]["state"] is None
        assert res["primary_decision"]["entry_window"] is None
        assert res["primary_decision"]["model_tension"] is None
        # Safety gate unchanged
        assert AI_EXECUTION_INFLUENCE == 0.0
        assert BROKER_SUBMISSION is False

    def test_malformed_gemini_output_rejected(self, tmp_path):
        """Malformed Gemini response is rejected and does not damage state."""
        status_file = tmp_path / "shadow_status.json"
        mock_backend = MagicMock()
        # Missing required headline and bullets
        mock_backend.invoke_reasoning.return_value = (
            None,
            {"status": "FAILED", "error": "SchemaValidationFailed: Missing headline"},
        )
        adapter = GeminiScoutAdapter(backend=mock_backend)
        receipt = CanonicalShadowReceipt.from_packet_payload(
            make_sample_payload(revision=10), revision=10
        )
        out, tel = adapter.analyze(receipt, make_sample_packet(10))
        assert out is None
        assert tel["status"] == "FAILED"

        orch = LiveShadowOrchestrator(
            gemini_adapter=adapter,
            status_path=str(status_file),
        )
        orch._run_gemini_async(receipt, make_sample_packet(revision=10))
        assert orch.metrics["gemini_failures"] == 1
        assert orch._latest_gemini_view is None

    def test_malformed_sol_output_rejected(self, tmp_path):
        """Malformed Sol response is rejected and does not damage state."""
        status_file = tmp_path / "shadow_status.json"
        mock_backend = MagicMock()
        mock_backend.invoke_reasoning.return_value = (
            None,
            {"status": "FAILED", "error": "JSONDecodeError"},
        )
        adapter = SolOptionSpecialistAdapter(backend=mock_backend)
        receipt = CanonicalShadowReceipt.from_packet_payload(
            make_sample_payload(revision=10), revision=10
        )
        out, tel = adapter.analyze(receipt, make_sample_packet(10))
        assert out is None
        assert tel["status"] == "FAILED"

        orch = LiveShadowOrchestrator(
            sol_adapter=adapter,
            status_path=str(status_file),
        )
        orch._run_sol_async(receipt, make_sample_packet(revision=10))
        assert orch.metrics["sol_failures"] == 1
        assert orch._latest_sol_view is None
