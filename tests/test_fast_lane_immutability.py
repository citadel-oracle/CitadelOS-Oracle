"""Comprehensive regression test proving Fast Lane snapshot immutability with production structures."""

import hashlib
import json
import time
from src.oracle.fast_lane_publisher import FastLaneSnapshotProcessor


def test_production_structure_fast_lane_immutability():
    processor = FastLaneSnapshotProcessor()

    # Build full production-like input structures
    live_workspace = {
        "active_symbol": "NIFTY",
        "positions": [{"id": "pos_1", "strike": 24500, "side": "CE", "qty": 75}],
        "metrics": {"total_pnl": 1250.50, "max_drawdown": -300.0},
        "flags": {"can_trade": False, "guard_active": True},
    }

    obi_feed = {
        "status": "AVAILABLE",
        "data": {
            "CE": {
                "fair_price": 210.50,
                "ask": 211.00,
                "bid": 210.00,
                "book": {
                    "best_bid": {"price": 210.0, "quantity": 1500, "orders": 5},
                    "best_ask": {"price": 211.0, "quantity": 800, "orders": 3},
                    "levels": [210.0, 209.5, 209.0],
                },
                "market_pressure": {"total_buy_quantity": 50000, "total_sell_quantity": 30000},
            },
            "PE": {
                "fair_price": 125.00,
                "ask": 125.50,
                "bid": 124.50,
                "book": {"best_bid": {"price": 124.5, "quantity": 2000, "orders": 8}},
            },
            "straddle": {"now": 335.50, "change_5m": -2.50},
        },
    }

    order_flow_feed = {
        "status": "AVAILABLE",
        "data": {
            "mlofi": {"current": 0.45, "session_extreme": 0.82},
            "cvd": {"delta": 15000, "history": [100, 250, 400]},
            "recent_trades": [{"price": 23820.0, "qty": 50, "aggressor": "BUY"}],
        },
    }

    payload_r = {
        "build_revision": 100,
        "runtime_instance_id": "inst_001",
        "source_revisions": {"oracle": "1", "obi": "1", "order_flow": "1"},
        "base_updates": {
            "oracle": {"status": "AVAILABLE", "data": {"session": "MORNING"}},
            "option_buyer_intelligence": obi_feed,
            "order_flow": order_flow_feed,
        },
        "workspace_update": {"value": live_workspace},
        "changed": ["oracle", "option_buyer_intelligence", "order_flow"],
    }

    # Publish revision R
    doc_r = processor("BUILD", payload_r)
    assert doc_r is not None
    body_r_original = doc_r["body"]
    hash_r_original = hashlib.sha256(body_r_original).hexdigest()
    parsed_r_original = json.loads(body_r_original.decode())

    # 1. Mutate all original producer-owned nested inputs
    live_workspace["positions"][0]["qty"] = 999999
    live_workspace["positions"].append({"id": "pos_MUTATED", "strike": 99999})
    live_workspace["metrics"]["total_pnl"] = -999999.0
    obi_feed["data"]["CE"]["fair_price"] = 9999.99
    obi_feed["data"]["CE"]["book"]["best_bid"]["price"] = 8888.88
    obi_feed["data"]["CE"]["book"]["levels"].append(0.0)
    order_flow_feed["data"]["cvd"]["history"].clear()
    order_flow_feed["data"]["recent_trades"][0]["price"] = 0.0

    # Assert R body and parsed content remain completely unchanged after input mutation
    assert doc_r["body"] == body_r_original
    assert hashlib.sha256(doc_r["body"]).hexdigest() == hash_r_original
    assert json.loads(doc_r["body"].decode()) == parsed_r_original

    # 2. Build revision R+1 with new changes
    new_workspace = {"active_symbol": "NIFTY", "positions": [], "metrics": {"total_pnl": 50.0}}
    payload_r1 = {
        "build_revision": 101,
        "runtime_instance_id": "inst_001",
        "source_revisions": {"oracle": "2", "obi": "1", "order_flow": "1"},
        "base_updates": {},
        "workspace_update": {"value": new_workspace},
        "changed": ["oracle"],
    }

    doc_r1 = processor("BUILD", payload_r1)
    assert doc_r1 is not None

    # Assert R remains strictly unchanged after building R+1
    assert doc_r["body"] == body_r_original
    assert hashlib.sha256(doc_r["body"]).hexdigest() == hash_r_original
    assert json.loads(doc_r["body"].decode()) == parsed_r_original

    # Assert R+1 has the updated revision and workspace
    parsed_r1 = json.loads(doc_r1["body"].decode())
    assert parsed_r1["revision"] == 101
    assert parsed_r1["feeds"]["oracle"]["data"]["live_workspace"]["metrics"]["total_pnl"] == 50.0

    # 3. Benchmark real execution timing
    iterations = 50
    t0 = time.perf_counter()
    for i in range(iterations):
        processor("BUILD", {
            "build_revision": 102 + i,
            "runtime_instance_id": "inst_001",
            "source_revisions": {"oracle": f"{3 + i}", "obi": "1", "order_flow": "1"},
            "base_updates": {},
            "workspace_update": {"value": {"iter": i}},
            "changed": ["oracle"],
        })
    elapsed_ms = (time.perf_counter() - t0) * 1000.0 / iterations
    assert elapsed_ms < 20.0  # Real timing must be fast (< 20ms per build)
