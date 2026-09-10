"""Detector Bar, BarUpdate, and DetectorContext Input Models for Eye Engine E2B."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from src.eye.contracts import PriceAtom, InstrumentIdentity, _check_tz, EyeContractError


@dataclass(frozen=True, kw_only=True, slots=True)
class DetectorBar:
    instrument_key: str
    timeframe: str
    open_time: datetime
    expected_close_time: datetime
    available_at: datetime
    bar_key: str
    open: PriceAtom
    high: PriceAtom
    low: PriceAtom
    close: PriceAtom
    is_closed: bool
    volume: Optional[int] = None
    actual_close_time: Optional[datetime] = None
    source_name: str = "DHAN"

    def __post_init__(self) -> None:
        _check_tz(self.open_time, "open_time")
        _check_tz(self.expected_close_time, "expected_close_time")
        _check_tz(self.available_at, "available_at")
        if self.actual_close_time:
            _check_tz(self.actual_close_time, "actual_close_time")
        if self.low.ticks > self.high.ticks:
            raise EyeContractError("Low price cannot exceed high price in DetectorBar")
        if not (self.low.ticks <= self.open.ticks <= self.high.ticks):
            raise EyeContractError("Open price must be bounded by low and high price in DetectorBar")
        if not (self.low.ticks <= self.close.ticks <= self.high.ticks):
            raise EyeContractError("Close price must be bounded by low and high price in DetectorBar")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_key": self.instrument_key,
            "timeframe": self.timeframe,
            "open_time": self.open_time.astimezone(timezone.utc).isoformat(),
            "expected_close_time": self.expected_close_time.astimezone(timezone.utc).isoformat(),
            "actual_close_time": self.actual_close_time.astimezone(timezone.utc).isoformat() if self.actual_close_time else None,
            "available_at": self.available_at.astimezone(timezone.utc).isoformat(),
            "bar_key": self.bar_key,
            "open": self.open.to_dict(),
            "high": self.high.to_dict(),
            "low": self.low.to_dict(),
            "close": self.close.to_dict(),
            "is_closed": self.is_closed,
            "volume": self.volume,
            "source_name": self.source_name,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class BarUpdate:
    target_bar_key: str
    update_sequence: int
    update_time: datetime
    high_so_far: PriceAtom
    low_so_far: PriceAtom
    close_so_far: PriceAtom
    is_final: bool = False
    volume_so_far: Optional[int] = None

    def __post_init__(self) -> None:
        _check_tz(self.update_time, "update_time")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_bar_key": self.target_bar_key,
            "update_sequence": self.update_sequence,
            "update_time": self.update_time.astimezone(timezone.utc).isoformat(),
            "high_so_far": self.high_so_far.to_dict(),
            "low_so_far": self.low_so_far.to_dict(),
            "close_so_far": self.close_so_far.to_dict(),
            "is_final": self.is_final,
            "volume_so_far": self.volume_so_far,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class DetectorContext:
    instrument: InstrumentIdentity
    timeframe: str
    as_of: datetime
    producer_version: str = "1.0.0"
    source_revision: str = "8632791"

    def __post_init__(self) -> None:
        _check_tz(self.as_of, "as_of")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument.to_dict(),
            "timeframe": self.timeframe,
            "as_of": self.as_of.astimezone(timezone.utc).isoformat(),
            "producer_version": self.producer_version,
            "source_revision": self.source_revision,
        }
