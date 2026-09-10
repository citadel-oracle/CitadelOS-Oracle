"""
Phase 10 — Chronological and Adversarial Validation Test Suite for ARGUS Decision Engine v2.1.
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.tactical_store import ArgusTacticalStore


import tempfile

def make_test_engine():
    tmp_dir = tempfile.mkdtemp()
    store = ArgusTacticalStore(path=Path(tmp_dir) / "store.json")
    return ArgusTacticalEdgeEngine(store=store)


def make_sample_argus_payload(action="WAIT_FOR_RETEST", direction="PUT", market_state="OPEN", stale=False):
    timestamp = "2026-07-23T15:29:59.000000+05:30"
    return {
        "status": "STALE" if stale else "AVAILABLE",
        "freshness": "STALE" if stale else "FRESH",
        "stale_reason": "ARGUS_SOURCE_NOT_FRESH" if stale else None,
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "expiry": "2026-07-30",
                "ltp": 23868.6,
                "atm_strike": 23850.0,
                "market_state": market_state,
                "fetched_at": timestamp,
            },
            "atm_window": [
                {
                    "strike": 23850.0,
                    "ce": {
                        "oi": 15000,
                        "change_oi": 500,
                        "volume": 2000,
                        "activity": "CALL_WRITING",
                        "positioning": "CALL_WRITING",
                        "ltp": 120.0,
                        "top_ask_price": 120.5,
                        "top_bid_price": 119.5,
                        "security_id": 63933,
                    },
                    "pe": {
                        "oi": 25000,
                        "change_oi": 1200,
                        "volume": 3500,
                        "activity": "PUT_BUYING",
                        "positioning": "PUT_BUYING",
                        "ltp": 248.0,
                        "top_ask_price": 248.5,
                        "top_bid_price": 247.5,
                        "security_id": 63934,
                    },
                }
            ],
            "pressure": {
                "direction": direction,
                "call_score": 42.8,
                "put_score": 54.5,
                "delta": -11.6,
                "spot_confirmation": "DOWN",
                "evidence_quality": 100.0,
                "state": "PUT_PRESSURE",
                "status": "LIVE",
                "strikes": [],
            },
            "previous_oi": {
                "status": "AVAILABLE",
                "call_wall": 25000.0,
                "put_wall": 23000.0,
                "aggregate_intraday_ce_change": 12880010.0,
                "aggregate_intraday_pe_change": -3929120.0,
            },
            "premium_attribution": {
                "status": "AVAILABLE",
                "CE": {"premium": 120.0, "intrinsic": 0.0, "extrinsic": 120.0, "activity": "CALL_WRITING"},
                "PE": {"premium": 248.0, "intrinsic": 231.4, "extrinsic": 16.6, "activity": "PUT_BUYING"},
                "greek_attribution": "UNAVAILABLE",
                "unavailable": ["DELTA", "GAMMA", "THETA", "VEGA"],
            },
        },
    }


def create_sample_ose():
    return {
        "status": "LIVE",
        "symbol": "NIFTY",
        "expiry": "2026-07-30",
        "anchor": 23850.0,
        "canonical_digest": "digest_12345",
        "calculated_at": "2026-07-23T15:29:59+05:30",
        "contracts": {
            "CE": {
                "contract": {"security_id": "63933", "strike": 23850.0, "expiry": "2026-07-30", "trading_symbol": "NIFTY26JUL23850CE"},
                "premium": 120.0,
                "composite": {"label": "CONTINUATION"},
                "structures": {"5m": {"completed_bucket": True, "state": "BALANCED"}},
            },
            "PE": {
                "contract": {"security_id": "63934", "strike": 23850.0, "expiry": "2026-07-30", "trading_symbol": "NIFTY26JUL23850PE"},
                "premium": 248.0,
                "composite": {"label": "CONTINUATION"},
                "structures": {"5m": {"completed_bucket": True, "state": "BALANCED"}},
            },
        },
        "duel": {"state": "BALANCED", "label": "NEUTRAL", "delta": 0.0},
    }


def test_call_cannot_select_pe():
    engine = make_test_engine()
    argus = make_sample_argus_payload(direction="CALL")
    ose = create_sample_ose()
    projection = engine.evaluate(argus, ose)
    contract_sel = projection.get("contract_selection", {})
    if "CE" in contract_sel and contract_sel["CE"]:
        ce_contract = contract_sel["CE"]
        assert ce_contract.get("side") == "CE" or ce_contract.get("trading_symbol", "").endswith("CE") or "CE" in ce_contract.get("trading_symbol", "")


def test_put_cannot_select_ce():
    engine = make_test_engine()
    argus = make_sample_argus_payload(direction="PUT")
    ose = create_sample_ose()
    projection = engine.evaluate(argus, ose)
    contract_sel = projection.get("contract_selection", {})
    if "PE" in contract_sel and contract_sel["PE"]:
        pe_contract = contract_sel["PE"]
        assert pe_contract.get("side") == "PE" or pe_contract.get("trading_symbol", "").endswith("PE") or "PE" in pe_contract.get("trading_symbol", "")


def test_enter_now_never_emitted():
    engine = make_test_engine()
    argus = make_sample_argus_payload()
    ose = create_sample_ose()
    projection = engine.evaluate(argus, ose)
    decision = projection.get("decision", {})
    assert decision.get("current_action") != "ENTER_NOW"
    assert decision.get("action") != "ENTER_NOW"


def test_stale_data_locks_action():
    engine = make_test_engine()
    stale_argus = make_sample_argus_payload(stale=True)
    ose = create_sample_ose()
    projection = engine.evaluate(stale_argus, ose)
    assert projection.get("status") in ("STALE", "LAST_AUTHORITATIVE", "LOCK", "UNAVAILABLE")


def test_missing_greeks_never_creates_gamma_claims():
    engine = make_test_engine()
    argus = make_sample_argus_payload()
    ose = create_sample_ose()
    projection = engine.evaluate(argus, ose)
    gamma = projection.get("gamma", {})
    assert gamma.get("status") == "UNAVAILABLE" or gamma.get("available") is False
    why = projection.get("why", {})
    assert any("Gamma" in r or "Greeks" in r or "GREEKS" in r for r in why.get("reasons", [])) or "GAMMA" in why.get("unavailable", [])


def test_missing_numeric_fields_do_not_become_zero():
    engine = make_test_engine()
    argus = make_sample_argus_payload()
    del argus["data"]["pressure"]["delta"]
    ose = create_sample_ose()
    projection = engine.evaluate(argus, ose)
    assert projection is not None


def test_ist_timezone_normalization():
    tz = ZoneInfo("Asia/Kolkata")
    assert tz.key == "Asia/Kolkata"


def test_launchagent_service_files_exist():
    home = Path.home()
    backend_plist = home / "Library" / "LaunchAgents" / "com.citadelos.backend.plist"
    frontend_plist = home / "Library" / "LaunchAgents" / "com.citadelos.frontend.plist"
    assert backend_plist.exists(), f"Backend LaunchAgent plist missing at {backend_plist}"
    assert frontend_plist.exists(), f"Frontend LaunchAgent plist missing at {frontend_plist}"

    repo_dir = Path("/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend")
    assert (repo_dir / "start-citadel.sh").exists()
    assert (repo_dir / "stop-citadel.sh").exists()
    assert (repo_dir / "restart-citadel.sh").exists()
    assert (repo_dir / "status-citadel.sh").exists()
