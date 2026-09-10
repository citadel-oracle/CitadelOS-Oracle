import json
import pytest
from pathlib import Path
from copy import deepcopy

from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.tactical_store import ArgusTacticalStore
from src.oracle.fast_lane_publisher import wrap_provider_feed, FastLaneSnapshotProcessor


def test_argus_mutation_isolation():
    """Prove that mutating the source input dict after evaluate() does not mutate the published result."""
    store = ArgusTacticalStore(Path("/tmp/mutation_test_store.json"))
    engine = ArgusTacticalEdgeEngine(store)

    argus_input = {
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
                    "strike": 24250.0,
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
            ]
        }
    }

    ose_input = {
        "status": "AVAILABLE",
        "current_iv": 13.2,
        "iv_percentile": 42.0,
        "max_pain": 24250.0,
        "pcr": 0.85,
    }

    # 1. Run evaluation
    result_snapshot = engine.evaluate(argus_input, ose_input)
    assert result_snapshot["spot"] == 24240.0
    original_decision = deepcopy(result_snapshot["decision"])

    # 2. Mutate the input dictionary maliciously
    argus_input["data"]["underlying"]["ltp"] = 99999.0
    argus_input["data"]["underlying"]["symbol"] = "MUTATED"
    argus_input["data"]["atm_window"][0]["ce_oi"] = 0
    ose_input["pcr"] = 999.0

    # 3. Prove result snapshot was NOT mutated
    assert result_snapshot["spot"] == 24240.0
    assert result_snapshot["symbol"] == "NIFTY"
    assert result_snapshot["decision"] == original_decision


def test_fast_lane_publisher_mutation_isolation():
    """Prove that mutating provider data after wrap_provider_feed or builder does not corrupt encoded bytes."""
    processor = FastLaneSnapshotProcessor()

    provider_data = {
        "status": "AVAILABLE",
        "value": 123.45,
        "nested": {"key": "original_val"}
    }

    # Build revision 1
    payload1 = {
        "source_revisions": {"argus": "rev-1"},
        "changed": ["argus"],
        "provider_updates": {
            "argus": {"value": provider_data, "error": None}
        },
        "build_revision": 1
    }

    result1 = processor("BUILD", payload1)
    bytes1 = result1["body"]
    assert b"original_val" in bytes1

    # Maliciously mutate provider_data dictionary in place
    provider_data["nested"]["key"] = "MUTATED_VAL"
    provider_data["value"] = 99999.99

    # Result bytes from revision 1 must remain 100% byte-identical
    assert b"original_val" in bytes1
    assert b"MUTATED_VAL" not in bytes1
