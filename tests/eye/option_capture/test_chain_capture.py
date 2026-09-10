"""E4A-E Test for Option Chain REST Collector."""

import json
import pytest
from src.eye.option_capture.chain_collector import OptionChainCollector


def test_chain_collector_parsing():
    collector = OptionChainCollector(cadence_seconds=0.0)
    data = {
        "status": "success",
        "data": {
            "oc": {
                "24500.0": {
                    "ce": {"security_id": 43210, "last_price": 150.0, "volume": 1000},
                    "pe": {"security_id": 43211, "last_price": 120.0, "volume": 800},
                }
            }
        }
    }
    raw_bytes = json.dumps(data).encode("utf-8")
    res = collector.parse_chain_response(raw_bytes)

    assert "chain_matrix" in res
    assert "24500.0" in res["chain_matrix"]
