"""Official Market Status Evaluation Engine for Citadel Eye Engine Option Capture."""

from enum import Enum
from typing import Optional
from datetime import datetime, date, time
import dateutil.tz


class MarketStatus(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    CLOSED_AFTER_SESSION = "CLOSED_AFTER_SESSION"
    WEEKEND = "WEEKEND"
    OFFICIAL_HOLIDAY = "OFFICIAL_HOLIDAY"
    SPECIAL_SESSION = "SPECIAL_SESSION"
    EXCHANGE_OUTAGE = "EXCHANGE_OUTAGE"
    DATA_PROVIDER_UNAVAILABLE = "DATA_PROVIDER_UNAVAILABLE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    UNKNOWN = "UNKNOWN"


# Official NSE 2026 F&O Holiday List (ISO YYYY-MM-DD)
NSE_FO_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-03-26",  # Shri Ram Navami
    "2026-03-31",  # Mahavir Jayanti
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-28",  # Bakri Id
    "2026-06-26",  # Muharram
    "2026-08-15",  # Independence Day
    "2026-09-15",  # Milad-un-Nabi
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-10",  # Diwali Balipratipada
    "2026-11-24",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
}


def evaluate_market_status(dt: Optional[datetime] = None) -> MarketStatus:
    """Evaluates the official NSE Equity Derivatives market status at datetime `dt` (defaults to now in Asia/Kolkata)."""
    tz_ist = dateutil.tz.gettz("Asia/Kolkata")
    if dt is None:
        dt = datetime.now(tz_ist)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz_ist)
    else:
        dt = dt.astimezone(tz_ist)

    curr_date_str = dt.strftime("%Y-%m-%d")

    # 1. Official Holiday Check
    if curr_date_str in NSE_FO_HOLIDAYS_2026:
        return MarketStatus.OFFICIAL_HOLIDAY

    # 2. Weekend Check (Saturday=5, Sunday=6)
    if dt.weekday() in (5, 6):
        return MarketStatus.WEEKEND

    # 3. Session Timing Check (IST)
    curr_time = dt.time()
    t_pre_open = time(9, 0)
    t_open = time(9, 15)
    t_close = time(15, 30)

    if t_pre_open <= curr_time < t_open:
        return MarketStatus.PRE_OPEN
    elif t_open <= curr_time <= t_close:
        return MarketStatus.OPEN
    else:
        return MarketStatus.CLOSED_AFTER_SESSION
