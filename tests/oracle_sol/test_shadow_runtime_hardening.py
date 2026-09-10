"""Offline contract/failure tests. Synthetic observations; never provider inference."""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.privacy_sanitizer import sanitize_brain_packet
from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator
from src.oracle_sol.shadow_specialists import GeminiScoutOutput
from src.oracle_sol.shadow_orchestrator import GEMINI_SCOUT_MODEL_ID


def packet(revision=1):
    return BrainPacket(
        packet_id=f"synthetic-{revision}", session_id="2026-09-09", revision=revision,
        compiled_at="2026-09-09T04:00:00Z", canonical_state={}, what_changed={},
        unseen_event_ids=[f"synthetic-{revision}"], unseen_events_summary=[],
        previous_thesis=None, verified_external_events=[], external_quotes=[],
        valid_evidence_ids=[f"synthetic-{revision}"],
    )


@pytest.fixture
def runtime(tmp_path):
    router = Mock()
    router.evaluate_routing.return_value = SimpleNamespace(invoke_gemini=True, invoke_sol=True)
    runtime = LiveShadowOrchestrator(router, Mock(), Mock(), str(tmp_path / "status.json"), sol_enabled=True, gemini_enabled=True)
    runtime._executor.shutdown()
    runtime._executor = Mock()  # Capture tasks; execute explicitly, no threads/network.
    return runtime


def test_real_packet_dedupe_out_of_order_and_bounded_pending(runtime):
    first = runtime.process_live_packet(packet())
    assert first["dispatched_gemini"] and first["dispatched_sol"]
    assert runtime.process_live_packet(packet())["status"] == "DUPLICATE_OR_OLDER_RECEIPT"
    runtime.process_live_packet(packet(2))
    runtime.process_live_packet(packet(3))
    assert runtime._executor.submit.call_count == 2
    assert runtime._pending_gemini[0].revision == 3
    assert runtime._pending_sol[0].revision == 3
    assert runtime.process_live_packet(packet(2))["status"] == "DUPLICATE_OR_OLDER_RECEIPT"


def test_one_revision_late_response_is_not_current(runtime):
    runtime.process_live_packet(packet())
    receipt, original = runtime._executor.submit.call_args_list[0].args[1:]
    runtime.process_live_packet(packet(2))
    output = GeminiScoutOutput(model_id=GEMINI_SCOUT_MODEL_ID, receipt_id=receipt.receipt_id,
                               revision=1, headline="No classified flow supplied.")
    runtime.gemini_adapter.analyze.return_value = (output, {"status": "CURRENT"})
    runtime._run_gemini_async(receipt, original)
    assert runtime._latest_gemini_view is None
    assert runtime.metrics["gemini_stale_dropped"] == 1
    assert runtime._gemini_in_flight  # One coalesced replacement, not a backlog.


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError("HTTP failure"), ValueError("malformed output")])
def test_provider_failure_isolated(runtime, error):
    runtime.process_live_packet(packet())
    receipt, original = runtime._executor.submit.call_args_list[0].args[1:]
    runtime.gemini_adapter.analyze.side_effect = error
    runtime._run_gemini_async(receipt, original)
    assert runtime.metrics["gemini_failures"] == 1
    assert not runtime._gemini_in_flight
    assert runtime._sol_in_flight


def test_future_and_wrong_frontier_never_current(runtime):
    runtime.process_live_packet(packet())
    runtime._latest_gemini_view = dict(updated_at="2099-01-01T00:00:00Z", receipt_id=runtime._latest_receipt_id,
                                     session_date="2026-09-09", headline="Synthetic")
    assert runtime.get_projected_views()["gemini_scout"]["status"] != "CURRENT"
    runtime._latest_gemini_view.update(updated_at=datetime.now(timezone.utc).isoformat(), receipt_id="wrong")
    assert runtime.get_projected_views()["gemini_scout"]["status"] != "CURRENT"


