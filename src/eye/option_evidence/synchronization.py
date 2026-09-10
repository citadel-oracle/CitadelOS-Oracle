"""Quote-Underlying Time Synchronization & Bitemporal Watermarking for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple
from src.eye.option_evidence.contracts import OptionMarketObservation


@dataclass(frozen=True)
class SynchronizedEvidencePair:
    option_observation: OptionMarketObservation
    underlying_price: float
    underlying_timestamp: datetime
    synchronization_latency_seconds: float
    is_watermark_compliant: bool


def synchronize_option_and_underlying(
    option_obs: OptionMarketObservation,
    underlying_ticks: List[Tuple[datetime, float]],
    watermark: datetime,
    max_latency_seconds: float = 60.0,
) -> Optional[SynchronizedEvidencePair]:
    """Align option market observation with latest underlying price at or before watermark."""
    # 1. Enforce No-Look-Ahead: option observation must be <= watermark
    if option_obs.available_at > watermark or option_obs.observed_at > watermark:
        return None

    # 2. Find latest underlying price at or before watermark
    valid_u = [u for u in underlying_ticks if u[0] <= watermark]
    if not valid_u:
        return None

    latest_u = max(valid_u, key=lambda x: x[0])
    u_time, u_price = latest_u

    latency = abs((option_obs.observed_at - u_time).total_seconds())

    return SynchronizedEvidencePair(
        option_observation=option_obs,
        underlying_price=u_price,
        underlying_timestamp=u_time,
        synchronization_latency_seconds=round(latency, 3),
        is_watermark_compliant=(latency <= max_latency_seconds),
    )
