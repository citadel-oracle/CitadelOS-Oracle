"""Canonical Dhan exchange-time normalization.

Dhan Full packets can carry an implausible epoch-shaped LTT. Raw evidence is
always retained. For genuine live packets, the trusted receive clock owns
transport/session validity and event ordering whenever raw LTT is implausible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
_RAW_LTT_PLAUSIBILITY_SECONDS = 30


@dataclass(frozen=True, slots=True)
class DhanLtt:
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


def normalize_dhan_ltt(raw_epoch: int, receive_wall_utc: str | datetime | None = None) -> DhanLtt:
    """Preserve raw LTT and fail over to receive time without fixed offsets."""
    raw_epoch = int(raw_epoch)
    if raw_epoch <= 0:
        raise ValueError("DHAN_LTT_EPOCH_INVALID")
    raw_utc = datetime.fromtimestamp(raw_epoch, tz=timezone.utc)
    raw_ist = raw_utc.astimezone(IST)
    receive_utc = _receive_time(receive_wall_utc)
    receive_ist = receive_utc.astimezone(IST) if receive_utc is not None else None
    raw_skew_seconds = (
        (raw_utc - receive_utc).total_seconds()
        if receive_utc is not None
        else None
    )
    raw_ltt_suspicious = bool(
        raw_skew_seconds is not None
        and abs(raw_skew_seconds) > _RAW_LTT_PLAUSIBILITY_SECONDS
    )
    receive_time_substituted = raw_ltt_suspicious and receive_utc is not None
    normalized_epoch = int(receive_utc.timestamp()) if receive_time_substituted else raw_epoch
    utc = receive_utc if receive_time_substituted else raw_utc
    ist = utc.astimezone(IST)
    normalized_skew_seconds = (
        (utc - receive_utc).total_seconds() if receive_utc is not None else None
    )
    # Transport validity is owned by the trusted local receive clock.  Trade
    # event semantics remain owned by the normalized exchange LTT.
    transport_accepted = _is_regular_session(receive_ist or ist)
    event_accepted = _is_regular_session(ist)
    return DhanLtt(
        raw_epoch=raw_epoch,
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
    )


def _is_regular_session(value: datetime) -> bool:
    minute = value.hour * 60 + value.minute
    return value.weekday() < 5 and 9 * 60 + 15 <= minute < 15 * 60 + 30


def _receive_time(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("DHAN_RECEIVE_TIME_NAIVE")
    return parsed.astimezone(timezone.utc)
