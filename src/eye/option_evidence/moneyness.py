"""Moneyness Classifier & Intrinsic/Time Decomposition for Eye Engine Phase E4A."""

from dataclasses import dataclass
from typing import Optional
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.contracts import MoneynessState, OptionContractIdentity


@dataclass(frozen=True)
class MoneynessResult:
    moneyness_state: MoneynessState
    underlying_price: float
    strike_price: float
    absolute_distance_points: float
    strike_interval_distance: float
    intrinsic_value: float
    time_value: Optional[float]


def classify_moneyness(
    contract: OptionContractIdentity,
    underlying_price: float,
    option_price: Optional[float] = None,
    strike_interval: float = 50.0,
    atm_tolerance_points: float = 25.0,
) -> MoneynessResult:
    """Classify moneyness (ITM, ATM, OTM) and decompose intrinsic vs time value."""
    if underlying_price <= 0:
        return MoneynessResult(
            moneyness_state=MoneynessState.UNKNOWN, underlying_price=underlying_price,
            strike_price=contract.strike.ticks / 100.0, absolute_distance_points=0.0,
            strike_interval_distance=0.0, intrinsic_value=0.0, time_value=None,
        )

    K = contract.strike.ticks / 100.0
    S = underlying_price
    dist_pts = abs(S - K)
    dist_intervals = dist_pts / strike_interval if strike_interval > 0 else 0.0

    opt_type = contract.option_type.upper()

    # Calculate intrinsic value
    if opt_type == "CE":
        intrinsic = max(0.0, S - K)
        if dist_pts <= atm_tolerance_points:
            m_state = MoneynessState.ATM
        elif S > K + atm_tolerance_points:
            m_state = MoneynessState.ITM
        else:
            m_state = MoneynessState.OTM
    else:  # PE
        intrinsic = max(0.0, K - S)
        if dist_pts <= atm_tolerance_points:
            m_state = MoneynessState.ATM
        elif S < K - atm_tolerance_points:
            m_state = MoneynessState.ITM
        else:
            m_state = MoneynessState.OTM

    time_val = None
    if option_price is not None and option_price >= 0:
        time_val = max(0.0, option_price - intrinsic)

    return MoneynessResult(
        moneyness_state=m_state,
        underlying_price=round(S, 2),
        strike_price=K,
        absolute_distance_points=round(dist_pts, 2),
        strike_interval_distance=round(dist_intervals, 2),
        intrinsic_value=round(intrinsic, 2),
        time_value=round(time_val, 2) if time_val is not None else None,
    )
