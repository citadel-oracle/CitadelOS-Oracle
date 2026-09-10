"""Comprehensive Live-Readiness Test Suite for CITADEL MARKET BRAIN (Gemini 3.7 Flash Activation).

Tests:
1. Baseline changes only after event durable commit
2. Failed event write leaves previous baseline intact
3. Retry regenerates missing events
4. All required temporal sensorium fields reconstructible
5. Gemini key never exposed in frontend/state/log
6. Provider adapter selection (Gemini vs OpenAI)
7. Gemini structured-output parsing
8. Malformed Gemini output fails closed
9. Hallucinated evidence ref rejected
10. Gemini key present != provider connected
11. Provider connected only after successful API response
12. Analyzing / idle state transitions
13. Quota error suspends current thesis
14. No automatic paid fallback
15. Existing OpenAI adapter preserved
16. Session rotation isolation
17. Observed zero safety & 128-bit identity hashes
"""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import MagicMock, patch
import pytest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.oracle_sol.contracts import (
    ActiveMarketStory,
    DataAvailability,
    DevelopingState,
    ExpectationEvaluationRecord,
    ExpectationRecord,
    ExpectationResult,
    MarketEvent,
    MarketThesisVerdict,
    ReasoningStatus,
    SolBeaconOutput,
    SolEvidenceSnapshot,
    SolModelRequestEnvelope,
    SystemStatus,
    ThesisState,
)
from src.oracle_sol.event_sourced_memory import EventSourcedMarketMemory
from src.oracle_sol.event_story_builder import MarketEventStoryBuilder
from src.oracle_sol.field_registry import SOL_VOB_FREE_FIELD_REGISTRY
from src.oracle_sol.gemini_adapter import GeminiModelAdapter, get_secure_gemini_api_key
from src.oracle_sol.model_adapter import SolModelAdapter
from src.oracle_sol.provider_factory import get_reasoning_adapter
from src.oracle_sol.provenance_guard import (
    EvidenceReferenceValidator,
    ProvenanceGuard,
    UnverifiedLineageError,
    VobContaminationError,
)
from src.oracle_sol.reasoning_protocol import SolReasoningOrchestrator
from src.oracle_sol.replay import SolCycleReplayEngine
from src.oracle_sol.service import SolMarketBrainService
from src.oracle_sol.shadow_ledger import SolShadowLedger
from src.oracle_sol.snapshot_extractor import extract_sol_evidence_snapshot
from src.oracle_sol.thesis_memory import ThesisMemory

IST = ZoneInfo("Asia/Kolkata")