def test_previous_assertion_not_fact_and_packet_roundtrip():
    original = replace(packet(), previous_thesis=dict(session_id="2026-09-09", state="WAIT",
        thesis_evolution="HOLDING", opportunity_maturity="EARLY", counter_case="Price response remains unresolved."))
    payload = sanitize_brain_packet(BrainPacket.from_dict(original.to_dict()))
    assert payload["previous_model_view"]["state"] == "WAIT"
    assert payload["previous_model_view"]["kind"] == "PREVIOUS_MODEL_ASSERTION_NOT_CANONICAL_FACT"
    assert all(f["value"] is None for f in payload["current_facts"].values())


@pytest.mark.parametrize("bad", [None, "invented_id", "unsupported_absorption"])
def test_specialist_exact_request_and_semantic_rejection(tmp_path, monkeypatch, bad):
    import src.oracle_sol.shadow_specialists as specialists
    from src.oracle_sol.shadow_orchestrator import CanonicalShadowReceipt
    from src.oracle_sol.luna_input_receipt import valid_binding
    monkeypatch.setattr(specialists, "REQUEST_RECEIPT_DIR", str(tmp_path / "inputs"))
    monkeypatch.setattr(specialists, "persist_challenger_artifact", lambda *a, **kw: "isolated-audit")
    item = replace(packet(), canonical_state={"spot_price": 100}, valid_evidence_ids=["metric:spot_price"],
        evidence_registry={"metric:spot_price": {"value": 100, "availability": "RECORDED", "timestamp": "2026-09-09T04:00:00Z"}})
    response = dict(schema_version="1.3.0-fast-scout", role="FAST_SCOUT", semantic_state="UNKNOWN",
        headline="Price is recorded; trade-side evidence is unavailable.", bullets=[], missing_evidence=["flow_net_delta"],
        deserves_luna_review=False, evidence_ids=["metric:spot_price"])
    if bad == "invented_id":
        response["evidence_ids"] = ["invented"]
    if bad == "unsupported_absorption":
        response["headline"] = "Aggressive sellers absorbed by institutional bids."
    def invoke(**kw):
        body = json.dumps({"model": GEMINI_SCOUT_MODEL_ID, "messages": [{"content": kw["user_prompt"]}]}).encode()
        kw["before_send"](body)
        assert list((tmp_path / "inputs").glob("*.json"))  # BEFORE transport returns.
        return response, {"status": "CURRENT"}
    backend = Mock()
    backend.invoke_reasoning.side_effect = invoke
    adapter = specialists.GeminiScoutAdapter(backend=backend)
    receipt = CanonicalShadowReceipt.from_packet_payload(sanitize_brain_packet(item), item.revision)
    output, telemetry = adapter.analyze(receipt, item)
    if bad:
        assert output is None and telemetry["status"] == "REJECTED"
    else:
        assert output is not None
        assert valid_binding(telemetry["input_receipt"], response, item.session_id, item.revision, GEMINI_SCOUT_MODEL_ID)


