"""Unit and mathematical invariant tests for Option Intelligence Engine."""

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest

from src.oracle.option_intelligence import (
    OptionIntelligenceEngine,
    calculate_bs_greeks,
    black76_price,
    solve_iv_bisection,
)

IST = ZoneInfo("Asia/Kolkata")


def test_black_scholes_greeks_invariants():
    spot = 24500.0
    strike = 24500.0
    time_years = 7.0 / 365.0
    rate = 0.065
    vol = 0.14

    ce = calculate_bs_greeks(spot, strike, time_years, rate, vol, "CE")
    assert ce is not None
    assert 0.45 <= ce["delta"] <= 0.58
    assert ce["gamma"] > 0
    assert ce["theta"] < 0
    assert ce["vega"] > 0

    pe = calculate_bs_greeks(spot, strike, time_years, rate, vol, "PE")
    assert pe is not None
    assert -0.58 <= pe["delta"] <= -0.42
    assert pe["gamma"] > 0
    assert pe["theta"] < 0
    assert pe["vega"] > 0

    # Put-Call Delta parity: Delta_CE - Delta_PE approx exp(-q*T) approx 1.0
    assert abs((ce["delta"] - pe["delta"]) - 1.0) < 0.05
    # Gamma parity: Gamma_CE == Gamma_PE
    assert abs(ce["gamma"] - pe["gamma"]) < 1e-6


def test_black76_and_iv_inversion():
    forward = 24550.0
    strike = 24500.0
    time_years = 5.0 / 365.0
    rate = 0.065
    target_iv = 0.155

    price_ce = black76_price(forward, strike, time_years, target_iv, rate, "CE")
    assert price_ce is not None and price_ce > 50.0

    solved_iv = solve_iv_bisection(price_ce, forward, strike, time_years, rate, "CE")
    assert solved_iv is not None
    assert abs(solved_iv - target_iv) < 0.001


def test_option_intelligence_evaluate_ladder():
    engine = OptionIntelligenceEngine(lot_size=65, rate=0.065)
    base_time = datetime(2026, 8, 22, 11, 30, tzinfo=IST)
    expiry = "2026-08-27"
    forward = 24500.0

    # Pre-record causal minute returns for RV computation
    for i in range(5):
        t = base_time - timedelta(minutes=5 - i)
        engine.record_spot_price(24500.0 + (i * 2.5), t)

    observed_at = base_time

    # Generate synthetic strike ladder: 24300 to 24700 (9 strikes)
    rows = []
    for k in range(24300, 24800, 50):
        iv_pe = 0.16 + max(0, (24500 - k) / 24500.0) * 0.15
        iv_ce = 0.14 + max(0, (k - 24500) / 24500.0) * 0.10

        p_ce = black76_price(forward, float(k), 5.0 / 365.0, iv_ce, 0.065, "CE") or 10.0
        p_pe = black76_price(forward, float(k), 5.0 / 365.0, iv_pe, 0.065, "PE") or 10.0

        rows.append({
            "strike": k,
            "ce": {
                "top_bid_price": round(p_ce - 0.5, 2),
                "top_ask_price": round(p_ce + 0.5, 2),
                "ltp": round(p_ce, 2),
                "oi": 50000 + (24700 - k) * 50,
                "implied_volatility": round(iv_ce * 100.0, 2),
            },
            "pe": {
                "top_bid_price": round(p_pe - 0.5, 2),
                "top_ask_price": round(p_pe + 0.5, 2),
                "ltp": round(p_pe, 2),
                "oi": 60000 + (k - 24300) * 50,
                "implied_volatility": round(iv_pe * 100.0, 2),
            },
        })

    result = engine.evaluate(rows, forward, observed_at, expiry)
    assert result["status"] == "LIVE"
    assert result["schema_version"] == "1.0.0"

    # GEX assertions
    gex = result["gex"]
    assert gex is not None
    assert "total_net_gex_inr_cr" in gex
    assert "total_call_gex_inr_cr" in gex
    assert "total_put_gex_inr_cr" in gex
    assert gex["total_call_gex_inr_cr"] >= 0
    assert gex["total_put_gex_inr_cr"] <= 0
    assert gex["dealer_regime"] in ("LONG_GAMMA_PIN", "SHORT_GAMMA_AMPLIFY")
    assert gex["zero_gamma_strike"] is not None
    assert len(gex["strike_profile"]) == len(rows)

    # Skew assertions
    skew = result["iv_skew"]
    assert skew is not None
    assert skew["call_25d"] is not None
    assert skew["put_25d"] is not None
    assert skew["skew_25d_spread"] is not None
    assert skew["skew_regime"] in ("PUT_SKEW_ELEVATED", "CALL_SKEW_ELEVATED", "BALANCED")

    # Gamma/Theta Quality assertions
    quality = result["gamma_theta_quality"]
    assert quality is not None
    assert quality["atm_ce"] is not None
    assert quality["atm_ce"]["quality_ratio"] > 0
    assert quality["atm_ce"]["rating"] in ("PRIME", "ACCEPTABLE", "POOR")

    # Volatility Opportunity & HAR-RV assertions
    vol = result["volatility_opportunity"]
    assert vol is not None
    assert vol["atm_iv"] > 0
    assert vol["intraday_rv_annualized"] is not None
    assert vol["har_rv_forecast_annualized"] is not None
    assert "iv_rv_spread" in vol
    assert vol["vol_premium_regime"] in ("OVERPRICED_PREMIUM", "UNDERPRICED_PREMIUM", "FAIR")


