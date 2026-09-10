"""E4A-C Test for Greeks Model Provenance."""

import pytest
from src.eye.option_evidence.greeks import calculate_black_scholes_greeks, GreekType


def test_black_scholes_greeks_provenance_and_ranges():
    T = 30.0 / 365.0
    greeks = calculate_black_scholes_greeks(24500.0, 24500.0, T, 0.065, 0.15, "CE")

    assert GreekType.DELTA in greeks
    assert GreekType.GAMMA in greeks
    assert GreekType.THETA in greeks
    assert GreekType.VEGA in greeks

    assert 0.45 <= greeks[GreekType.DELTA] <= 0.60
    assert greeks[GreekType.GAMMA] > 0
    assert greeks[GreekType.VEGA] > 0
