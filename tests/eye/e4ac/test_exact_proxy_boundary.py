"""E4A-C Test for Exact vs Proxy Boundary Isolation."""

import pytest
from src.eye.option_evidence.rolling_history_adapter import generate_rolling_series_key


def test_proxy_series_key_format_isolation():
    key_proxy = generate_rolling_series_key("NIFTY", "NEAR", "ATM", "CE")
    assert key_proxy.series_key.startswith("ROLLING:")
    assert not key_proxy.series_key.startswith("OPTCONTRACT:")
