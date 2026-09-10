"""Tests for CITADEL Luna Production Cognitive Adapter."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot, SystemStatus
from src.oracle_sol.experiential_adapter import ExperientialAdapter
from src.oracle_sol.luna_cognitive_adapter import LunaCognitiveAdapter, PRODUCTION_MODEL_ID


@pytest.fixture(autouse=True)
def isolated_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr("src.oracle_sol.luna_cognitive_adapter.RECEIPT_DIRECTORY", tmp_path / "inputs")


@pytest.fixture
def test_packet():
    compiler = BrainPacketCompiler()
    fixture_path = Path("tests/oracle_sol/fixtures/bridge_recorded_snapshot_20260904.json")
    snap_data = json.loads(fixture_path.read_text())
    snap_data["market_session_date"] = "2026-09-08"
    snap_data["timestamp_ist"] = "13:51:35"
    snap_data["system_status"] = SystemStatus.HEALTHY
    snapshot = SolEvidenceSnapshot(**snap_data)
    unseen = [
        MarketEvent(
            event_id="evt_spot_1",
            session_date="2026-09-08",
            timestamp_utc="2026-09-08T08:21:35Z",
            timestamp_ist="13:51:35",
            event_type="SPOT_MOVE",
            instrument="NIFTY_INDEX",
            security_id=None,
            strike=None,
            expiry=None,
            summary="Spot dropped 11 pts",
            before_state={"state": "WAIT"},
            after_state={"state": "WAIT"},
            supporting_values={"before_spot": 23637.7, "after_spot": 23625.85, "spot_delta": -11.85},
            provenance_hash="prov_12345",
        )
    ]
    return compiler.compile_packet("2026-09-08", 1, snapshot, None, unseen, [], [])


def test_luna_adapter_configured_model_identity():
    adapter = LunaCognitiveAdapter()
    assert adapter.configured_model == "gpt-5.6-luna"
    assert adapter.backend.configured_model == "gpt-5.6-luna"
    assert adapter.backend.enforce_zero_cost is True
    assert adapter.backend.reject_substituted_model is True


def test_receipt_persisted_before_transport_and_failure_blocks_call(test_packet, tmp_path):
    adapter = LunaCognitiveAdapter(backend_adapter=ExperientialAdapter(
        model_name=PRODUCTION_MODEL_ID, api_key="xpl_mock_test_key_valid_fingerprint_12345"))
    response = MagicMock()
    response.__enter__.return_value.status = 200
    response.__enter__.return_value.headers = {}
    response.__enter__.return_value.read.return_value = json.dumps({
        "model": PRODUCTION_MODEL_ID, "cost_micro_usd": 0,
        "choices": [{"message": {"content": '{"state":"WAIT"}'}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 10},
    }).encode()

    def dispatch(request, **kwargs):
        files = list((tmp_path / "inputs").glob("*.json"))
        assert len(files) == 1
        assert json.loads(files[0].read_text())["request_body"].encode() == request.data
        return response

    with patch("urllib.request.urlopen", side_effect=dispatch):
        output, telemetry = adapter.analyze(test_packet)
    assert output == {"state": "WAIT"}
    assert telemetry["input_receipt"]["output_hash"]
    with patch("src.oracle_sol.luna_cognitive_adapter.persist_receipt", side_effect=OSError("disk unavailable")), patch("urllib.request.urlopen") as transport:
        output, telemetry = adapter.analyze(test_packet)
        assert output is None
        assert telemetry["error_class"] == "INPUT_RECEIPT_PERSISTENCE_FAILED"
        transport.assert_not_called()


def test_luna_adapter_rejects_model_substitution(test_packet):
    backend = ExperientialAdapter(
        model_name=PRODUCTION_MODEL_ID,
        api_key="xpl_mock_test_key_valid_fingerprint_12345",
        reject_substituted_model=True,
    )
    adapter = LunaCognitiveAdapter(backend_adapter=backend)

    mock_resp = {
        "id": "xpl-chatcmpl-test",
        "model": "gpt-6-astra",  # Substituted model!
        "choices": [{"message": {"role": "assistant", "content": '{"state": "WAIT"}'}}],
        "usage": {"total_tokens": 50},
        "cost_micro_usd": 0,
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value.status = 200
    mock_urlopen.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    mock_urlopen.__enter__.return_value.headers = {}

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        output, telemetry = adapter.analyze(test_packet)
        assert output is None
        assert telemetry["error_class"] == "MODEL_SUBSTITUTION_REJECTED"
        assert telemetry["model_substitution_detected"] is True
        assert telemetry["requested_model"] == "gpt-5.6-luna"
        assert telemetry["response_model"] == "gpt-6-astra"


def test_luna_adapter_rejects_monetary_spend(test_packet):
    backend = ExperientialAdapter(
        model_name=PRODUCTION_MODEL_ID,
        api_key="xpl_mock_test_key_valid_fingerprint_12345",
        enforce_zero_cost=True,
    )
    adapter = LunaCognitiveAdapter(backend_adapter=backend)

    mock_resp = {
        "id": "xpl-chatcmpl-test",
        "model": "gpt-5.6-luna",
        "choices": [{"message": {"role": "assistant", "content": '{"state": "WAIT"}'}}],
        "usage": {"total_tokens": 50},
        "cost_micro_usd": 1500,  # $0.001500 monetary spend!
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value.status = 200
    mock_urlopen.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    mock_urlopen.__enter__.return_value.headers = {}

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        output, telemetry = adapter.analyze(test_packet)
        assert output is None
        assert telemetry["error_class"] == "COMMERCIAL_STATE_VIOLATION"


def test_luna_adapter_privacy_violation_blocks_network_dispatch(test_packet):
    backend = ExperientialAdapter(
        model_name=PRODUCTION_MODEL_ID,
        api_key="xpl_mock_test_key_valid_fingerprint_12345",
    )
    adapter = LunaCognitiveAdapter(backend_adapter=backend)

    # Inject prohibited token into packet
    test_packet.canonical_state["dhan_client_id"] = "1100223344"

    with patch("urllib.request.urlopen") as mock_urlopen:
        # Pass an unseen event that has prohibited term in supporting_values
        bad_event = {
            "event_id": "evt_bad_1",
            "event_type": "ORDER_ATTEMPT",
            "supporting_values": {"broker_secret": "secret_abc123"},
        }
        output, telemetry = adapter.analyze(test_packet, unseen_events=[bad_event])
        assert output is None
        assert telemetry["error_class"] == "PRIVACY_VIOLATION_BLOCKED"
        # Verify network dispatch was NEVER called!
        mock_urlopen.assert_not_called()


def test_luna_adapter_successful_clean_cycle(test_packet):
    backend = ExperientialAdapter(
        model_name=PRODUCTION_MODEL_ID,
        api_key="xpl_mock_test_key_valid_fingerprint_12345",
    )
    adapter = LunaCognitiveAdapter(backend_adapter=backend)

    expected_output = {
        "state": "WAIT",
        "thesis_evolution": "REVERSAL_WATCH",
        "opportunity_maturity": "UNKNOWN",
        "conclusions": [
            {
                "purpose": "why_now",
                "claim": "Consolidation observed after session low.",
                "evidence_ids": ["evt_spot_1"],
            }
        ],
        "hypotheses": {
            "CALL": {"plausibility": "PLAUSIBLE", "discrimination": "Rebound seen.", "evidence_ids": ["evt_spot_1"]},
            "PUT": {"plausibility": "PLAUSIBLE", "discrimination": "Trend intact.", "evidence_ids": ["evt_spot_1"]},
            "NOISE": {"plausibility": "PLAUSIBLE", "discrimination": "Range chop.", "evidence_ids": ["evt_spot_1"]},
            "REVERSAL": {"plausibility": "UNRESOLVED", "discrimination": "No follow-through.", "evidence_ids": ["evt_spot_1"]},
        },
        "promotion_reason": "WAIT warranted while reversal watch develops.",
    }

    mock_resp = {
        "id": "xpl-chatcmpl-test",
        "model": "gpt-5.6-luna",
        "choices": [{"message": {"role": "assistant", "content": json.dumps(expected_output)}}],
        "usage": {"total_tokens": 1200, "prompt_tokens": 800, "completion_tokens": 400},
        "cost_micro_usd": 0,
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value.status = 200
    mock_urlopen.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    mock_urlopen.__enter__.return_value.headers = {}

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        output, telemetry = adapter.analyze(test_packet)
        assert output is not None
        assert output["state"] == "WAIT"
        assert output["thesis_evolution"] == "REVERSAL_WATCH"
        assert telemetry["status"] == "CURRENT"
        assert telemetry["cost_micro_usd"] == 0
        assert telemetry["requested_model"] == "gpt-5.6-luna"
        assert telemetry["response_model"] == "gpt-5.6-luna"