def test_unavailable_handling():
    engine = OptionIntelligenceEngine()
    # Empty rows
    res1 = engine.evaluate([], 24500.0, datetime.now(tz=IST), "2026-08-27")
    assert res1["status"] == "UNAVAILABLE"

    # None forward
    res2 = engine.evaluate([{"strike": 24500}], None, datetime.now(tz=IST), "2026-08-27")
    assert res2["status"] == "UNAVAILABLE"


def test_repo_skew_momentum_skips_missing_observations_without_zero_fill():
    base_time = datetime(2026, 8, 24, 10, 0, tzinfo=IST)
    valid_pairs = [
        (-1.5, -0.9),
        (-1.3, -0.7),
        (-1.1, -0.5),
        (-0.8, -0.2),
        (-0.4, 0.1),
    ]

    clean = OptionIntelligenceEngine()
    with_missing = OptionIntelligenceEngine()
    for index, (skew_25d, skew_10d) in enumerate(valid_pairs):
        observed_at = base_time + timedelta(seconds=index * 6)
        clean.record_iv_skew(12.0, skew_25d, observed_at, skew_10d=skew_10d)
        with_missing.record_iv_skew(12.0, skew_25d, observed_at, skew_10d=skew_10d)
        if index < len(valid_pairs) - 1:
            with_missing.record_iv_skew(
                12.0, None, observed_at + timedelta(seconds=3), skew_10d=None
            )

    clean_result = clean.calculate_repo_skew_momentum()
    missing_result = with_missing.calculate_repo_skew_momentum()
    assert missing_result == clean_result

    missing_25d = OptionIntelligenceEngine()
    for index in range(8):
        missing_25d.record_iv_skew(
            12.0, None, base_time + timedelta(seconds=index * 3), skew_10d=0.2
        )
    assert missing_25d.calculate_repo_skew_momentum()["repo_skew_velocity"] is None

    missing_10d = OptionIntelligenceEngine()
    for index, (skew_25d, _) in enumerate(valid_pairs):
        missing_10d.record_iv_skew(
            12.0, skew_25d, base_time + timedelta(seconds=index * 3), skew_10d=None
        )
    result = missing_10d.calculate_repo_skew_momentum()
    assert result["repo_skew_velocity"] is not None
    assert result["repo_10d_wing_velocity"] is None
    assert result["repo_wing_confirms"] is None
