"""Detector Result and Abstention Models for Eye Engine E2B."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Sequence, Tuple

from src.eye.contracts import EyeEventRecord, InstrumentIdentity, _check_tz


class DetectorAbstentionReason(str, Enum):
    INSUFFICIENT_BARS = "INSUFFICIENT_BARS"
    INCOMPLETE_BAR = "INCOMPLETE_BAR"
    INCOMPLETE_HIGHER_TIMEFRAME = "INCOMPLETE_HIGHER_TIMEFRAME"
    MISSING_CONSTITUENT_BAR = "MISSING_CONSTITUENT_BAR"
    DUPLICATE_BAR = "DUPLICATE_BAR"
    OUT_OF_ORDER_BAR = "OUT_OF_ORDER_BAR"
    INVALID_PRICE = "INVALID_PRICE"
    PRICE_QUANTUM_MISSING = "PRICE_QUANTUM_MISSING"
    INTRABAR_SEQUENCE_UNAVAILABLE = "INTRABAR_SEQUENCE_UNAVAILABLE"
    STRUCTURAL_STATE_UNDEFINED = "STRUCTURAL_STATE_UNDEFINED"
    SWING_NOT_CONFIRMED = "SWING_NOT_CONFIRMED"
    LIQUIDITY_POOL_NOT_CONFIRMED = "LIQUIDITY_POOL_NOT_CONFIRMED"
    RECLAIM_PENDING = "RECLAIM_PENDING"
    RECLAIM_TIMEOUT = "RECLAIM_TIMEOUT"
    RULE_VARIANT_UNRESOLVED = "RULE_VARIANT_UNRESOLVED"
    REQUIRED_FEATURE_UNAVAILABLE = "REQUIRED_FEATURE_UNAVAILABLE"
    SESSION_CONTEXT_UNAVAILABLE = "SESSION_CONTEXT_UNAVAILABLE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


@dataclass(frozen=True, kw_only=True, slots=True)
class DetectorAbstention:
    code: DetectorAbstentionReason
    reason: str
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "reason": self.reason,
            "context": self.context,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class DetectorResult:
    detector_family: str
    rule_id: str
    rule_version: str
    instrument: InstrumentIdentity
    timeframe: str
    as_of: datetime
    records: Tuple[EyeEventRecord, ...] = field(default_factory=tuple)
    abstentions: Tuple[DetectorAbstention, ...] = field(default_factory=tuple)
    completed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        _check_tz(self.as_of, "as_of")
        if self.completed_at:
            _check_tz(self.completed_at, "completed_at")
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "abstentions", tuple(self.abstentions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_family": self.detector_family,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "instrument": self.instrument.to_dict(),
            "timeframe": self.timeframe,
            "as_of": self.as_of.astimezone(timezone.utc).isoformat(),
            "records": [r.to_dict() for r in self.records],
            "abstentions": [a.to_dict() for a in self.abstentions],
            "completed_at": self.completed_at.astimezone(timezone.utc).isoformat() if self.completed_at else None,
        }
