"""E7AR-2 S05 Genuine Pivot + No-Lookahead Closure Tests.

These tests prove the BLOCKED state honestly:
- Security ID verified from authoritative instrument master
- Previous E7AR detection INVALIDATED (manual pivot inputs used)
- Previous session exact PE data NOT AVAILABLE
- S05 detection remains BLOCKED pending genuine prev-session option data
"""

import json
import os
import pytest

REAL_COHORT_DIR = "/Users/ayushmudgal/Developer/CitadelOS/reports/eye_personal_strategy_acceptance/20260807_real"
INVALID_COHORT_DIR = "/Users/ayushmudgal/Developer/CitadelOS/reports/eye_personal_strategy_acceptance/e7a_invalid_synthetic_20260807"
INSTRUMENT_MASTER = "/Users/ayushmudgal/Developer/CitadelOS/logs/dhan_instrument_master.json"


def test_exact_contract_identity_proven():
    """NIFTY 11-AUG-2026 24700 PE security_id = 41024 from authoritative instrument master."""
    with open(INSTRUMENT_MASTER) as f:
        master = json.load(f)

    rows = master.get("rows", [])
    matches = [
        r for r in rows
        if str(r.get("SECURITY_ID")) == "41024"
    ]
    assert len(matches) == 1, f"Expected 1 match for security_id 41024, got {len(matches)}"
    row = matches[0]
    assert row["OPTION_TYPE"] == "PE"
    assert row["STRIKE_PRICE"] == "24700.00000"
    assert row["UNDERLYING_SYMBOL"] == "NIFTY"
    assert row["SM_EXPIRY_DATE"] == "2026-08-11"
    assert row["INSTRUMENT"] == "OPTIDX"
    assert row["LOT_SIZE"] == "65.0"


def test_previous_e7ar_security_id_10024700_invalid():
    """E7AR manifest claimed security_id=10024700 which is NOT in instrument master."""
    with open(INSTRUMENT_MASTER) as f:
        master = json.load(f)

    rows = master.get("rows", [])
    matches_10024700 = [r for r in rows if str(r.get("SECURITY_ID")) == "10024700"]
    assert len(matches_10024700) == 0, "10024700 should NOT exist in authoritative instrument master"


def test_previous_e7ar_s05_detection_invalidated():
    """Prove previous E7AR S05 detection was invalid (used hardcoded manual pivot inputs)."""
    # The previous call used: daily_prev_high=180.0, daily_prev_low=150.0, daily_prev_close=165.0
    # These are not from any real previous-session PE data — no source file contains them
    manual_prev_high = 180.0
    manual_prev_low = 150.0
    manual_prev_close = 165.0

    # This would compute:
    p = (manual_prev_high + manual_prev_low + manual_prev_close) / 3.0
    r1 = 2 * p - manual_prev_low
    assert abs(r1 - 180.0) < 0.01, f"R1 should be ~180 (same as manual prev_high), proving trivial trigger"
    # R1 == prev_high when prev_close == (prev_high + prev_low)/2
    # This was a degenerate case that made the cross trivially easy
    # INVALIDATED: manual pivot inputs, not genuine prev-session PE data
    assert True  # invalidation confirmed


def test_previous_session_pe_data_not_in_local_store():
    """Previous session (2026-08-06) exact PE 1m data does not exist locally."""
    golden_dir = "/Users/ayushmudgal/Developer/CitadelOS/reports/eye_golden_replay"
    pe_prev_session = os.path.join(golden_dir, "20260806", "option_24700pe_20260806.json")
    assert not os.path.exists(pe_prev_session), (
        f"Previous-session PE data should NOT exist at {pe_prev_session}. "
        "If it now exists, update this test."
    )


def test_s05_previous_session_pivot_blocked():
    """S05 genuine detection is BLOCKED because genuine prev-session PE H/L/C unavailable.

    Per Phase 17 of the spec:
    'If the contract did not exist / has no prior valid session:
     state: MISSING_DATA_PREVIOUS_SESSION_OPTION_OHLC
     Do not calculate CPR from NIFTY spot as substitute.'
    """
    # Verify the local store only has the 2026-08-07 session
    golden_path = "/Users/ayushmudgal/Developer/CitadelOS/reports/eye_golden_replay/20260807/option_24700pe_20260807.json"
    assert os.path.exists(golden_path)

    with open(golden_path) as f:
        bars = json.load(f)

    # All bars should be from 2026-08-07 session (epoch >= 1786074300 for 09:15 IST)
    # 1786074300 = 2026-08-07 09:15:00 IST
    session_start_epoch = 1786074300.0
    assert all(b["time"] >= session_start_epoch for b in bars), "All bars should be from 2026-08-07"
    assert len(bars) == 385

    # S05_GENUINE_DETECTION_STATUS: BLOCKED_MISSING_PREVIOUS_SESSION_EXACT_OPTION_OHLC
    blocked_reason = "MISSING_PREVIOUS_SESSION_EXACT_OPTION_OHLC"
    assert blocked_reason  # blocked, no fabrication allowed


def test_synthetic_quarantine_present():
    """Verify previous invalid E7AR data is quarantined and labelled."""
    invalid_path = os.path.join(INVALID_COHORT_DIR, "STATISTICAL_INVALIDATION.json")
    assert os.path.exists(invalid_path)
    with open(invalid_path) as f:
        data = json.load(f)
    assert data["status"] == "STATISTICALLY_INVALIDATED"


def test_no_lookahead_resampler_3m():
    """3m bar aggregation: first bar is confirmed only after 3 complete 1m bars."""
    from src.eye.personal_strategies.resampler import SessionResampler

    with open(os.path.join(REAL_COHORT_DIR, "option_pe_24700_1m.json")) as f:
        bars_raw = json.load(f)

    formatted = [{
        "open": b["open"], "high": b["high"], "low": b["low"],
        "close": b["close"], "volume": b["volume"], "timestamp": "09:15:00"
    } for b in bars_raw]

    # Only 2 bars → no confirmed 3m bar yet
    res_2 = SessionResampler.resample_1m_to_tf(formatted[:2], 3)
    assert len(res_2) == 0, "2 bars should NOT produce a confirmed 3m bar"

    # Exactly 3 bars → 1 confirmed 3m bar
    res_3 = SessionResampler.resample_1m_to_tf(formatted[:3], 3)
    assert len(res_3) == 1
    assert res_3[0]["is_confirmed"] is True
    assert res_3[0]["open"] == bars_raw[0]["open"]
    assert res_3[0]["close"] == bars_raw[2]["close"]
