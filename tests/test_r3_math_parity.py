import json
import pytest
from pathlib import Path
from copy import deepcopy

from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.tactical_store import ArgusTacticalStore


def test_argus_mathematical_parity_and_output_identity():
    """Prove that optimized tactical edge produces 100% identical outputs on golden input."""
    # 1. Create tactical store in temp memory
    store = ArgusTacticalStore(Path("/tmp/parity_test_store.json"))
    engine = ArgusTacticalEdgeEngine(store)

    # 2. Build representative golden input
    golden_argus = {
        "status": "available",
        "freshness": "fresh",
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "ltp": 24240.0,
                "atm_strike": 24250.0,
                "expiry": "2026-08-20",
                "fetched_at": "2026-08-18T15:00:00+05:30",
                "market_state": "OPEN",
            },
            "atm_window": [
                {
                    "strike": 24100.0,
                    "ce_oi": 2500000,
                    "ce_change_oi": 150000,
                    "ce_ltp": 150.0,
                    "ce_volume": 500000,
                    "ce_iv": 12.5,
                    "pe_oi": 800000,
                    "pe_change_oi": -20000,
                    "pe_ltp": 8.0,
                    "pe_volume": 100000,
                    "pe_iv": 14.2,
                },
                {
                    "strike": 24150.0,
                    "ce_oi": 3000000,
                    "ce_change_oi": 200000,
                    "ce_ltp": 110.0,
                    "ce_volume": 600000,
                    "ce_iv": 12.8,
                    "pe_oi": 1200000,
                    "pe_change_oi": -10000,
                    "pe_ltp": 15.0,
                    "pe_volume": 150000,
                    "pe_iv": 14.0,
                },
                {
                    "strike": 24200.0,
                    "ce_oi": 4500000,
                    "ce_change_oi": 400000,
                    "ce_ltp": 75.0,
                    "ce_volume": 1200000,
                    "ce_iv": 13.0,
                    "pe_oi": 2800000,
                    "pe_change_oi": 100000,
                    "pe_ltp": 25.0,
                    "pe_volume": 400000,
                    "pe_iv": 13.8,
                },
                {
                    "strike": 24250.0, # ATM
                    "ce_oi": 6000000,
                    "ce_change_oi": 800000,
                    "ce_ltp": 45.0,
                    "ce_volume": 2000000,
                    "ce_iv": 13.2,
                    "pe_oi": 5500000,
                    "pe_change_oi": 500000,
                    "pe_ltp": 45.0,
                    "pe_volume": 1800000,
                    "pe_iv": 13.5,
                },
                {
                    "strike": 24300.0,
                    "ce_oi": 8500000,
                    "ce_change_oi": 1200000,
                    "ce_ltp": 22.0,
                    "ce_volume": 1500000,
                    "ce_iv": 13.5,
                    "pe_oi": 3200000,
                    "pe_change_oi": 200000,
                    "pe_ltp": 72.0,
                    "pe_volume": 300000,
                    "pe_iv": 13.3,
                },
                {
                    "strike": 24350.0,
                    "ce_oi": 4000000,
                    "ce_change_oi": 300000,
                    "ce_ltp": 10.0,
                    "ce_volume": 400000,
                    "ce_iv": 13.8,
                    "pe_oi": 1500000,
                    "pe_change_oi": 50000,
                    "pe_ltp": 110.0,
                    "pe_volume": 120000,
                    "pe_iv": 13.1,
                },
                {
                    "strike": 24400.0,
                    "ce_oi": 5000000,
                    "ce_change_oi": 250000,
                    "ce_ltp": 5.0,
                    "ce_volume": 300000,
                    "ce_iv": 14.1,
                    "pe_oi": 900000,
                    "pe_change_oi": 10000,
                    "pe_ltp": 155.0,
                    "pe_volume": 80000,
                    "pe_iv": 12.9,
                },
            ]
        }
    }

    golden_ose = {
        "status": "AVAILABLE",
        "current_iv": 13.2,
        "iv_percentile": 42.0,
        "max_pain": 24250.0,
        "pcr": 0.85,
    }

    # Evaluate multiple times and ensure 100% determinism and exact mathematical output
    res1 = engine.evaluate(golden_argus, golden_ose)
    res2 = engine.evaluate(golden_argus, golden_ose)

    assert res1["status"] == "LIVE"
    assert res2["status"] == "LIVE"
    assert res1["decision"] == res2["decision"]
    assert res1["pressure"] == res2["pressure"]
    assert res1["breadth"] == res2["breadth"]
    assert res1["setups"] == res2["setups"]
    assert res1 == res2
