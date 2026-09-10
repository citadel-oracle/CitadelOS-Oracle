"""Tests for CITADEL Privacy Sanitizer Boundary."""

import json
from pathlib import Path
import pytest

from src.oracle_sol.privacy_sanitizer import (
    PrivacyViolationError,
    sanitize_event,
    sanitize_brain_packet,
    verify_sanitized_payload,
)
from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot, SystemStatus


@pytest.mark.parametrize("values", [
    {"unreviewed_signal": 42},
    {"diffs": {"ce_pricing": {"after": {"unreviewed_signal": 42}}}},
    {"structure": {"hidden_context": "sensitive"}},
])
def test_unknown_fields_fail_closed_without_echoing_content(values):
    with pytest.raises(PrivacyViolationError, match="Unreviewed") as error:
        sanitize_event({"supporting_values": values})
    assert "sensitive" not in str(error.value)


def test_quote_endpoints_preserve_identity_and_nulls():
    quotes = {"before": {"security_id": "A", "ltp": None},
              "after": {"security_id": "B", "ltp": 10, "best_ask_price": 11}}
    result = sanitize_event({"supporting_values": {"diffs": {"ce_pricing": quotes}}})
    assert result["supporting_values"]["diffs"]["ce_pricing"] == quotes


def test_sanitize_event_retains_only_public_observables():
    raw_event = {
        "event_id": "evt_test_12345",
        "event_type": "SPOT_MOVE",
        "instrument": "NIFTY_INDEX",
        "strike": 23650.0,
        "expiry": "2026-09-08",
        "security_id": "42625",
        "timestamp_ist": "13:51:35",
        "timestamp_utc": "2026-09-08T08:21:35.672000+00:00",
        "summary": "Internal proprietary summary string",
        "provenance_hash": "a1b2c3d4e5f67890",
        "before_state": "COGNITIVE_WAIT",
        "after_state": "VOB_ACTIVE",
        "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
        "canonical_snapshot_id": "can_snap_9999",
        "supporting_values": {
            "before_spot": 23637.7,
            "after_spot": 23625.85,
            "spot_delta": -11.85,
            "session_vwap": 23650.0,
            "ose_ssi_score": 0.85,
            "vob_state": "VOB_ACTIVE",
            "vob_touch_count": 3,
        }
    }

    sanitized = sanitize_event(raw_event)

    # Retained fields
    assert sanitized["event_id"] == "evt_test_12345"
    assert sanitized["event_type"] == "SPOT_MOVE"
    assert sanitized["instrument"] == "NIFTY_INDEX"
    assert sanitized["strike"] == 23650.0
    assert sanitized["security_id"] == "42625"
    assert sanitized["timestamp_ist"] == "13:51:35"

    # Retained supporting values
    sup = sanitized["supporting_values"]
    assert sup["before_spot"] == 23637.7
    assert sup["after_spot"] == 23625.85
    assert sup["spot_delta"] == -11.85
    assert sup["session_vwap"] == 23650.0

    # Stripped internal engine fields
    assert "summary" not in sanitized
    assert "provenance_hash" not in sanitized
    assert "before_state" not in sanitized
    assert "after_state" not in sanitized
    assert "chronology_mode" not in sanitized
    assert "canonical_snapshot_id" not in sanitized
    assert "ose_ssi_score" not in sup
    assert "vob_state" not in sup
    assert "vob_touch_count" not in sup


@pytest.mark.parametrize("banned_phrase", [
    "dhan",
    "client_id",
    "access_token",
    "broker_secret",
    "api_key",
    "keychain",
    "ayush",
    "user_id",
    "position",
    "pnl",
    "margin",
    "order_placement",
    "place_order",
    "buy_order",
    "sell_order",
    "modify_order",
    "cancel_order",
    "broker_submission",
    "weight",
    "formula",
    "proprietary",
    "/Users/ayushmudgal/Developer",
    "/home/user/citadel",
    "vob_state",
    "vob_touch_count",
    "vob_sweep",
])
def test_verify_sanitized_payload_fails_closed_on_prohibited_terms(banned_phrase):
    payload = json.dumps({"market_data": f"Some text with {banned_phrase} embedded"})
    valid, reason = verify_sanitized_payload(payload)
    assert valid is False
    assert reason is not None
    assert banned_phrase.lower() in reason.lower() or "prohibited term detected" in reason.lower()


def test_sanitize_brain_packet_end_to_end_clean():
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
    packet = compiler.compile_packet("2026-09-08", 1, snapshot, None, unseen, [], [])

    sanitized = sanitize_brain_packet(packet, unseen_events=unseen, decision_cutoff_ist="13:51:35")
    assert sanitized["session_date"] == "2026-09-08"
    assert sanitized["decision_cutoff_ist"] == "13:51:35"
    assert len(sanitized["timeline"]) == 1
    ev0 = sanitized["timeline"][0]["events"][0]
    assert ev0["event_id"] == "evt_spot_1"
    assert ev0["supporting_values"]["after_spot"] == 23625.85
    assert "summary" not in ev0
    assert "chronology_mode" not in ev0

    # Verify no privacy violation raised
    serialized = json.dumps(sanitized)
    ok, err = verify_sanitized_payload(serialized)
    assert ok is True
    assert err is None
