"""Time-to-Expiry Calculation Conventions for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import datetime, date, timezone
from typing import Optional


@dataclass(frozen=True)
class TimeToExpiryResult:
    calendar_seconds: float
    calendar_days: float
    years_act_365: float
    years_trading_252: float
    trading_minutes_remaining: Optional[float]
    expiry_state: str  # ACTIVE, EXPIRY_DAY, EXPIRED


def calculate_time_to_expiry(
    observation_time: datetime,
    expiry_timestamp: datetime,
    trading_minutes_per_day: float = 375.0,  # 09:15 to 15:30 IST = 6.25 hrs = 375 mins
) -> TimeToExpiryResult:
    """Calculate exact time-to-expiry using ACT/365 and TRADING/252 conventions."""
    diff_sec = (expiry_timestamp - observation_time).total_seconds()

    if diff_sec <= 0:
        return TimeToExpiryResult(
            calendar_seconds=0.0,
            calendar_days=0.0,
            years_act_365=0.0,
            years_trading_252=0.0,
            trading_minutes_remaining=0.0,
            expiry_state="EXPIRED",
        )

    cal_days = diff_sec / 86400.0
    years_act_365 = cal_days / 365.0
    years_trading_252 = cal_days / 252.0

    state = "ACTIVE"
    if observation_time.date() == expiry_timestamp.date():
        state = "EXPIRY_DAY"

    return TimeToExpiryResult(
        calendar_seconds=diff_sec,
        calendar_days=round(cal_days, 6),
        years_act_365=round(years_act_365, 8),
        years_trading_252=round(years_trading_252, 8),
        trading_minutes_remaining=round(diff_sec / 60.0, 2),
        expiry_state=state,
    )
