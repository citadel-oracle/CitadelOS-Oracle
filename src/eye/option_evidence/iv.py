"""Implied Volatility (IV) Solvers & Provenance for Eye Engine Phase E4A."""

import math
from datetime import datetime
from typing import Optional, Dict, Any
from src.eye.option_evidence.contracts import ImpliedVolatilityObservation, PriceReference
from src.eye.option_evidence.sources import SourceType
from src.eye.option_evidence.greeks import norm_cdf, norm_pdf, calculate_black_scholes_greeks, GreekType


def calculate_black_scholes_option_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> float:
    """Calculate theoretical Black-Scholes option price."""
    if spot <= 0 or strike <= 0 or time_to_expiry_years <= 0 or volatility <= 0:
        return 0.0

    S = spot
    K = strike
    T = time_to_expiry_years
    r = risk_free_rate
    sigma = volatility
    q = dividend_yield

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    if option_type.upper() == "CE":
        return S * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * norm_cdf(-d2) - S * math.exp(-q * T) * norm_cdf(-d1)


def solve_implied_volatility(
    option_price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: str,
    dividend_yield: float = 0.0,
    max_iterations: int = 100,
    tolerance: float = 1e-5,
) -> Optional[float]:
    """Solve for Black-Scholes implied volatility using Newton-Raphson & Bisection fallbacks."""
    if spot <= 0 or strike <= 0 or time_to_expiry_years <= 0 or option_price <= 0:
        return None

    S = spot
    K = strike
    T = time_to_expiry_years
    r = risk_free_rate
    q = dividend_yield
    opt_type = option_type.upper()

    # 1. No-arbitrage lower bound check
    df_r = math.exp(-r * T)
    df_q = math.exp(-q * T)

    if opt_type == "CE":
        lower_bound = max(0.0, S * df_q - K * df_r)
        upper_bound = S * df_q
    else:
        lower_bound = max(0.0, K * df_r - S * df_q)
        upper_bound = K * df_r

    if option_price < lower_bound - 1e-4 or option_price > upper_bound + 1e-4:
        # Fails no-arbitrage bounds
        return None

    # 2. Newton-Raphson iteration
    sigma = 0.20  # Initial guess 20%
    for _ in range(max_iterations):
        price = calculate_black_scholes_option_price(S, K, T, r, sigma, opt_type, q)
        diff = price - option_price
        if abs(diff) < tolerance:
            return round(sigma, 6)

        greeks = calculate_black_scholes_greeks(S, K, T, r, sigma, opt_type, q)
        vega = greeks.get(GreekType.VEGA, 0.0) * 100.0  # Convert back from % vega
        if vega <= 1e-8:
            break

        sigma -= diff / vega
        if sigma <= 0.001 or sigma > 5.0:
            break

    # 3. Bisection fallback if Newton-Raphson fails
    low = 0.001
    high = 5.0
    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        price = calculate_black_scholes_option_price(S, K, T, r, mid, opt_type, q)
        diff = price - option_price
        if abs(diff) < tolerance:
            return round(mid, 6)
        if price > option_price:
            high = mid
        else:
            low = mid

    return None
