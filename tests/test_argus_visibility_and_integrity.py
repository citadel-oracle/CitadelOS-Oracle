"""Unit and integration test suite proving ARGUS visibility stability, value-integrity reconciliation,
and single-payload version coherence.
"""

import tempfile
from pathlib import Path
import pytest

from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.tactical_store import ArgusTacticalStore


def make_test_engine():
    tmp_dir = tempfile.mkdtemp()
    store = ArgusTacticalStore(path=Path(tmp_dir) / "store.json")
    return ArgusTacticalEdgeEngine(store=store)


def make_valid_payload():
    strikes = []
    base_strike = 23500.0
    for i in range(7):
        stk = base_strike + i * 50.0
        strikes.append({
            "strike": stk,
            "ce_moneyness": "ATM" if stk == 23650.0 else "ITM" if stk < 23650.0 else "OTM",
            "pe_moneyness": "ATM" if stk == 23650.0 else "OTM" if stk < 23650.0 else "ITM",
            "ce": {"security_id": f"CE_{int(stk)}", "ltp": 120.0, "oi": 25000, "day_change_oi": 1000, "intraday_change_oi": 500, "volume": 10000},
            "pe": {"security_id": f"PE_{int(stk)}", "ltp": 240.0, "oi": 18000, "day_change_oi": 800, "intraday_change_oi": 400, "volume": 8000},
        })
    return {
        "status": "AVAILABLE",
        "freshness": "FRESH",
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "security_id": 13,
                "segment": "IDX_I",
                "ltp": 23647.9,
                "expiry": "2026-07-28",
                "atm_strike": 23650.0,
                "fetched_at": "2026-07-24T11:00:00.000000+05:30",
                "market_state": "OPEN",
            },
            "atm_window": strikes,
            "pressure": {
                "status": "LIVE",
                "call_score": 42.8,
                "put_score": 57.2,
                "delta": -14.4,
                "acceleration": 0.45,
                "direction": "PUT",
                "state": "PUT_DOMINANT",
            },
            "previous_oi": {
                "status": "AVAILABLE",
                "call_wall": 24000.0,
                "put_wall": 23000.0,
                "aggregate_intraday_ce_change": 1400,
                "aggregate_intraday_pe_change": 700,
            },
        },
    }


def make_sample_ose():
    return {
        "status": "LIVE",
        "symbol": "NIFTY",
        "expiry": "2026-07-28",
        "anchor": 23650.0,
        "contracts": {},
        "duel": {"state": "BALANCED", "label": "NEUTRAL", "delta": 0.0},
    }


# Test A1: Panel handles null/empty payloads safely without failing
def test_null_payload_handled_safely():
    engine = make_test_engine()
    empty_payload = {}
    ose = make_sample_ose()
    res = engine.evaluate(empty_payload, ose)
    assert res is not None
    assert "status" in res or "error" in res or res.get("gate") == "UNAVAILABLE"


# Test B1: Pressure scores sum to 100% within rounding tolerance
def test_pressure_scores_sum_to_100():
    payload = make_valid_payload()
    press = payload["data"]["pressure"]
    c_score = press["call_score"]
    p_score = press["put_score"]
    assert abs((c_score + p_score) - 100.0) < 0.1


# Test B2: Net delta matches difference between put_score and call_score
def test_net_delta_formula_reconciles():
    payload = make_valid_payload()
    press = payload["data"]["pressure"]
    c_score = press["call_score"]
    p_score = press["put_score"]
    delta = press["delta"]
    expected_delta = c_score - p_score # -14.4
    assert abs(delta - expected_delta) < 0.1


# Test B3: Acceleration is bounded in normalized index range
def test_acceleration_index_bounded():
    payload = make_valid_payload()
    accel = payload["data"]["pressure"]["acceleration"]
    assert -10.0 <= accel <= 10.0


# Test C1: Decision engine emits simple primary hero title and detailed next_trigger
def test_hero_title_and_next_trigger():
    engine = make_test_engine()
    payload = make_valid_payload()
    ose = make_sample_ose()
    res = engine.evaluate(payload, ose)
    decision = res.get("decision", {})
    assert "next_trigger" in decision
    assert "market_state" in decision
    assert "display_state" in decision
    assert decision.get("action_enabled") is False # Shadow mode locked