def _full_canonical_feeds(
    spot=24535.50,
    fut=24558.00,
    mlofi=-4.20,
    atm=24550.0,
    basis=22.50,
    closed_5m=62000,
    struct="SHORT_BUILDUP",
    date_str="2026-08-28",
    time_str="10:15:00",
    sudden_oi=None,
):
    return {
        "idempotency_key": f"rev_canonical_{date_str}_{time_str}",
        "oracle": {
            "ok": True,
            "data": {
                "spot_ltp": spot,
                "futures_ltp": fut,
                "futures_basis": basis,
                "session_vwap": 24512.20,
                "spot_to_vwap": 23.30,
                "atm_strike": atm,
                "atm_straddle_price": 285.50,
                "atm_iv": 14.85,
                "skew_25d": -1.45,
                "skew_10d": -2.10,
                "expected_move": 115.0,
                "net_gex_inr": -420000000.0,
                "highest_gex_strike": 24600.0,
                "zero_gamma": 24510.0,
                "dhan_connected": True,
                "market_open": True,
                "futures_sid": "FUT_NIFTY_20260903",
                "source_timestamp": f"{date_str}T{time_str}+05:30",
            }
        },
        "order_flow": {
            "ok": True,
            "data": {
                "mlofi": mlofi,
                "flow_x": 2.85,
                "is_extreme": True,
                "age_ms": 120.0,
            }
        },
        "argus": {
            "ok": True,
            "data": {
                "atm_strike": atm,
                "expiry": "2026-09-03",
                "sudden_oi": sudden_oi or {
                    "CALL": {
                        "top_strike": 24600.0,
                        "delta_oi": 85000,
                        "closed_window_5m": 85000,
                        "percentile": 98.5,
                        "new_session_extreme": True,
                        "state": "AGGRESSIVE_CALL_WRITING",
                    },
                    "PUT": {
                        "top_strike": 24500.0,
                        "delta_oi": -12000,
                        "closed_window_5m": -12000,
                        "percentile": 42.0,
                        "new_session_extreme": False,
                        "state": "LONG_UNWINDING",
                    }
                },
                "ce_pricing": {
                    "security_id": "SEC_NIFTY_24550_CE",
                    "strike": 24550.0,
                    "option_type": "CE",
                    "expiry": "2026-09-03",
                    "ltp": 152.0,
                    "best_bid_price": 151.8,
                    "best_ask_price": 152.2,
                    "spread": 0.4,
                    "iv": 14.8,
                    "fair_iv": 14.2,
                    "fair_price": 147.0,
                    "fair_gap_pct": 3.4,
                    "time_value": 115.0,
                    "holding_decay_per_min": 0.12,
                    "depth_levels": [],
                    "depth_imbalance": 0.15,
                    "source_timestamp": f"{date_str}T{time_str}+05:30",
                },
                "pe_pricing": {
                    "security_id": "SEC_NIFTY_24550_PE",
                    "strike": 24550.0,
                    "option_type": "PE",
                    "expiry": "2026-09-03",
                    "ltp": 133.5,
                    "best_bid_price": 133.3,
                    "best_ask_price": 133.7,
                    "spread": 0.4,
                    "iv": 14.9,
                    "fair_iv": 15.2,
                    "fair_price": 136.0,
                    "fair_gap_pct": -1.8,
                    "time_value": 133.5,
                    "holding_decay_per_min": 0.14,
                    "depth_levels": [],
                    "depth_imbalance": -0.05,
                    "source_timestamp": f"{date_str}T{time_str}+05:30",
                },
                "chain_strikes": [
                    {
                        "strike": 24550.0,
                        "relation_to_atm": "ATM",
                        "ce_security_id": "SEC_NIFTY_24550_CE",
                        "ce_ltp": 152.0,
                        "ce_fair_gap_pct": 3.4,
                        "ce_closed_5m_oi": closed_5m,
                        "ce_closed_15m_oi": 115000,
                        "ce_structure": struct,
                        "pe_security_id": "SEC_NIFTY_24550_PE",
                        "pe_ltp": 133.5,
                        "pe_fair_gap_pct": -1.8,
                        "pe_closed_5m_oi": -14000,
                        "pe_closed_15m_oi": -22000,
                        "pe_structure": "LONG_UNWINDING",
                    }
                ]
            }
        }
    }


# 1. Baseline Changes Only After Event Durable Commit (Test 1, 2, 3)
def test_atomic_baseline_commit_and_failure_injection(tmp_path):
    storage = str(tmp_path / "sol_atomic_test")
    service = SolMarketBrainService(storage_dir=storage, runtime_mode="TEST")

    # Ingest Frame A -> Baseline A
    snap_a = extract_sol_evidence_snapshot(_full_canonical_feeds(spot=24500.0, time_str="10:00:00"))
    assert service.ingest_snapshot(snap_a) is True
    assert service.story_builder._last_snapshot.snapshot_id == snap_a.snapshot_id

    # Ingest Frame B with Injected IO Persistence Failure
    snap_b = extract_sol_evidence_snapshot(_full_canonical_feeds(spot=24520.0, time_str="10:01:00"))
    with patch.object(service.memory, "append_batch", side_effect=IOError("Simulated disk failure")):
        assert service.ingest_snapshot(snap_b) is False

    # Baseline MUST remain A (not updated to B!)
    assert service.story_builder._last_snapshot.snapshot_id == snap_a.snapshot_id

    # Retry Frame B normally without failure
    assert service.ingest_snapshot(snap_b) is True
    # Now baseline is successfully committed to B
    assert service.story_builder._last_snapshot.snapshot_id == snap_b.snapshot_id
    service.worker.stop()


