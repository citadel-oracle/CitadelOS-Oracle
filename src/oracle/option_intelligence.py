"""Pure, deterministic Option Intelligence engine for CITADEL Oracle.

Computes:
1. Full-ladder Black-Scholes Greeks (Delta, Gamma, Theta, Vega) per strike
2. 10D and 25D Put-Call IV Skew and regime classification
3. Per-strike and Aggregate GEX (Gamma Exposure), Zero-Gamma level, and Dealer Regime
4. Gamma/Theta Quality Ratio for Option Buying
5. Intraday Realized Volatility and HAR-RV multi-horizon volatility forecast with IV-RV spread

Zero I/O, zero network calls, strictly causal and watermark-bounded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def calculate_bs_greeks(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    volatility: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> dict[str, float] | None:
    """Calculate analytical Black-Scholes Greeks."""
    if spot <= 0 or strike <= 0 or time_years <= 0 or volatility <= 0:
        return None

    S = spot
    K = strike
    T = time_years
    r = rate
    sigma = volatility
    q = dividend_yield

    sqrt_T = math.sqrt(T)
    if sqrt_T <= 0:
        return None

    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    opt_type = option_type.upper()
    pdf_d1 = _norm_pdf(d1)

    if opt_type == "CE":
        delta = math.exp(-q * T) * _norm_cdf(d1)
        theta = (
            -(S * sigma * math.exp(-q * T) * pdf_d1) / (2.0 * sqrt_T)
            - r * K * math.exp(-r * T) * _norm_cdf(d2)
            + q * S * math.exp(-q * T) * _norm_cdf(d1)
        ) / 365.0
    elif opt_type == "PE":
        delta = -math.exp(-q * T) * _norm_cdf(-d1)
        theta = (
            -(S * sigma * math.exp(-q * T) * pdf_d1) / (2.0 * sqrt_T)
            + r * K * math.exp(-r * T) * _norm_cdf(-d2)
            - q * S * math.exp(-q * T) * _norm_cdf(-d1)
        ) / 365.0
    else:
        return None

    gamma = (math.exp(-q * T) * pdf_d1) / (S * sigma * sqrt_T)
    vega = (S * math.exp(-q * T) * pdf_d1 * sqrt_T) / 100.0  # Vega per 1% vol change

    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 8),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
    }


def black76_price(
    forward: float,
    strike: float,
    time_years: float,
    volatility: float,
    rate: float,
    option_type: str,
) -> float | None:
    """Black-76 model price for futures / forward underlying."""
    if min(forward, strike, time_years, volatility) <= 0.0:
        return None
    sigma_root_t = volatility * math.sqrt(time_years)
    if sigma_root_t <= 0.0:
        return None
    d1 = (math.log(forward / strike) + 0.5 * volatility * volatility * time_years) / sigma_root_t
    d2 = d1 - sigma_root_t
    discount = math.exp(-rate * time_years)
    opt = option_type.upper()
    if opt == "CE":
        return discount * (forward * _norm_cdf(d1) - strike * _norm_cdf(d2))
    if opt == "PE":
        return discount * (strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1))
    return None


def solve_iv_bisection(
    price: float,
    forward: float,
    strike: float,
    time_years: float,
    rate: float,
    option_type: str,
    max_iterations: int = 80,
    tolerance: float = 1e-4,
) -> float | None:
    """Solve Black-76 implied volatility via robust bounded bisection."""
    if min(price, forward, strike, time_years) <= 0.0 or option_type not in {"CE", "PE"}:
        return None
    intrinsic = math.exp(-rate * time_years) * (
        max(forward - strike, 0.0) if option_type == "CE" else max(strike - forward, 0.0)
    )
    if price < intrinsic:
        return None
    low, high = 1e-4, 5.0
    high_p = black76_price(forward, strike, time_years, high, rate, option_type)
    if high_p is None or price > high_p:
        return None

    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        val = black76_price(forward, strike, time_years, mid, rate, option_type)
        if val is None:
            return None
        diff = val - price
        if abs(diff) < tolerance:
            return mid
        if val < price:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


@dataclass
class OptionIntelligenceEngine:
    """Unified Option Intelligence Engine."""

    lot_size: int = 65
    rate: float = 0.065
    har_intercept: float = 1.50
    har_beta_daily: float = 0.38
    har_beta_weekly: float = 0.33
    har_beta_monthly: float = 0.21

    # In-memory session return storage for 1-minute RV tracking (strictly causal)
    _spot_minute_prices: list[tuple[float, float]] = field(default_factory=list)  # (epoch, price)
    _daily_rv_history: list[float] = field(default_factory=list)
    _iv_skew_history: list[dict[str, float | None]] = field(default_factory=list)

    def record_spot_price(self, price: float, observed_at: datetime) -> None:
        """Record 1-minute interval spot price for intraday realized volatility."""
        if price is None or price <= 0 or observed_at is None:
            return
        epoch = observed_at.timestamp()
        # Enforce chronological ordering and 1-minute bucket deduplication
        if not self._spot_minute_prices:
            self._spot_minute_prices.append((epoch, price))
        elif epoch >= self._spot_minute_prices[-1][0] + 55.0:
            self._spot_minute_prices.append((epoch, price))
            if len(self._spot_minute_prices) > 500:
                self._spot_minute_prices.pop(0)

    def calculate_intraday_rv(self) -> float | None:
        """Compute annualized realized volatility from 1-minute log returns."""
        if len(self._spot_minute_prices) < 3:
            return None

        squared_returns = []
        for i in range(1, len(self._spot_minute_prices)):
            p0 = self._spot_minute_prices[i - 1][1]
            p1 = self._spot_minute_prices[i][1]
            if p0 > 0 and p1 > 0:
                ret = math.log(p1 / p0)
                squared_returns.append(ret * ret)

        if not squared_returns:
            return None

        mean_sq = sum(squared_returns) / len(squared_returns)
        rv_annualized = math.sqrt(252.0 * 375.0 * mean_sq) * 100.0
        return round(max(1.0, min(150.0, rv_annualized)), 2)

    def calculate_har_rv_forecast(self, current_day_rv: float | None) -> dict[str, Any] | None:
        """Compute multi-horizon HAR-RV forecast (1d, 5d, 22d)."""
        if current_day_rv is None:
            return None

        history = list(self._daily_rv_history) if self._daily_rv_history else [current_day_rv]
        daily_val = current_day_rv
        weekly_val = sum(history[-5:]) / min(5, len(history))
        monthly_val = sum(history[-22:]) / min(22, len(history))

        forecast = (
            self.har_intercept
            + self.har_beta_daily * daily_val
            + self.har_beta_weekly * weekly_val
            + self.har_beta_monthly * monthly_val
        )
        forecast = max(2.0, min(120.0, forecast))

        return {
            "forecast_annualized": round(forecast, 2),
            "daily_component": round(daily_val, 2),
            "weekly_component": round(weekly_val, 2),
            "monthly_component": round(monthly_val, 2),
        }

    def record_iv_skew(
        self,
        atm_iv: float | None,
        skew_25d: float | None,
        observed_at: datetime | None,
        *,
        c25_iv: float | None = None,
        p25_iv: float | None = None,
        c10_iv: float | None = None,
        p10_iv: float | None = None,
        skew_10d: float | None = None,
    ) -> None:
        """Record rolling IV and skew samples for continuous backend velocity calculation across all wings."""
        if observed_at is None or (atm_iv is None and skew_25d is None and c25_iv is None):
            return
        epoch = observed_at.timestamp()
        entry = {
            "epoch": epoch,
            "atm_iv": float(atm_iv) if atm_iv is not None else None,
            "skew_25d": float(skew_25d) if skew_25d is not None else None,
            "c25_iv": float(c25_iv) if c25_iv is not None else None,
            "p25_iv": float(p25_iv) if p25_iv is not None else None,
            "c10_iv": float(c10_iv) if c10_iv is not None else None,
            "p10_iv": float(p10_iv) if p10_iv is not None else None,
            "skew_10d": float(skew_10d) if skew_10d is not None else None,
        }
        if not self._iv_skew_history:
            self._iv_skew_history.append(entry)
        elif epoch >= self._iv_skew_history[-1].get("epoch", 0.0) + 3.0:
            self._iv_skew_history.append(entry)
            if len(self._iv_skew_history) > 600:  # 600 * 3s = 1800s (30 mins)
                self._iv_skew_history.pop(0)

    def calculate_iv_skew_velocities(
        self,
        current_atm_iv: float | None,
        current_skew: float | None,
        observed_at: datetime | None,
        *,
        c25_iv: float | None = None,
        p25_iv: float | None = None,
        c10_iv: float | None = None,
        p10_iv: float | None = None,
        skew_10d: float | None = None,
    ) -> dict[str, Any]:
        """Compute rolling 5M and 15M IV and skew deltas directly from backend history for all wings."""
        if not observed_at or not self._iv_skew_history:
            return {
                "iv_5m_delta": None,
                "iv_15m_delta": None,
                "c25_5m_delta": None,
                "c25_15m_delta": None,
                "p25_5m_delta": None,
                "p25_15m_delta": None,
                "c10_5m_delta": None,
                "c10_15m_delta": None,
                "p10_5m_delta": None,
                "p10_15m_delta": None,
                "skew_5m_delta": None,
                "skew_15m_delta": None,
                "skew_10d_5m_delta": None,
                "skew_10d_15m_delta": None,
                "history_depth_seconds": 0.0,
            }
        now_epoch = observed_at.timestamp()
        
        # 5M window: sample around 300s ago (between 240s and 360s)
        s5 = [s for s in self._iv_skew_history if 240.0 <= (now_epoch - s.get("epoch", 0.0)) <= 360.0]
        # 15M window: sample around 900s ago (between 800s and 1000s)
        s15 = [s for s in self._iv_skew_history if 800.0 <= (now_epoch - s.get("epoch", 0.0)) <= 1000.0]
        
        ref5 = s5[-1] if s5 else None
        ref15 = s15[-1] if s15 else None
        
        def _delta(curr: float | None, ref_dict: dict | None, key: str) -> float | None:
            if curr is None or not ref_dict or ref_dict.get(key) is None:
                return None
            return round(curr - ref_dict[key], 2)

        repo_momentum = self.calculate_repo_skew_momentum()

        return {
            "iv_5m_delta": _delta(current_atm_iv, ref5, "atm_iv"),
            "iv_15m_delta": _delta(current_atm_iv, ref15, "atm_iv"),
            "c25_5m_delta": _delta(c25_iv, ref5, "c25_iv"),
            "c25_15m_delta": _delta(c25_iv, ref15, "c25_iv"),
            "p25_5m_delta": _delta(p25_iv, ref5, "p25_iv"),
            "p25_15m_delta": _delta(p25_iv, ref15, "p25_iv"),
            "c10_5m_delta": _delta(c10_iv, ref5, "c10_iv"),
            "c10_15m_delta": _delta(c10_iv, ref15, "c10_iv"),
            "p10_5m_delta": _delta(p10_iv, ref5, "p10_iv"),
            "p10_15m_delta": _delta(p10_iv, ref15, "p10_iv"),
            "skew_5m_delta": _delta(current_skew, ref5, "skew_25d"),
            "skew_15m_delta": _delta(current_skew, ref15, "skew_25d"),
            "skew_10d_5m_delta": _delta(skew_10d, ref5, "skew_10d"),
            "skew_10d_15m_delta": _delta(skew_10d, ref15, "skew_10d"),
            "history_depth_seconds": round(now_epoch - self._iv_skew_history[0].get("epoch", now_epoch), 1),
            "repo_skew_velocity": repo_momentum["repo_skew_velocity"],
            "repo_skew_acceleration": repo_momentum["repo_skew_acceleration"],
            "repo_10d_wing_velocity": repo_momentum["repo_10d_wing_velocity"],
            "repo_wing_confirms": repo_momentum["repo_wing_confirms"],
            "repo_regime": repo_momentum["repo_regime"],
        }

    @staticmethod
    def _calculate_ema(series: list[float], period: int) -> list[float]:
        """Exponential moving average matching upstream 0DTE Momentum Skew Rider."""
        if not series:
            return []
        alpha = 2.0 / (period + 1)
        ema = [series[0]]
        for i in range(1, len(series)):
            ema.append(alpha * series[i] + (1.0 - alpha) * ema[i - 1])
        return ema

    def calculate_repo_skew_momentum(self) -> dict[str, Any]:
        """Compute exact upstream 0DTE Momentum Skew Rider momentum quantities."""
        valid_25d = [
            sample for sample in self._iv_skew_history
            if sample.get("skew_25d") is not None
        ]
        if len(valid_25d) < 5:
            return {
                "repo_skew_velocity": None,
                "repo_skew_acceleration": None,
                "repo_10d_wing_velocity": None,
                "repo_wing_confirms": None,
                "repo_regime": "INSUFFICIENT_HISTORY",
            }
        skew_25d_series = [float(s["skew_25d"]) for s in valid_25d]
        
        fast_25 = self._calculate_ema(skew_25d_series, 3)
        slow_25 = self._calculate_ema(skew_25d_series, 8)
        repo_skew_velocity = round(fast_25[-1] - slow_25[-1], 4)
        
        if len(skew_25d_series) >= 10:
            prior_fast = self._calculate_ema(skew_25d_series[:-3], 3)
            prior_slow = self._calculate_ema(skew_25d_series[:-3], 8)
            prior_vel = prior_fast[-1] - prior_slow[-1]
            repo_skew_acceleration = round(repo_skew_velocity - prior_vel, 4)
        else:
            repo_skew_acceleration = 0.0
            
        paired_wings = [
            sample for sample in self._iv_skew_history
            if sample.get("skew_25d") is not None and sample.get("skew_10d") is not None
        ]
        if len(paired_wings) >= 5:
            paired_25d = [float(s["skew_25d"]) for s in paired_wings]
            skew_10d_series = [float(s["skew_10d"]) for s in paired_wings]
            fast_10 = self._calculate_ema(skew_10d_series, 3)
            slow_10 = self._calculate_ema(skew_10d_series, 8)
            repo_10d_wing_velocity = round(fast_10[-1] - slow_10[-1], 4)
            paired_25_velocity = (
                self._calculate_ema(paired_25d, 3)[-1]
                - self._calculate_ema(paired_25d, 8)[-1]
            )
            wing_confirms = (
                (paired_25_velocity > 0 and repo_10d_wing_velocity > 0)
                or (paired_25_velocity < 0 and repo_10d_wing_velocity < 0)
                or (paired_25_velocity == 0 and repo_10d_wing_velocity == 0)
            )
        else:
            repo_10d_wing_velocity = None
            wing_confirms = None
        
        # Upstream regime classification
        current_25 = skew_25d_series[-1]
        mean_25 = sum(skew_25d_series) / len(skew_25d_series)
        if repo_skew_velocity > 0.03 and current_25 > mean_25:
            regime = "steepening"
        elif repo_skew_velocity < -0.03 and current_25 > mean_25:
            regime = "flattening"
        elif current_25 < 0:
            regime = "inverting"
        else:
            regime = "stable"
            
        return {
            "repo_skew_velocity": repo_skew_velocity,
            "repo_skew_acceleration": repo_skew_acceleration,
            "repo_10d_wing_velocity": repo_10d_wing_velocity,
            "repo_wing_confirms": wing_confirms,
            "repo_regime": regime,
        }

    def evaluate(
        self,
        rows: Sequence[Mapping[str, Any]],
        forward: float | None,
        observed_at: datetime | None,
        chain_expiry: str | None,
    ) -> dict[str, Any]:
        """Evaluate full Option Intelligence profile over the chain ladder."""
        if not rows or forward is None or forward <= 0 or observed_at is None or not chain_expiry:
            return self._unavailable("INPUT_DATA_UNAVAILABLE")

        time_years = self._time_to_expiry_years(chain_expiry, observed_at)
        if time_years is None or time_years <= 0:
            return self._unavailable("EXPIRY_TIME_INVALID")

        ladder_data: list[dict[str, Any]] = []
        call_strikes_for_skew: list[dict[str, Any]] = []
        put_strikes_for_skew: list[dict[str, Any]] = []

        total_call_gex_inr = 0.0
        total_put_gex_inr = 0.0

        atm_strike = round(forward / 50.0) * 50.0
        atm_ce_quality: dict[str, Any] | None = None
        atm_pe_quality: dict[str, Any] | None = None
        atm_iv: float | None = None

        for row in rows:
            strike = row.get("strike")
            if strike is None:
                continue
            strike_val = float(strike)

            ce_leg = row.get("ce") if isinstance(row.get("ce"), Mapping) else (row.get("CE") if isinstance(row.get("CE"), Mapping) else {})
            pe_leg = row.get("pe") if isinstance(row.get("pe"), Mapping) else (row.get("PE") if isinstance(row.get("PE"), Mapping) else {})

            # CE Metrics
            ce_mid = self._clean_mid(ce_leg)
            ce_oi = int(ce_leg.get("oi") or 0)
            ce_iv_raw = ce_leg.get("iv") or ce_leg.get("implied_volatility")
            ce_iv = float(ce_iv_raw) / 100.0 if ce_iv_raw else None
            if ce_iv is None or ce_iv <= 0:
                if ce_mid is not None:
                    ce_iv = solve_iv_bisection(ce_mid, forward, strike_val, time_years, self.rate, "CE")

            ce_greeks = None
            if ce_iv is not None and ce_iv > 0:
                ce_greeks = calculate_bs_greeks(forward, strike_val, time_years, self.rate, ce_iv, "CE")

            # PE Metrics
            pe_mid = self._clean_mid(pe_leg)
            pe_oi = int(pe_leg.get("oi") or 0)
            pe_iv_raw = pe_leg.get("iv") or pe_leg.get("implied_volatility")
            pe_iv = float(pe_iv_raw) / 100.0 if pe_iv_raw else None
            if pe_iv is None or pe_iv <= 0:
                if pe_mid is not None:
                    pe_iv = solve_iv_bisection(pe_mid, forward, strike_val, time_years, self.rate, "PE")

            pe_greeks = None
            if pe_iv is not None and pe_iv > 0:
                pe_greeks = calculate_bs_greeks(forward, strike_val, time_years, self.rate, pe_iv, "PE")

            # GEX Components: OI is already CONTRACT_QUANTITY (total underlying shares).
            # True nominal GEX (₹/point) = Gamma * OI * Spot.
            call_gamma = ce_greeks["gamma"] if ce_greeks else 0.0
            put_gamma = pe_greeks["gamma"] if pe_greeks else 0.0

            call_gex = call_gamma * ce_oi * forward
            put_gex = -put_gamma * pe_oi * forward
            net_gex = call_gex + put_gex

            total_call_gex_inr += call_gex
            total_put_gex_inr += put_gex

            strike_entry = {
                "strike": strike_val,
                "call_gex_cr": round(call_gex / 1e7, 3),
                "put_gex_cr": round(put_gex / 1e7, 3),
                "net_gex_cr": round(net_gex / 1e7, 3),
                "ce_delta": ce_greeks["delta"] if ce_greeks else None,
                "pe_delta": pe_greeks["delta"] if pe_greeks else None,
                "ce_gamma": call_gamma,
                "pe_gamma": put_gamma,
                "ce_theta": ce_greeks["theta"] if ce_greeks else None,
                "pe_theta": pe_greeks["theta"] if pe_greeks else None,
                "ce_iv": round(ce_iv * 100.0, 2) if ce_iv else None,
                "pe_iv": round(pe_iv * 100.0, 2) if pe_iv else None,
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
            }
            ladder_data.append(strike_entry)

            if ce_greeks and ce_iv:
                call_strikes_for_skew.append({
                    "strike": strike_val,
                    "delta": ce_greeks["delta"],
                    "iv": round(ce_iv * 100.0, 2),
                })
            if pe_greeks and pe_iv:
                put_strikes_for_skew.append({
                    "strike": strike_val,
                    "delta": pe_greeks["delta"],
                    "iv": round(pe_iv * 100.0, 2),
                })

            # Check ATM Quality
            if abs(strike_val - atm_strike) < 25.0:
                if ce_iv and pe_iv:
                    atm_iv = round((ce_iv + pe_iv) * 50.0, 2)
                elif ce_iv:
                    atm_iv = round(ce_iv * 100.0, 2)
                elif pe_iv:
                    atm_iv = round(pe_iv * 100.0, 2)

                ce_spread = self._spread(ce_leg)
                pe_spread = self._spread(pe_leg)

                if ce_greeks and ce_spread and ce_spread > 0 and ce_greeks["theta"] != 0:
                    convexity_1pct = 0.5 * call_gamma * ((0.01 * forward) ** 2)
                    ce_ratio = convexity_1pct / (abs(ce_greeks["theta"]) * ce_spread)
                    atm_ce_quality = {
                        "strike": strike_val,
                        "gamma": call_gamma,
                        "theta_daily": ce_greeks["theta"],
                        "spread": ce_spread,
                        "quality_ratio": round(ce_ratio, 2),
                        "rating": "PRIME" if ce_ratio >= 2.0 else ("ACCEPTABLE" if ce_ratio >= 1.0 else "POOR"),
                    }

                if pe_greeks and pe_spread and pe_spread > 0 and pe_greeks["theta"] != 0:
                    convexity_1pct = 0.5 * put_gamma * ((0.01 * forward) ** 2)
                    pe_ratio = convexity_1pct / (abs(pe_greeks["theta"]) * pe_spread)
                    atm_pe_quality = {
                        "strike": strike_val,
                        "gamma": put_gamma,
                        "theta_daily": pe_greeks["theta"],
                        "spread": pe_spread,
                        "quality_ratio": round(pe_ratio, 2),
                        "rating": "PRIME" if pe_ratio >= 2.0 else ("ACCEPTABLE" if pe_ratio >= 1.0 else "POOR"),
                    }

        if not ladder_data:
            return self._unavailable("NO_VALID_STRIKE_DATA")

        # ── 1. GEX Synthesis ──────────────────────────────────────────
        ladder_data.sort(key=lambda s: s["strike"])
        total_net_gex_inr = total_call_gex_inr + total_put_gex_inr
        zero_gamma_strike = self._find_zero_gamma_strike(ladder_data, forward)

        dealer_regime = "LONG_GAMMA_PIN" if total_net_gex_inr >= 0 else "SHORT_GAMMA_AMPLIFY"

        gex_result = {
            "total_net_gex_inr_cr": round(total_net_gex_inr / 1e7, 2),
            "total_call_gex_inr_cr": round(total_call_gex_inr / 1e7, 2),
            "total_put_gex_inr_cr": round(total_put_gex_inr / 1e7, 2),
            "zero_gamma_strike": zero_gamma_strike,
            "spot_distance_to_zero_gamma": round(abs(forward - (zero_gamma_strike or forward)), 2),
            "dealer_regime": dealer_regime,
            "strike_profile": [
                {
                    "strike": s["strike"],
                    "call_gex_cr": s["call_gex_cr"],
                    "put_gex_cr": s["put_gex_cr"],
                    "net_gex_cr": s["net_gex_cr"],
                    "ce_iv": s["ce_iv"],
                    "pe_iv": s["pe_iv"],
                }
                for s in ladder_data
            ],
        }

        # ── 2. IV Skew Synthesis ──────────────────────────────────────
        call_25d = self._closest_delta(call_strikes_for_skew, 0.25)
        put_25d = self._closest_delta(put_strikes_for_skew, -0.25)
        call_10d = self._closest_delta(call_strikes_for_skew, 0.10)
        put_10d = self._closest_delta(put_strikes_for_skew, -0.10)

        skew_25d_spread = round(put_25d["iv"] - call_25d["iv"], 2) if put_25d and call_25d else None
        skew_25d_ratio = round(put_25d["iv"] / max(0.1, call_25d["iv"]), 2) if put_25d and call_25d else None
        skew_10d_spread = round(put_10d["iv"] - call_10d["iv"], 2) if put_10d and call_10d else None

        skew_regime = (
            "PUT_SKEW_ELEVATED" if skew_25d_spread is not None and skew_25d_spread > 1.5
            else ("CALL_SKEW_ELEVATED" if skew_25d_spread is not None and skew_25d_spread < -0.5
                  else ("BALANCED" if skew_25d_spread is not None else "UNAVAILABLE"))
        )

        skew_result = {
            "skew_25d_spread": skew_25d_spread,
            "skew_25d_ratio": skew_25d_ratio,
            "skew_10d_spread": skew_10d_spread,
            "call_25d": call_25d,
            "put_25d": put_25d,
            "call_10d": call_10d,
            "put_10d": put_10d,
            "skew_regime": skew_regime,
        }

        # ── 3. Gamma/Theta Quality ────────────────────────────────────
        quality_result = {
            "atm_ce": atm_ce_quality,
            "atm_pe": atm_pe_quality,
        }

        # ── 4. Volatility Opportunity & HAR-RV ───────────────────────
        self.record_spot_price(forward, observed_at)
        intraday_rv = self.calculate_intraday_rv()
        har_forecast = self.calculate_har_rv_forecast(intraday_rv)

        effective_atm_iv = atm_iv or (call_25d["iv"] if call_25d else None)
        c25_val = call_25d["iv"] if call_25d else None
        p25_val = put_25d["iv"] if put_25d else None
        c10_val = call_10d["iv"] if call_10d else None
        p10_val = put_10d["iv"] if put_10d else None

        self.record_iv_skew(
            effective_atm_iv,
            skew_25d_spread,
            observed_at,
            c25_iv=c25_val,
            p25_iv=p25_val,
            c10_iv=c10_val,
            p10_iv=p10_val,
            skew_10d=skew_10d_spread,
        )
        iv_skew_velocities = self.calculate_iv_skew_velocities(
            effective_atm_iv,
            skew_25d_spread,
            observed_at,
            c25_iv=c25_val,
            p25_iv=p25_val,
            c10_iv=c10_val,
            p10_iv=p10_val,
            skew_10d=skew_10d_spread,
        )

        if effective_atm_iv is not None and har_forecast and har_forecast.get("forecast_annualized") is not None:
            iv_rv_spread = round(effective_atm_iv - har_forecast["forecast_annualized"], 2)
            vol_regime = (
                "OVERPRICED_PREMIUM" if iv_rv_spread > 2.0
                else ("UNDERPRICED_PREMIUM" if iv_rv_spread < -1.0 else "FAIR")
            )
        else:
            iv_rv_spread = None
            vol_regime = "STANDBY"

        vol_opportunity = {
            "atm_iv": effective_atm_iv,
            "intraday_rv_annualized": intraday_rv,
            "har_rv_forecast_annualized": har_forecast["forecast_annualized"] if har_forecast else None,
            "iv_rv_spread": iv_rv_spread,
            "vol_premium_regime": vol_regime,
            "velocities": iv_skew_velocities,
            "har_components": {
                "daily_rv": har_forecast["daily_component"] if har_forecast else None,
                "weekly_rv": har_forecast["weekly_component"] if har_forecast else None,
                "monthly_rv": har_forecast["monthly_component"] if har_forecast else None,
            } if har_forecast else None,
        }

        skew_result["velocities"] = iv_skew_velocities

        return {
            "schema_version": "1.0.0",
            "status": "LIVE",
            "generated_at": observed_at.isoformat(),
            "forward": forward,
            "atm_strike": atm_strike,
            "time_to_expiry_years": round(time_years, 5),
            "gex": gex_result,
            "iv_skew": skew_result,
            "gamma_theta_quality": quality_result,
            "volatility_opportunity": vol_opportunity,
        }

    @staticmethod
    def _clean_mid(leg: Mapping[str, Any]) -> float | None:
        bid = leg.get("top_bid_price") or leg.get("bid")
        ask = leg.get("top_ask_price") or leg.get("ask")
        ltp = leg.get("last_price") or leg.get("ltp")
        try:
            bid_f = float(bid) if bid is not None else None
            ask_f = float(ask) if ask is not None else None
            if bid_f is not None and ask_f is not None and 0.0 < bid_f <= ask_f:
                return (bid_f + ask_f) / 2.0
            if ltp is not None and float(ltp) > 0:
                return float(ltp)
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _spread(leg: Mapping[str, Any]) -> float | None:
        bid = leg.get("top_bid_price") or leg.get("bid")
        ask = leg.get("top_ask_price") or leg.get("ask")
        try:
            if bid is not None and ask is not None:
                b_f, a_f = float(bid), float(ask)
                if 0 < b_f <= a_f:
                    return round(a_f - b_f, 2)
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _time_to_expiry_years(expiry: str, observed_at: datetime) -> float | None:
        try:
            close_dt = datetime.fromisoformat(str(expiry)).replace(
                tzinfo=IST, hour=15, minute=30, second=0, microsecond=0
            )
            seconds = (close_dt - observed_at).total_seconds()
            return seconds / (365.0 * 24.0 * 60.0 * 60.0) if seconds > 0 else 0.0001
        except Exception:
            return None

    @staticmethod
    def _find_zero_gamma_strike(strikes: list[dict[str, Any]], spot: float) -> float | None:
        if not strikes:
            return None
        for i in range(len(strikes) - 1):
            g1 = strikes[i]["net_gex_cr"]
            g2 = strikes[i + 1]["net_gex_cr"]
            if g1 * g2 <= 0 and (g1 != 0 or g2 != 0):
                k1 = strikes[i]["strike"]
                k2 = strikes[i + 1]["strike"]
                if g1 == g2:
                    return k1
                ratio = abs(g1) / (abs(g1) + abs(g2))
                return round(k1 + ratio * (k2 - k1), 1)
        min_strike = min(strikes, key=lambda s: abs(s["net_gex_cr"]))
        return min_strike["strike"]

    @staticmethod
    def _closest_delta(strikes: list[dict[str, Any]], target_delta: float) -> dict[str, Any] | None:
        if not strikes:
            return None
        return min(strikes, key=lambda s: abs(s["delta"] - target_delta))

    @staticmethod
    def _unavailable(reason: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "status": "UNAVAILABLE",
            "reason": reason,
            "gex": None,
            "iv_skew": None,
            "gamma_theta_quality": None,
            "volatility_opportunity": None,
        }
