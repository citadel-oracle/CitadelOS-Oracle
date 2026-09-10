"""E4A Exact vs Rolling History Boundary Isolation Tests."""

import pytest
from src.eye.option_evidence.rolling_history_adapter import generate_rolling_series_key


def test_rolling_series_key_does_not_collide_with_exact_contract_key():
    r_key = generate_rolling_series_key("NIFTY", "WEEKLY", "ATM+1", "CE")
    assert r_key.series_key == "ROLLING:NIFTY:WEEKLY:ATM+1:CE"
    assert not r_key.series_key.startswith("OPTCONTRACT:")
