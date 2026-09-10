"""Canonical Provider-Neutral Exchange Time Normalization.

Preserves raw exchange timestamps and normalizes across providers (Dhan, Upstox)
with automatic millisecond/second detection, segment-aware session bounds
(Spot: 09:15-15:30 IST; F&O: 09:15-15:40 IST), and receive clock fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
_DEFAULT_PLAUSIBILITY_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class ExchangeLtt:
    raw_epoch: int
    raw_utc: datetime
    raw_ist: datetime
    normalized_epoch: int
    utc: datetime
    ist: datetime
    receive_utc: datetime | None
    receive_ist: datetime | None
    raw_receive_skew_ms: float | None
    receive_skew_ms: float | None
    raw_ltt_suspicious: bool
    receive_time_substituted: bool
    session_accepted: bool
    event_session_accepted: bool
    segment: str = "IDX_I"
    provider: str = "GENERIC"


def is_exchange_session(value: datetime, segment: str = "IDX_I") -> bool:
    """Checks whether the given IST datetime falls within exchange trading bounds."""
    if value.weekday() >= 5:  # Weekend
        return False
    minute = value.hour * 60 + value.minute
    open_min = 9 * 60 + 15  # 09:15 IST

    # Current NSE Equity Derivatives normal market session trades through 15:40 IST
    if segment in ("NSE_FNO", "NSE_FO", "FUTIDX", "OPTIDX", "NSE_FUT"):
        close_min = 15 * 60 + 40  # 15:40 IST
    else:
        close_min = 15 * 60 + 30  # 15:30 IST (Spot / Cash Equity)

    return open_min <= minute < close_min


def _parse_receive_time(value: Union[str, datetime, None]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("RECEIVE_TIME_NAIVE")
    return parsed.astimezone(timezone.utc)


def normalize_exchange_ltt(
    raw_epoch: Union[int, float],
    receive_wall_utc: Union[str, datetime, None] = None,
    segment: str = "IDX_I",
    provider: str = "GENERIC",
    plausibility_seconds: float = _DEFAULT_PLAUSIBILITY_SECONDS,
) -> ExchangeLtt:
    """Normalizes raw exchange LTT with millisecond auto-detection and segment bounds."""
    raw_val = float(raw_epoch)
    if raw_val <= 0:
        raise ValueError("EXCHANGE_LTT_EPOCH_INVALID")

    # Auto-detect millisecond timestamp (> 1e11)
    if raw_val > 1e11:
        raw_val = raw_val / 1000.0

    raw_sec = int(raw_val)
    raw_utc = datetime.fromtimestamp(raw_sec, tz=timezone.utc)
    raw_ist = raw_utc.astimezone(IST)

    receive_utc = _parse_receive_time(receive_wall_utc)
    receive_ist = receive_utc.astimezone(IST) if receive_utc is not None else None

    raw_skew_seconds = (raw_utc - receive_utc).total_seconds() if receive_utc is not None else None

    raw_ltt_suspicious = bool(
        raw_skew_seconds is not None and abs(raw_skew_seconds) > plausibility_seconds
    )
    receive_time_substituted = raw_ltt_suspicious and receive_utc is not None
    normalized_epoch = int(receive_utc.timestamp()) if receive_time_substituted else raw_sec
    utc = receive_utc if receive_time_substituted else raw_utc
    ist = utc.astimezone(IST)

    normalized_skew_seconds = (utc - receive_utc).total_seconds() if receive_utc is not None else None

    transport_accepted = is_exchange_session(receive_ist or ist, segment=segment)
    event_accepted = is_exchange_session(ist, segment=segment)

    return ExchangeLtt(
        raw_epoch=raw_sec,
        raw_utc=raw_utc,
        raw_ist=raw_ist,
        normalized_epoch=normalized_epoch,
        utc=utc,
        ist=ist,
        receive_utc=receive_utc,
        receive_ist=receive_ist,
        raw_receive_skew_ms=round(raw_skew_seconds * 1000.0, 3) if raw_skew_seconds is not None else None,
        receive_skew_ms=round(normalized_skew_seconds * 1000.0, 3) if normalized_skew_seconds is not None else None,
        raw_ltt_suspicious=raw_ltt_suspicious,
        receive_time_substituted=receive_time_substituted,
        session_accepted=transport_accepted,
        event_session_accepted=event_accepted,
        segment=segment,
        provider=provider,
    )


def normalize_upstox_ltt(
    raw_epoch: Union[int, float],
    receive_wall_utc: Union[str, datetime, None] = None,
    segment: str = "IDX_I",
) -> ExchangeLtt:
    """Normalizes Upstox exchange LTT with high-tolerance plausibility and segment bounds."""
    # Upstox timestamps are high-accuracy exchange milliseconds, with 300s clock-drift tolerance
    return normalize_exchange_ltt(
        raw_epoch=raw_epoch,
        receive_wall_utc=receive_wall_utc,
        segment=segment,
        provider="UPSTOX",
        plausibility_seconds=300.0,
    )