def test_runtime_format_view_rejects_revision_mismatch_and_unsupported_flag(runtime, monkeypatch):
    import src.oracle_sol.shadow_runtime as shadow_runtime
    monkeypatch.setattr(shadow_runtime, "validated_specialist_view", lambda x: True)
    runtime.process_live_packet(packet(10))
    now_iso = datetime.now(timezone.utc).isoformat()
    # 1. Revision mismatch between specialist view and runtime latest revision
    runtime._latest_gemini_view = {
        "schema_version": "1.3.0-fast-scout",
        "model_id": GEMINI_SCOUT_MODEL_ID,
        "role": "FAST_SCOUT",
        "receipt_id": runtime._latest_receipt_id,
        "revision": 9,  # Older revision than runtime's 10
        "session_date": "2026-09-09",
        "semantic_state": "FLOW_SHIFT",
        "headline": "Revision 9 headline",
        "bullets": ["b1"],
        "evidence_ids": ["metric:spot"],
        "updated_at": now_iso,
        "telemetry": {
            "validation_status": "ACCEPTED",
            "validated_output": {
                "schema_version": "1.3.0-fast-scout",
                "role": "FAST_SCOUT",
                "semantic_state": "FLOW_SHIFT",
                "headline": "Revision 9 headline",
                "bullets": ["b1"],
                "missing_evidence": [],
                "evidence_ids": ["metric:spot"],
                "deserves_luna_review": False,
            },
        },
    }
    views = runtime.get_projected_views()
    # Mismatched revision must be STALE, never CURRENT
    assert views["gemini_scout"]["status"] == "STALE"

    # 2. Unsupported inference flag must force STALE
    runtime._latest_gemini_view["revision"] = 10
    runtime._latest_gemini_view["unsupported_inference_flag"] = True
    views = runtime.get_projected_views()
    assert views["gemini_scout"]["status"] == "STALE"


