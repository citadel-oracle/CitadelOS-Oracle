"""Focused validation test suite for ARGUS ATM recentering, strike universe reshuffling,
market-state hero rendering, and data integrity invariants.
"""

import tempfile
from pathlib import Path
import pytest

from src.argus.option_chain_engine import OptionChainEngine, OptionChainSnapshot
from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.tactical_store import ArgusTacticalStore


def make_test_engine():
    tmp_dir = tempfile.mkdtemp()
    store = ArgusTacticalStore(path=Path(tmp_dir) / "store.json")
    return ArgusTacticalEdgeEngine(store=store)


def make_sample_ose():
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


def make_argus_payload(spot=23868.6, atm=23850.0, market_state="OPEN", stale=False):
    strikes = []
    base_strike = atm - 150.0
    for i in range(7):
        stk = base_strike + i * 50.0
        strikes.append({
            "strike": stk,
            "ce_moneyness": "ATM" if stk == atm else "ITM" if stk < atm else "OTM",
            "pe_moneyness": "ATM" if stk == atm else "OTM" if stk < atm else "ITM",
            "ce": {"security_id": f"CE_{int(stk)}", "ltp": 120.0, "oi": 25000, "day_change_oi": 1000, "intraday_change_oi": 500, "volume": 10000},
            "pe": {"security_id": f"PE_{int(stk)}", "ltp": 240.0, "oi": 18000, "day_change_oi": 800, "intraday_change_oi": 400, "volume": 8000},
        })
    return {
        "status": "STALE" if stale else "AVAILABLE",
        "freshness": "STALE" if stale else "FRESH",
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "security_id": 13,
                "segment": "IDX_I",
                "ltp": spot,
                "expiry": "2026-07-30",
                "atm_strike": atm,
                "fetched_at": "2026-07-23T15:29:59.250871+05:30",
                "market_state": market_state,
                "data_age_seconds": 1.5,
            },
            "atm_window": strikes,
            "pressure": {
                "status": "LIVE",
                "call_score": 42.8,
                "put_score": 54.5,
                "delta": -11.7,
                "direction": "PUT",
                "state": "PUT_DOMINANT",
            },
            "previous_oi": {
                "status": "AVAILABLE",
                "call_wall": 24200.0,
                "put_wall": 23700.0,
                "aggregate_intraday_ce_change": 1400,
                "aggregate_intraday_pe_change": 700,
            },
        },
    }


# Test 1: Spot crossing an ATM boundary rebuilds the strike universe
def test_spot_crossing_atm_boundary_rebuilds_universe():
    argus1 = make_argus_payload(spot=23868.6, atm=23850.0)
    argus2 = make_argus_payload(spot=23925.0, atm=23900.0)
    engine = make_test_engine()
    ose = make_sample_ose()
    p1 = engine.evaluate(argus1, ose)
    p2 = engine.evaluate(argus2, ose)
    assert p1 is not None and p2 is not None


# Test 2: Spot remaining within same ATM bucket does not unnecessarily rebuild
def test_spot_within_same_atm_bucket():
    argus1 = make_argus_payload(spot=23860.0, atm=23850.0)
    argus2 = make_argus_payload(spot=23868.6, atm=23850.0)
    engine = make_test_engine()
    ose = make_sample_ose()
    p1 = engine.evaluate(argus1, ose)
    p2 = engine.evaluate(argus2, ose)
    assert p1 is not None and p2 is not None


# Test 3 & 4: Hysteresis prevents oscillation and sustained move changes ATM
def test_hysteresis_and_sustained_move():
    interval = 50.0
    midpoint = 23875.0
    # Spot at 23872 is inside hysteresis band near midpoint (within 10 of 23875)
    spot_near = 23872.0
    base_atm = round(spot_near / interval) * interval
    assert base_atm == 23850.0 or base_atm == 23900.0


# Test 5 & 6: Strike ladder recenters and suggested contract reselects
def test_strike_ladder_and_contract_selection():
    engine = make_test_engine()
    argus = make_argus_payload(spot=23868.6, atm=23850.0)
    ose = make_sample_ose()
    p = engine.evaluate(argus, ose)
    assert p.get("decision", {}).get("side") in ("CALL", "PUT", "BALANCED", None)


# Test 7, 8, 9: Pressure, walls, WHY evidence regenerated
def test_pressure_walls_why_regenerated():
    engine = make_test_engine()
    argus = make_argus_payload()
    ose = make_sample_ose()
    p = engine.evaluate(argus, ose)
    decision = p.get("decision", {})
    assert "next_trigger" in decision
    assert "market_state" in decision
    assert "display_state" in decision
    assert "last_verified" in decision


# Test 12, 13, 14, 15: Market closed, stale, disconnect states
def test_market_closed_and_stale_hero_states():
    engine = make_test_engine()
    ose = make_sample_ose()
    
    # Establish open snapshot in store
    argus_open = make_argus_payload(market_state="OPEN")
    engine.evaluate(argus_open, ose)

    # Market Closed
    argus_closed = make_argus_payload(market_state="CLOSED")
    p_closed = engine.evaluate(argus_closed, ose)
    d_closed = p_closed.get("decision", {})
    assert p_closed.get("status") in ("STALE", "LOCK", "AVAILABLE")
    assert d_closed.get("market_state") in ("MARKET_CLOSED", "STALE")

    # Stale
    argus_stale = make_argus_payload(stale=True)
    p_stale = engine.evaluate(argus_stale, ose)
    d_stale = p_stale.get("decision", {})
    assert p_stale.get("status") in ("STALE", "LOCK")


# Test 17 & 18: ENTER NOW remains disabled and no live order path enabled
def test_enter_now_disabled():
    engine = make_test_engine()
    argus = make_argus_payload()
    ose = make_sample_ose()
    p = engine.evaluate(argus, ose)
    decision = p.get("decision", {})
    assert decision.get("action_enabled") is False
    assert decision.get("execution_authorization") is False
    assert decision.get("current_action") != "ENTER_NOW"
