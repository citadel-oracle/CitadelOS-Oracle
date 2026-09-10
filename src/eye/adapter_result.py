"""Adapter Result, Abstention, and Diagnostics Models for Eye Engine E2A."""

from __future__ import annotations

from dataclasses import dataclass, fields, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple

from src.eye.contracts import EyeEventRecord, InstrumentIdentity, SCHEMA_VERSION, _check_tz
from src.eye.serialization import canonical_json


class AdapterAbstentionReason(str, Enum):
    NATIVE_OUTPUT_UNAVAILABLE = "NATIVE_OUTPUT_UNAVAILABLE"
    INSUFFICIENT_WARMUP = "INSUFFICIENT_WARMUP"
    SOURCE_BAR_LINEAGE_MISSING = "SOURCE_BAR_LINEAGE_MISSING"
    AMBIGUOUS_EVENT_TIME = "AMBIGUOUS_EVENT_TIME"
    AMBIGUOUS_PRICE_GEOMETRY = "AMBIGUOUS_PRICE_GEOMETRY"
    AMBIGUOUS_RULE_VARIANT = "AMBIGUOUS_RULE_VARIANT"
    FORMING_BAR_NOT_REPRODUCIBLE = "FORMING_BAR_NOT_REPRODUCIBLE"
    IDENTITY_CONTEXT_MISSING = "IDENTITY_CONTEXT_MISSING"
    TIMEFRAME_CONTEXT_MISSING = "TIMEFRAME_CONTEXT_MISSING"
    UNSUPPORTED_NATIVE_EVENT = "UNSUPPORTED_NATIVE_EVENT"
    INVALID_NATIVE_OUTPUT = "INVALID_NATIVE_OUTPUT"
    FUTURE_DEPENDENCY_UNRESOLVED = "FUTURE_DEPENDENCY_UNRESOLVED"
    EXACT_PRICE_CONVERSION_FAILED = "EXACT_PRICE_CONVERSION_FAILED"


@dataclass(frozen=True, kw_only=True, slots=True)
class AdapterAbstention:
    code: AdapterAbstentionReason
    reason: str
    native_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "reason": self.reason,
            "native_context": self.native_context,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class AdapterDiagnostics:
    original_native_value: str
    quantized_ticks: int
    quantum: str
    rounding_delta: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_native_value": self.original_native_value,
            "quantized_ticks": self.quantized_ticks,
            "quantum": self.quantum,
            "rounding_delta": self.rounding_delta,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class AdapterResult:
    producer: str
    producer_version: str
    input_identity: InstrumentIdentity
    timeframe: str
    evaluation_as_of: datetime
    records: Tuple[EyeEventRecord, ...] = field(default_factory=tuple)
    abstentions: Tuple[AdapterAbstention, ...] = field(default_factory=tuple)
    diagnostics: Tuple[AdapterDiagnostics, ...] = field(default_factory=tuple)
    source_revision: str = ""
    configuration_fingerprint: str = ""
    native_output_fingerprint: str = ""
    adapter_version: str = "0.1.0"
    completed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        _check_tz(self.evaluation_as_of, "evaluation_as_of")
        if self.completed_at:
            _check_tz(self.completed_at, "completed_at")
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "abstentions", tuple(self.abstentions))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer": self.producer,
            "producer_version": self.producer_version,
            "input_identity": self.input_identity.to_dict(),
            "timeframe": self.timeframe,
            "evaluation_as_of": self.evaluation_as_of.astimezone(timezone.utc).isoformat(),
            "records": [r.to_dict() for r in self.records],
            "abstentions": [a.to_dict() for a in self.abstentions],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "source_revision": self.source_revision,
            "configuration_fingerprint": self.configuration_fingerprint,
            "native_output_fingerprint": self.native_output_fingerprint,
            "adapter_version": self.adapter_version,
            "completed_at": self.completed_at.astimezone(timezone.utc).isoformat() if self.completed_at else None,
        }
