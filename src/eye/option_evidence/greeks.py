"""Greeks Provenance & Independent Parity Calculation for Eye Engine Phase E4A."""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from src.eye.option_evidence.contracts import GreekObservation, GreekType, GreekSource, PriceReference


@dataclass(frozen=True)
class RegulatoryFutEqResult:
    delta_adjusted_quantity: float
    underlying_units: float
    inr_notional_exposure: Optional[float]
    classification: str = "REGULATORY_DELTA_INPUT_ONLY"
    compliance_claim_made: bool = False


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def calculate_black_scholes_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str,  # CE or PE
    dividend_yield: float = 0.0,
) -> Dict[GreekType, float]:
    """Calculate analytical Black-Scholes Greeks."""
    if spot <= 0 or strike <= 0 or time_to_expiry_years <= 0 or volatility <= 0:
        return {}

    S = spot
    K = strike
    T = time_to_expiry_years
    r = risk_free_rate
    sigma = volatility
    q = dividend_yield

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    opt_type = option_type.upper()

    if opt_type == "CE":
        delta = math.exp(-q * T) * norm_cdf(d1)
        theta = (- (S * sigma * math.exp(-q * T) * norm_pdf(d1)) / (2.0 * sqrt_T)
                 - r * K * math.exp(-r * T) * norm_cdf(d2)
                 + q * S * math.exp(-q * T) * norm_cdf(d1)) / 365.0
    else:  # PE
        delta = -math.exp(-q * T) * norm_cdf(-d1)
        theta = (- (S * sigma * math.exp(-q * T) * norm_pdf(d1)) / (2.0 * sqrt_T)
                 + r * K * math.exp(-r * T) * norm_cdf(-d2)
                 - q * S * math.exp(-q * T) * norm_cdf(-d1)) / 365.0

    gamma = (math.exp(-q * T) * norm_pdf(d1)) / (S * sigma * sqrt_T)
    vega = (S * math.exp(-q * T) * norm_pdf(d1) * sqrt_T) / 100.0  # Vega per 1% change in vol

    return {
        GreekType.DELTA: round(delta, 6),
        GreekType.GAMMA: round(gamma, 8),
        GreekType.THETA: round(theta, 6),
        GreekType.VEGA: round(vega, 6),
    }


def calculate_regulatory_futeq_delta(
    option_quantity: int,
    delta: float,
    underlying_price: Optional[float] = None,
) -> RegulatoryFutEqResult:
    """Calculate regulatory delta input (option_quantity * delta) with explicit classification."""
    adj_qty = option_quantity * delta
    inr_val = round(adj_qty * underlying_price, 2) if underlying_price is not None else None
    return RegulatoryFutEqResult(
        delta_adjusted_quantity=round(adj_qty, 4),
        underlying_units=round(adj_qty, 4),
        inr_notional_exposure=inr_val,
        classification="REGULATORY_DELTA_INPUT_ONLY",
        compliance_claim_made=False,
    )