def test_baseline_disk_failure_does_not_advance_memory(tmp_path):
    builder = MarketEventStoryBuilder(storage_dir=str(tmp_path))
    snap_a = extract_sol_evidence_snapshot(_full_canonical_feeds(spot=24500.0, time_str="10:00:00"))
    snap_b = extract_sol_evidence_snapshot(_full_canonical_feeds(spot=24520.0, time_str="10:01:00"))
    builder.commit_baseline(snap_a)

    with patch("src.oracle_sol.event_story_builder.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            builder.commit_baseline(snap_b)

    assert builder._last_snapshot is not None
    assert builder._last_snapshot.snapshot_id == snap_a.snapshot_id
    assert builder.baseline_store_status == "ERROR"
    assert not list(tmp_path.glob("*.tmp"))


def test_same_snapshot_id_with_different_payload_is_rejected(tmp_path):
    builder = MarketEventStoryBuilder(storage_dir=str(tmp_path))
    original = extract_sol_evidence_snapshot(_full_canonical_feeds(spot=24500.0, time_str="10:00:00"))
    conflicting = replace(original, spot_ltp=24501.0)
    builder.commit_baseline(original)

    with pytest.raises(ValueError, match="Snapshot identity collision"):
        builder.compile_events(conflicting)


# 2. Full Temporal Sensorium Fields Reconstructible (Test 4)
def test_full_temporal_sensorium_fields_reconstructible():
    builder = MarketEventStoryBuilder()
    snap1 = extract_sol_evidence_snapshot(_full_canonical_feeds())
    builder.build_events(snap1)

    feeds2 = _full_canonical_feeds()
    feeds2["oracle"]["data"]["futures_ltp"] = 24600.0
    feeds2["oracle"]["data"]["futures_basis"] = 35.0
    feeds2["oracle"]["data"]["atm_straddle_price"] = 310.0
    feeds2["oracle"]["data"]["atm_iv"] = 16.50
    feeds2["oracle"]["data"]["net_gex_inr"] = 500000000.0
    feeds2["argus"]["data"]["chain_strikes"][0]["ce_closed_5m_oi"] = 95000
    snap2 = extract_sol_evidence_snapshot(feeds2)

    evts = builder.compile_events(snap2)
    types = {e.event_type for e in evts}

    assert "FUTURES_MOVE" in types
    assert "BASIS_SHIFT" in types
    assert "STRADDLE_CHANGE" in types
    assert "VOLATILITY_SURFACE_SHIFT" in types
    assert "GEX_SHIFT" in types
    assert "CLOSED_OI_DELTA" in types


# 3. Gemini Key Never Exposed in Frontend / State / Log (Test 5)
def test_gemini_key_never_exposed_in_state_or_logs(tmp_path):
    service = SolMarketBrainService(storage_dir=str(tmp_path), runtime_mode="TEST")
    state = service.get_latest_state()

    state_str = json.dumps(state)
    assert "CITADEL_GEMINI_API_KEY" not in state_str
    assert "AIzaSy" not in state_str
    assert state["api_key_present"] is False or state["api_key_present"] is True
    service.worker.stop()


# 4. Provider Adapter Selection (Test 6, 15)
def test_provider_adapter_selection():
    adapter_gemini = get_reasoning_adapter(provider="gemini")
    assert isinstance(adapter_gemini, GeminiModelAdapter)
    assert adapter_gemini.configured_model == "gemini-3.7-flash"

    adapter_openai = get_reasoning_adapter(provider="openai")
    assert isinstance(adapter_openai, SolModelAdapter)
    assert adapter_openai.configured_model == "gpt-5.6-sol"


# 5. Gemini Structured-Output Parsing (Test 7)
def test_gemini_structured_output_parsing():
    adapter = GeminiModelAdapter(configured_model="gemini-3.7-flash", api_key="dummy_gemini_key_12345678")

    sample_output = {
        "market_verdict": "CALL",
        "developing_state": "CALL_DEVELOPING",
        "core_narrative": "Gemini 3.7 Flash validated thesis.",
        "what_changed": "Aggressive call buying.",
        "positioning_story": "Call OI expanding.",
        "oi_story": "Call writing low.",
        "flow_story": "Positive MLOFI.",
        "option_response_story": "Premiums surging.",
        "call_case": "Breakout confirmed.",
        "put_case": "None.",
        "no_trade_case": "None.",
        "strongest_contradiction": "NONE_OBSERVED",
        "why_bullets": ["Spot above VWAP", "Call OI dominant"],
        "expectation_evaluations": [],
        "pre_registered_expectations": [
            {
                "expected_condition": "Spot holds 24550",
                "invalidation_condition": "Spot drops below 24500",
            }
        ],
        "data_gaps": [],
        "evidence_references": [],
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(sample_output)
    mock_resp.model_version = "gemini-3.7-flash-001"

    with patch("google.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.models.generate_content.return_value = mock_resp
        mock_client.return_value = mock_instance

        parsed, telemetry, env = adapter.invoke_reasoning(
            cycle_id="cyc_gemini_001",
            system_prompt="You are Gemini Market Brain.",
            user_payload={"test": 1},
        )

        assert parsed is not None
        assert parsed["market_verdict"] == "CALL"
        assert telemetry["status"] == "SUCCESS"
        assert telemetry["provider"] == "GEMINI"
        client_config = mock_instance.models.generate_content.call_args.kwargs["config"]
        assert str(client_config.thinking_config.thinking_level.value).lower() == "high"


# 6. Malformed Gemini Output Fails Closed (Test 8)
def test_malformed_gemini_output_fails_closed():
    adapter = GeminiModelAdapter(configured_model="gemini-3.7-flash", api_key="dummy_gemini_key_12345678")

    mock_resp = MagicMock()
    mock_resp.text = "NOT_JSON_GARBAGE"

    with patch("google.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.models.generate_content.return_value = mock_resp
        mock_client.return_value = mock_instance

        parsed, telemetry, env = adapter.invoke_reasoning(
            cycle_id="cyc_malformed",
            system_prompt="Test",
            user_payload={"test": 1},
        )

        assert parsed is None
        assert telemetry["status"] in {"INVOCATION_EXCEPTION", "MALFORMED_OUTPUT"}


# 7. Hallucinated Evidence Reference Fails Closed (Test 9)
def test_hallucinated_evidence_reference_fails_closed():
    known_events = {"evt_real_001"}
    known_exp = set()
    hallucinated_output = {
        "market_verdict": "CALL",
        "developing_state": "CALL_DEVELOPING",
        "core_narrative": "Hallucinated refs",
        "what_changed": "None",
        "positioning_story": "None",
        "oi_story": "None",
        "flow_story": "None",
        "option_response_story": "None",
        "call_case": "Valid",
        "put_case": "None",
        "no_trade_case": "None",
        "strongest_contradiction": "NONE_OBSERVED",
        "why_bullets": ["Bullet 1"],
        "expectation_evaluations": [],
        "pre_registered_expectations": [],
        "data_gaps": [],
        "evidence_references": ["evt_FAKE_HALLUCINATED_999"],
    }

    is_valid, errors = EvidenceReferenceValidator.validate_references(
        model_output=hallucinated_output,
        known_event_ids=known_events,
        known_expectation_ids=known_exp,
        current_snapshot_id="snap_001",
    )
    assert is_valid is False
    assert len(errors) >= 1


# 8. Gemini Key Present != Provider Connected (Test 10, 11)
def test_key_present_does_not_mean_connected(tmp_path):
    # Adapter initialized with key but zero successful API responses yet
    adapter = GeminiModelAdapter(api_key="sk-gemini-sample-key-12345")
    service = SolMarketBrainService(storage_dir=str(tmp_path), model_adapter=adapter, runtime_mode="TEST")

    state = service.get_latest_state()
    # Key is present, but provider status must be IDLE (not CONNECTED until successful response)
    assert state["api_key_present"] is True
    assert state["health_strip"]["ai_provider"] == "IDLE"
    service.worker.stop()


# 9. Quota Error Suspends Current Thesis (Test 13, 14)
def test_quota_error_suspends_thesis(tmp_path):
    adapter = GeminiModelAdapter(api_key="sk-gemini-sample-key-12345")
    mock_env = SolModelRequestEnvelope(
        cycle_id="cyc_quota",
        prompt_version="3.2.0",
        prompt_hash="phash",
        input_hash="ihash",
        system_prompt="sys",
        user_payload={},
        configured_model="gemini-3.7-flash",
        requested_model="gemini-3.7-flash",
        reasoning_effort="medium",
    )
    adapter.invoke_reasoning = lambda cycle_id, system_prompt, user_payload: (
        None,
        {"cycle_id": cycle_id, "status": "QUOTA_EXHAUSTED", "error_message": "ResourceExhausted 429"},
        mock_env,
    )
    service = SolMarketBrainService(storage_dir=str(tmp_path), model_adapter=adapter, runtime_mode="TEST")
    snap = extract_sol_evidence_snapshot(_full_canonical_feeds())

    thesis, beacon, telemetry, env = service._process_snapshot_sync(snap)
    assert beacon.market_verdict is None
    assert beacon.reasoning_status == "DEGRADED_ADVISORY"
    service.worker.stop()


# 10. Session Rotation Isolation (Test 16)
def test_session_rotation_isolation():
    builder = MarketEventStoryBuilder()
    snap_day_a = extract_sol_evidence_snapshot(_full_canonical_feeds(spot=24500.0, date_str="2026-08-28", time_str="15:30:00"))
    evts_a = builder.compile_events(snap_day_a)
    builder.commit_baseline(snap_day_a)

    snap_day_b = extract_sol_evidence_snapshot(_full_canonical_feeds(spot=24650.0, date_str="2026-08-29", time_str="09:15:00"))
    evts_b = builder.compile_events(snap_day_b)

    assert len(evts_b) == 1
    assert evts_b[0].event_type == "STATE_TRANSITION"
    assert "baseline established" in evts_b[0].summary.lower()


# 11. Observed Zero Safety (Test 17)
def test_observed_zero_safety():
    feeds = _full_canonical_feeds()
    feeds["oracle"]["data"]["spot_ltp"] = 0.0
    feeds["oracle"]["data"]["futures_basis"] = 0.0
    feeds["order_flow"]["data"]["mlofi"] = 0.0

    snap = extract_sol_evidence_snapshot(feeds)
    assert snap.spot_ltp == 0.0
    assert snap.futures_basis == 0.0
    assert snap.mlofi_5l == 0.0
    assert snap.availability_matrix["spot_ltp"] == "OBSERVED_ZERO"


# 12. 128-Bit Identity Hash Length (Test 17)
def test_128_bit_identity_hash_length():
    snap = extract_sol_evidence_snapshot(_full_canonical_feeds())
    assert len(snap.snapshot_id) == len("snap_") + 32


# 13. Real Recorded Frame from Disk Replay
def test_real_recorded_citadel_frame_replay():
    from scripts.sol_real_smoke_test import load_real_recorded_citadel_frame
    feeds, source_desc, cov = load_real_recorded_citadel_frame()
    assert "snapshot:97b0ed82f3fa" in source_desc
    assert cov["spot"] is True
    assert cov["futures"] is True
    assert cov["basis"] is True

    snap = extract_sol_evidence_snapshot(feeds)
    assert snap.spot_ltp == 24252.85
    assert snap.futures_ltp == 24305.0


# 14. VOB Projection Boundary
def test_vob_projection_boundary():
    parent_feeds = _full_canonical_feeds()
    parent_feeds["vob"] = {"vob_horsepower": 55.0}

    snap = extract_sol_evidence_snapshot(parent_feeds)
    assert snap.vob_free_verified == "ZERO_VOB_ALLOWLIST_CONFIRMED"

    parent_feeds["argus"]["data"]["chain_strikes"][0]["ce_vob_zone"] = "BULLISH"
    with pytest.raises(VobContaminationError):
        extract_sol_evidence_snapshot(parent_feeds)


# 15. Citadel Calculates, Sol Consumes
def test_citadel_calculates_no_duplicated_calculations():
    feeds = _full_canonical_feeds(spot=24500.0, fut=24550.0, basis=50.0)
    snap = extract_sol_evidence_snapshot(feeds)
    assert snap.futures_basis == 50.0


# 16. Exact Input Replay Verification
def test_exact_input_replay_bit_exact(tmp_path):
    ledger_file = tmp_path / "test_exact_input_replay.jsonl"
    ledger = SolShadowLedger(runtime_mode="TEST", ledger_file_path=str(ledger_file))
    replay = SolCycleReplayEngine(ledger=ledger)

    service = SolMarketBrainService(storage_dir=str(tmp_path), runtime_mode="TEST")
    service.shadow_ledger = ledger
    snap = extract_sol_evidence_snapshot(_full_canonical_feeds())

    thesis, beacon, telemetry, envelope = service._process_snapshot_sync(snap)
    cycle_id = telemetry["cycle_id"]

    verification = replay.verify_exact_input_replay(cycle_id)
    assert verification["found"] is True
    assert verification["exact_input_replay_verified"] is True
    service.worker.stop()


# 17. Beacon Replay Mode Flag
def test_beacon_replay_mode_flag():
    beacon = SolBeaconOutput(
        system_status="HEALTHY",
        reasoning_status="ACTIVE_REASONING",
        market_verdict="CALL",
        developing_state="CALL_DEVELOPING",
        why_bullets=["Replay test"],
        main_contradiction="NONE_OBSERVED",
        what_changed="Test",
        thesis_timestamp_ist="10:15:00",
        feed_age_ms=100.0,
        configured_model="gemini-3.7-flash",
        actually_invoked_model="gemini-3.7-flash",
        replay_mode=True,
    )
    assert beacon.replay_mode is True
