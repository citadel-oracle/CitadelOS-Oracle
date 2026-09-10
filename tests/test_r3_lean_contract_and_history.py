import json
import pytest
from copy import deepcopy
from src.oracle.fast_lane_publisher import FastLaneSnapshotProcessor, _make_lean_live_feed


def test_fast_lane_lean_payload_reduction_and_structure():
    """Verify that FastLaneSnapshotProcessor materially reduces live payload size while preserving structure."""
    processor = FastLaneSnapshotProcessor()

    # Heavy mock data representative of full state
    heavy_strategies = {
        "ok": True,
        "data": {
            "summary": {"active_count": 2, "top_strategy": "pullback-master"},
            "edge_lab": {"large_sim_table": [list(range(100)) for _ in range(50)]}, # ~50 KB
            "audit": {"log": ["audit_entry_" + str(i) for i in range(1000)]}, # ~30 KB
            "versions": {"v1": "data", "v2": "data", "v3": "data"},
            "notifications": [{"id": f"notif_{i}", "msg": "alert"} for i in range(50)],
            "closed_trades": [{"trade_id": f"t_{i}", "pnl": i*10} for i in range(100)],
            "deployments": [
                {
                    "strategy_id": "pullback-v1",
                    "instance_id": "inst-1",
                    "name": "Pullback Master",
                    "status": "RUNNING",
                    "scheduler": {"state": "RUNNING"},
                    "positions": [],
                    "pnl": 1500.0,
                    "metrics": {"win_rate": 0.65},
                    "realized_pnl": 1500.0,
                    "unrealized_pnl": 0.0,
                    "bulky_config_schema": {"schema": "lots_of_definitions" * 100}
                }
            ]
        },
        "meta": {"module": "strategies", "health": "HEALTHY", "readiness": "READY"}
    }

    heavy_chart = {
        "ok": True,
        "data": {
            "symbol": "NIFTY",
            "timeframe": "5m",
            "candles": [{"open": 24000+i, "high": 24010+i, "low": 23990+i, "close": 24005+i, "volume": 1000} for i in range(500)], # ~50 KB
            "timeframes": {
                "5m": {"candles": [{"open": 24000+i, "high": 24010+i, "low": 23990+i, "close": 24005+i} for i in range(500)]}
            },
            "levels": {"r1": 24300, "s1": 24100},
            "forecast": {"bias": "BULLISH"},
            "decision_hud": {"status": "ACTIVE"}
        },
        "meta": {"module": "futures_chart", "health": "HEALTHY", "readiness": "READY"}
    }

    heavy_argus = {
        "ok": True,
        "data": {
            "data": {
                "tactical_edge": {
                    "decision": {"direction": "BUY", "confidence": 85, "all_candidate_ranks": list(range(1000))},
                    "direction": "BUY",
                    "scores": {"flow": 80, "gamma": 75},
                    "pressure": {"value": 1.2},
                    "breadth": {"value": 0.8},
                    "quality": {"grade": "A"},
                    "setups": ["pullback_bounce"],
                    "atm_window": [{"strike": 24100 + i*50, "ce_oi": 1000, "pe_oi": 1000} for i in range(7)],
                    "argus_prime": {
                        "full_evidence": {"raw_payload_copies": [list(range(100)) for _ in range(50)]}, # ~50 KB
                        "strike_spine": {"strikes": [{"strike": 24000 + i*50} for i in range(30)]}
                    },
                    "contract_selection": {
                        "directive_contract": "NIFTY24AUG24250CE",
                        "CE": "24250CE",
                        "PE": "24250PE",
                        "all_candidate_ranks": list(range(1000))
                    }
                }
            }
        },
        "meta": {"module": "argus", "health": "HEALTHY", "readiness": "READY"}
    }

    # Test raw vs lean feed
    lean_st = _make_lean_live_feed("strategies", heavy_strategies)
    lean_fc = _make_lean_live_feed("futures_chart", heavy_chart)
    lean_arg = _make_lean_live_feed("argus", heavy_argus)

    raw_total = len(json.dumps(heavy_strategies)) + len(json.dumps(heavy_chart)) + len(json.dumps(heavy_argus))
    lean_total = len(json.dumps(lean_st)) + len(json.dumps(lean_fc)) + len(json.dumps(lean_arg))

    # Verify > 50% reduction
    reduction = (raw_total - lean_total) / raw_total
    assert reduction >= 0.50, f"Expected >= 50% reduction, got {reduction*100:.1f}%"

    # Verify live field preservation
    assert lean_st["data"]["summary"]["active_count"] == 2
    assert lean_st["data"]["deployments"][0]["name"] == "Pullback Master"
    assert "bulky_config_schema" not in lean_st["data"]["deployments"][0]

    assert len(lean_fc["data"]["candles"]) == 100
    assert lean_fc["data"]["levels"]["r1"] == 24300
    assert lean_fc["data"]["forecast"]["bias"] == "BULLISH"

    tac = lean_arg["data"]["data"]["tactical_edge"]
    assert tac["decision"]["direction"] == "BUY"
    assert tac["contract_selection"]["directive_contract"] == "NIFTY24AUG24250CE"
    assert "full_evidence" not in tac["argus_prime"]
    assert len(tac["argus_prime"]["strike_spine"]["strikes"]) == 7


def test_fast_lane_vob_projection_removes_only_redundant_ladders():
    lane = {
        "demand": {"zone_id": "support", "zone_low": 100.0, "zone_high": 101.0},
        "supply": {"zone_id": "resistance", "zone_low": 110.0, "zone_high": 111.0},
        "latest_finalized_bar": {"close": 105.0},
        "zone_ladder": [{"zone_id": f"zone-{index}"} for index in range(100)],
    }
    vob = {
        "security_id": "101",
        "horsepower": {"combined": "NO CLEAN STRUCTURAL CHANGE"},
        "timeframes": {"1m": lane, "3m": lane, "5m": lane},
    }
    feed = {
        "ok": True,
        "data": {
            "revision": 7,
            "current_itm_vobs": {"CE": vob},
            "current_itm1_contracts": {"CE": {"quote": {"bid": 10.0}, "vob": vob}},
            "option_contracts": {"CE": {"contract_status": "CURRENT_ITM1", "vob": vob}},
        },
        "meta": {},
    }

    lean = _make_lean_live_feed("vob_reversal", feed)

    assert "current_itm_vobs" not in lean["data"]
    for collection_name in ("current_itm1_contracts", "option_contracts"):
        published_vob = lean["data"][collection_name]["CE"]["vob"]
        assert published_vob["horsepower"] == vob["horsepower"]
        assert published_vob["timeframes"]["3m"]["demand"] == lane["demand"]
        assert published_vob["timeframes"]["3m"]["latest_finalized_bar"] == lane["latest_finalized_bar"]
        assert "zone_ladder" not in published_vob["timeframes"]["3m"]
