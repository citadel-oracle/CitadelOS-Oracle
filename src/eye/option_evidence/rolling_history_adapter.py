"""Rolling ATM Proxy Adapter & Boundary Isolation for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from src.eye.option_evidence.sources import SourceType, DataClassification, SourceProvenance


@dataclass(frozen=True)
class RollingProxySeriesKey:
    underlying_symbol: str
    expiry_horizon: str  # e.g., "NEAR", "NEXT", "WEEKLY"
    moneyness_label: str  # e.g., "ATM", "ATM+1", "ITM1"
    option_type: str  # CE or PE
    series_key: str


def generate_rolling_series_key(
    underlying_symbol: str,
    expiry_horizon: str,
    moneyness_label: str,
    option_type: str,
) -> RollingProxySeriesKey:
    """Generate rolling series key separate from exact OptionContractIdentity."""
    s_key = (
        f"ROLLING:{underlying_symbol.upper()}:{expiry_horizon.upper()}:"
        f"{moneyness_label.upper()}:{option_type.upper()}"
    )
    return RollingProxySeriesKey(
        underlying_symbol=underlying_symbol.upper(),
        expiry_horizon=expiry_horizon.upper(),
        moneyness_label=moneyness_label.upper(),
        option_type=option_type.upper(),
        series_key=s_key,
    )


@dataclass(frozen=True)
class RollingProxyObservation:
    series_key: RollingProxySeriesKey
    provenance: SourceProvenance
    timestamp: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: Optional[int]
    open_interest: Optional[int]
    resolved_actual_strike: Optional[float]
    contract_transition_flag: bool = False
