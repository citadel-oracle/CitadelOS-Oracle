"""E4A Greeks Provenance & Independent Calculation Tests."""

import pytest
from src.eye.option_evidence.greeks import calculate_black_scholes_greeks, calculate_regulatory_futeq_delta, GreekType


def test_black_scholes_greeks_and_regulatory_futeq():
    # Spot 24500, Strike 24500, 30 days to expiry, 6.5% rate, 15% IV
    T = 30.0 / 365.0
    greeks_ce = calculate_black_scholes_greeks(24500.0, 24500.0, T, 0.065, 0.15, "CE")

    assert GreekType.DELTA in greeks_ce
    delta_ce = greeks_ce[GreekType.DELTA]
    assert 0.45 <= delta_ce <= 0.60

    # Put delta must be negative
    greeks_pe = calculate_black_scholes_greeks(24500.0, 24500.0, T, 0.065, 0.15, "PE")
    delta_pe = greeks_pe[GreekType.DELTA]
    assert -0.55 <= delta_pe <= -0.40

    # SEBI Regulatory FutEq Delta calculation (25 lot size * delta)
    res = calculate_regulatory_futeq_delta(25, delta_ce, 24500.0)
    assert res.delta_adjusted_quantity > 0
    assert res.classification == "REGULATORY_DELTA_INPUT_ONLY"
    assert res.compliance_claim_made is False
