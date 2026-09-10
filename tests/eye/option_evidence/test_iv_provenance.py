"""E4A Implied Volatility (IV) Provenance & Solver Tests."""

import pytest
from src.eye.option_evidence.iv import solve_implied_volatility, calculate_black_scholes_option_price


def test_iv_solver_and_no_arbitrage_bounds():
    # Spot 24500, Strike 24500, T = 30 days (30/365), r = 6.5%, IV = 15%
    T = 30.0 / 365.0
    bs_price = calculate_black_scholes_option_price(24500.0, 24500.0, T, 0.065, 0.15, "CE")
    assert bs_price > 0

    # Solve IV from BS price
    iv_solved = solve_implied_volatility(bs_price, 24500.0, 24500.0, T, 0.065, "CE")
    assert iv_solved is not None
    assert abs(iv_solved - 0.15) < 0.001

    # 2. Invalid price below no-arbitrage lower bound must return None (IV_UNAVAILABLE)
    invalid_price = 0.01
    iv_failed = solve_implied_volatility(invalid_price, 24500.0, 24000.0, T, 0.065, "CE")
    assert iv_failed is None