def test_projection_rejects_specialist_when_luna_revision_is_newer(tmp_path, monkeypatch):
    from src.oracle_sol.cognitive_projection import project_cognitive_decision
    monkeypatch.chdir(tmp_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    status_file = tmp_path / "data/sol_shadow/live_shadow_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write a status file at revision 10
    payload = {
        "updated_at_utc": now_iso,
        "latest_revision": 10,
        "latest_receipt_id": "rcpt_10",
        "session_date": "2026-09-09",
        "gemini_in_flight": False,
        "sol_in_flight": False,
        "gemini_scout": {
            "schema_version": "1.3.0-fast-scout",
            "model_id": GEMINI_SCOUT_MODEL_ID,
            "role": "FAST_SCOUT",
            "receipt_id": "rcpt_10",
            "revision": 10,
            "session_date": "2026-09-09",
            "semantic_state": "CONTROL_STABLE",
            "headline": "Rev 10 read",
            "bullets": [],
            "missing_evidence": [],
            "evidence_ids": ["e1"],
            "deserves_luna_review": False,
            "updated_at": now_iso,
            "status": "CURRENT",
            "telemetry": {
                "validation_status": "ACCEPTED",
                "input_receipt": {
                    "request_body": "{}",
                    "receipt_id": "rcpt_10",
                    "parent_receipt_id": "rcpt_10",
                    "payload": {
                        "decision_cutoff_ist": "13:35:00",
                        "evidence_frontier": ["e1"],
                        "frozen_at_utc": now_iso,
                        "revision": 10,
                        "session_date": "2026-09-09",
                    },
                    "session_id": "2026-09-09",
                    "revision": 10,
                    "frontier": ["e1"],
                    "cutoff": "13:35:00",
                    "observed_at": now_iso,
                    "model": GEMINI_SCOUT_MODEL_ID,
                    "output_hash": "dummy",
                },
                "validated_output": {
                    "schema_version": "1.3.0-fast-scout",
                    "role": "FAST_SCOUT",
                    "semantic_state": "CONTROL_STABLE",
                    "headline": "Rev 10 read",
                    "bullets": [],
                    "missing_evidence": [],
                    "evidence_ids": ["e1"],
                    "deserves_luna_review": False,
                },
            },
        },
        "sol_option_specialist": None,
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    # Mock validated_specialist_view so format is accepted
    import src.oracle_sol.shadow_specialists as specialists
    monkeypatch.setattr(specialists, "validated_specialist_view", lambda x: True)

    # Active Luna node is at revision 11 (newer than Gemini's 10)
    mock_active = Mock()
    mock_active.to_dict.return_value = {
        "thesis_id": "th_11",
        "session_id": "2026-09-09",
        "input_revision": 11,
        "created_at": now_iso,
        "state": "CALL_DEVELOPING",
        "entry_window": "MONITORING",
        "why_now": ["Spot rising"],
        "semantic_validation": {"status": "VALID"},
    }

    res = project_cognitive_decision(
        active=mock_active,
        previous=None,
        live_status={"session_id": "2026-09-09", "market_status": "LIVE"},
        snapshot={"market_session_date": "2026-09-09", "system_status": "LIVE"},
    )

    # Gemini from revision 10 MUST NOT be marked CURRENT beside Luna at revision 11
    assert res["gemini_scout"] is not None
    assert res["gemini_scout"]["status"] == "STALE"


def test_same_moment_specialist_truth_and_asymmetric_availability(tmp_path, monkeypatch):
    from src.oracle_sol.cognitive_projection import project_cognitive_decision
    monkeypatch.chdir(tmp_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    status_file = tmp_path / "data/sol_shadow/live_shadow_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Luna advances to N+1 (rev 11), both specialists at rev 10 -> both become STALE
    payload = {
        "updated_at_utc": now_iso,
        "latest_revision": 10,
        "latest_receipt_id": "rcpt_10",
        "session_date": "2026-09-09",
        "gemini_scout": {
            "schema_version": "1.3.0-fast-scout",
            "model_id": GEMINI_SCOUT_MODEL_ID,
            "role": "FAST_SCOUT",
            "receipt_id": "rcpt_10",
            "revision": 10,
            "session_date": "2026-09-09",
            "semantic_state": "FLOW_SHIFT",
            "headline": "Gemini rev 10",
            "bullets": [],
            "missing_evidence": [],
            "evidence_ids": ["e1"],
            "deserves_luna_review": False,
            "updated_at": now_iso,
            "status": "CURRENT",
            "telemetry": {"validation_status": "ACCEPTED"},
        },
        "sol_option_specialist": {
            "schema_version": "1.3.0-option-specialist",
            "model_id": "gpt-5.6-sol",
            "role": "OPTION_SPECIALIST",
            "receipt_id": "rcpt_10",
            "revision": 10,
            "session_date": "2026-09-09",
            "buying_state": "CALL_ATTRACTIVE",
            "headline": "Sol rev 10",
            "bullets": [],
            "missing_evidence": [],
            "evidence_ids": ["e1"],
            "updated_at": now_iso,
            "status": "CURRENT",
            "telemetry": {"validation_status": "ACCEPTED"},
        },
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    import src.oracle_sol.shadow_specialists as specialists
    from src.oracle_sol.evidence_gate import EvidenceGate
    monkeypatch.setattr(specialists, "validated_specialist_view", lambda x: True)
    monkeypatch.setattr(EvidenceGate, "revalidate_retained", lambda x: SimpleNamespace(is_valid=True, status="VALID", error_details=None))

    mock_active = Mock()
    mock_active.to_dict.return_value = {
        "thesis_id": "th_11",
        "session_id": "2026-09-09",
        "input_revision": 11,
        "created_at": now_iso,
        "state": "CALL_DEVELOPING",
        "entry_window": "MONITORING",
        "why_now": ["Spot rising [metric:spot_price metric:zero_gamma]"],
        "semantic_validation": {"status": "VALID"},
    }

    res = project_cognitive_decision(
        active=mock_active,
        previous=None,
        live_status={"session_id": "2026-09-09", "market_status": "LIVE"},
        snapshot={"market_session_date": "2026-09-09", "system_status": "LIVE"},
    )
    # Both specialists from rev 10 are STALE beside Luna at rev 11
    assert res["gemini_scout"]["status"] == "STALE"
    assert res["sol_option_specialist"]["status"] == "STALE"
    # Bracketed token was stripped from why_now
    assert res["primary_decision"]["why_now"] == ["Spot rising"]

    # 2. Asymmetric availability: Gemini rev 11 (CURRENT), Sol unavailable (None)
    payload_asym = {
        "updated_at_utc": now_iso,
        "latest_revision": 11,
        "latest_receipt_id": "rcpt_11",
        "session_date": "2026-09-09",
        "gemini_scout": {
            "schema_version": "1.3.0-fast-scout",
            "model_id": GEMINI_SCOUT_MODEL_ID,
            "role": "FAST_SCOUT",
            "receipt_id": "rcpt_11",
            "revision": 11,
            "session_date": "2026-09-09",
            "semantic_state": "FLOW_SHIFT",
            "headline": "Gemini rev 11 fresh read",
            "bullets": [],
            "missing_evidence": [],
            "evidence_ids": ["e1"],
            "deserves_luna_review": False,
            "updated_at": now_iso,
            "status": "CURRENT",
            "telemetry": {"validation_status": "ACCEPTED"},
        },
        "sol_option_specialist": None,
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(payload_asym, f)

    res_asym = project_cognitive_decision(
        active=mock_active,
        previous=None,
        live_status={"session_id": "2026-09-09", "market_status": "LIVE", "decision": {"model_tension": "ALIGNED: Solitary production cognitive analyst"}},
        snapshot={"market_session_date": "2026-09-09", "system_status": "LIVE"},
    )
    assert res_asym["gemini_scout"]["status"] == "CURRENT"
    assert res_asym["sol_option_specialist"] is None
    # model_tension does not falsely say ALIGNED: Solitary
    assert "ALIGNED: Solitary" not in (res_asym["primary_decision"]["model_tension"] or "")


def test_sol_pause_drops_queue_and_suppresses_dispatch(runtime, monkeypatch):
    import src.oracle_sol.shadow_runtime as shadow_runtime
    monkeypatch.setattr(shadow_runtime, "validated_specialist_view", lambda x: True)
    # Process packet 1 to establish baseline
    runtime.process_live_packet(packet(1))
    assert runtime._sol_in_flight

    # Pause Sol
    runtime.pause_sol(reason="INPUT_HARDENING")
    assert not runtime._sol_enabled
    assert runtime._pending_sol is None

    # Simulate in-flight call completing while paused
    receipt, original = runtime._executor.submit.call_args_list[1].args[1:]
    from src.oracle_sol.shadow_specialists import SolOptionSpecialistOutput
    from src.oracle_sol.shadow_orchestrator import SOL_CHALLENGER_MODEL_ID
    output = SolOptionSpecialistOutput(
        model_id=SOL_CHALLENGER_MODEL_ID,
        receipt_id=receipt.receipt_id,
        revision=1,
        buying_state="CALL_ATTRACTIVE",
        headline="Sol completed while paused",
    )
    runtime.sol_adapter.analyze.return_value = (output, {"status": "CURRENT"})
    runtime._run_sol_async(receipt, original)

    # Result is marked STALE and PAUSED, never CURRENT
    views = runtime.get_projected_views()
    sol_view = views["sol_option_specialist"]
    assert sol_view["status"] == "STALE"
    assert sol_view["paused"] is True
    assert sol_view["display_status"] == "PAUSED · INPUT HARDENING"
    assert sol_view.get("in_flight") is not True

    # Sending next packet with invoke_sol does NOT dispatch Sol, but dispatches Gemini
    runtime._gemini_in_flight = False
    res2 = runtime.process_live_packet(packet(2))
    assert res2["dispatched_sol"] is False
    assert res2["dispatched_gemini"] is True
    assert runtime._pending_sol is None

    # Resume Sol (requires SOL_DISPATCH_ENABLED = True)
    monkeypatch.setattr(shadow_runtime, "SOL_DISPATCH_ENABLED", True)
    runtime.resume_sol()
    assert runtime._sol_enabled
    res3 = runtime.process_live_packet(packet(3))
    assert res3["dispatched_sol"] is True


def test_gemini_pause_gate_and_historical_context_preservation(runtime, monkeypatch):
    import src.oracle_sol.shadow_runtime as shadow_runtime
    monkeypatch.setattr(shadow_runtime, "validated_specialist_view", lambda x: True)

    # Process first packet to dispatch Gemini
    res1 = runtime.process_live_packet(packet(1))
    assert res1["dispatched_gemini"] is True

    # Pause Gemini
    runtime.pause_gemini(reason="INPUT_ARCHITECTURE_HARDENING")
    assert not runtime._gemini_enabled
    assert runtime._pending_gemini is None

    # Simulate in-flight call completing while paused
    receipt, original = runtime._executor.submit.call_args_list[0].args[1:]
    output = GeminiScoutOutput(
        model_id=GEMINI_SCOUT_MODEL_ID,
        receipt_id=receipt.receipt_id,
        revision=1,
        headline="Gemini completed while paused",
    )
    runtime.gemini_adapter.analyze.return_value = (output, {"status": "CURRENT"})
    runtime._run_gemini_async(receipt, original)

    # Result is marked STALE and PAUSED, never CURRENT
    views = runtime.get_projected_views()
    gemini_view = views["gemini_scout"]
    assert gemini_view["status"] == "STALE"
    assert gemini_view["paused"] is True
    assert gemini_view["display_status"] == "PAUSED · INPUT/ARCHITECTURE HARDENING"
    assert gemini_view.get("in_flight") is not True

    # Sending next packet with invoke_gemini does NOT dispatch Gemini, but dispatches Sol
    runtime._sol_in_flight = False
    res2 = runtime.process_live_packet(packet(2))
    assert res2["dispatched_gemini"] is False
    assert res2["dispatched_sol"] is True
    assert runtime._pending_gemini is None

    # Resume Gemini (requires GEMINI_DISPATCH_ENABLED = True)
    monkeypatch.setattr(shadow_runtime, "GEMINI_DISPATCH_ENABLED", True)
    runtime.resume_gemini()
    assert runtime._gemini_enabled
    res3 = runtime.process_live_packet(packet(3))
    assert res3["dispatched_gemini"] is True


def test_sol_14_required_inputs_checklist_tracking(runtime):
    # Construct packet with partial option facts
    test_packet = BrainPacket(
        packet_id="packet-chk-1",
        session_id="2026-09-10",
        revision=100,
        compiled_at="2026-09-10T10:00:00Z",
        canonical_state={
            "spot_price": 23410.55,
            "futures_price": 23516.0,
            "basis": 105.45,
            "atm_strike": 23400.0,
            "ce_atm_security_id": 47293,
            "pe_atm_security_id": 47294,
            "ce_atm_premium": 146.9,
            "pe_atm_premium": 86.9,
            "atm_iv": 9.96,
            "straddle_change_15m": None,  # Missing
            "flow_net_delta": None,       # Missing
        },
        what_changed={},
        unseen_event_ids=["e1"],
        unseen_events_summary=[],
        previous_thesis=None,
        verified_external_events=[],
        external_quotes=[],
        valid_evidence_ids=["metric:spot_price"],
    )

    runtime.pause_sol(reason="INPUT_HARDENING")
    runtime.process_live_packet(test_packet)

    chk = runtime._sol_readiness_checklist
    assert chk is not None
    # 14 total items tracked
    assert chk["_summary"]["total_count"] == 14
    assert chk["_summary"]["status"] == "INPUT_HARDENING_REQUIRED"

    # Present items
    assert chk["option_contract_strike"]["ready"] is True
    assert chk["premium"]["ready"] is True
    assert chk["atm_iv"]["ready"] is True
    assert chk["underlying_futures_basis"]["ready"] is True

    # Incomplete/missing items
    assert chk["expiry"]["ready"] is False
    assert chk["time_to_expiry"]["ready"] is False
    assert chk["bid_ask"]["ready"] is False
    assert chk["straddle_change"]["ready"] is False
    assert chk["required_flow_evidence"]["ready"] is False
    assert chk["same_option_premium_change_history"]["ready"] is False
    assert chk["iv_baseline_reference"]["ready"] is False


