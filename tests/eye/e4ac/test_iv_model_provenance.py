"""E4A-C Test for IV Model Provenance."""

import pytest
from src.eye.option_evidence.iv import solve_implied_volatility, calculate_black_scholes_option_price


def test_iv_solver_provenance_and_arbitrage_bounds():
    T = 30.0 / 365.0
    price = calculate_black_scholes_option_price(24500.0, 24500.0, T, 0.065, 0.15, "CE")

    iv_solved = solve_implied_volatility(price, 24500.0, 24500.0, T, 0.065, "CE")
    assert iv_solved is not None
    assert abs(iv_solved - 0.15) < 0.001

    # Price failing lower bound returns None (IV_UNAVAILABLE)
    iv_bad = solve_implied_volatility(0.001, 24500.0, 24000.0, T, 0.065, "CE")
    assert iv_bad is None
