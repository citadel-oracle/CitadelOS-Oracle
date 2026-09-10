"""Versioned, immutable and content-addressed Oracle perception contracts.

These records are advisory-only.  They deliberately contain no decision, risk,
quantity, order, position or execution fields.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "2.0.0"
SUPPORTED_TIMEFRAMES = ("1D", "4H", "1H", "15m", "5m", "3m", "1m")


class ContractValidationError(ValueError):
    pass


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    HISTORICAL = "HISTORICAL"
    UNAVAILABLE = "UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class CompletionStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL_SESSION_BAR = "PARTIAL_SESSION_BAR"
    FORMING = "FORMING"


def _aware(value: str | datetime, field: str) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ContractValidationError(f"{field} must be ISO-8601") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ContractValidationError(f"{field} must be timezone-aware")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True, kw_only=True)
class PerceptionRecord:
    correlation_id: str
    instrument_id: str
    symbol: str
    timeframe: str
    source_timestamp: str
    generated_at: str
    as_of: str
    availability: Availability
    freshness_state: FreshnessState
    source_ids: Mapping[str, str]
    dependency_versions: Mapping[str, str]
    completion_status: CompletionStatus
    provenance: Mapping[str, Any]
    content_hash: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("correlation_id", "instrument_id", "symbol", "timeframe"):
            if not str(getattr(self, name)).strip():
                raise ContractValidationError(f"{name} is required")
        if self.timeframe not in (*SUPPORTED_TIMEFRAMES, "MULTI"):
            raise ContractValidationError("unsupported timeframe")
        source = _aware(self.source_timestamp, "source_timestamp")
        generated = _aware(self.generated_at, "generated_at")
        as_of = _aware(self.as_of, "as_of")
        if source > generated or as_of > generated:
            raise ContractValidationError("future source/as_of timestamp")
        if not self.source_ids or not self.dependency_versions or not self.provenance:
            raise ContractValidationError("lineage metadata is required")
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "source_ids", _freeze(self.source_ids))
        object.__setattr__(self, "dependency_versions", _freeze(self.dependency_versions))
        object.__setattr__(self, "provenance", _freeze(self.provenance))
        if self.content_hash and self.content_hash != self.compute_hash():
            raise ContractValidationError("content hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}

    def compute_hash(self) -> str:
        value = self.to_dict()
        value["content_hash"] = ""
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def verify_hash(self) -> bool:
        return bool(self.content_hash) and self.content_hash == self.compute_hash()


def seal(record: PerceptionRecord):
    return replace(record, content_hash=record.compute_hash())


@dataclass(frozen=True, kw_only=True)
class OracleIntent(PerceptionRecord):
    intent_type: str
    requested_timeframes: tuple[str, ...]
    original_text: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.intent_type not in {"LOAD_CONTEXT", "CAPTURE_VISUAL", "VERIFY_VISUAL"}:
            raise ContractValidationError("intent is outside Phase-2 perception scope")
        if not self.requested_timeframes or any(item not in SUPPORTED_TIMEFRAMES for item in self.requested_timeframes):
            raise ContractValidationError("invalid requested timeframe")


@dataclass(frozen=True, kw_only=True)
class CanonicalCandleRef(PerceptionRecord):
    candle_id: str
    security_id: str
    bar_start: str
    bar_end: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    trading_date: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.security_id or not self.candle_id:
            raise ContractValidationError("security/instrument identity is required")
        start, end = _aware(self.bar_start, "bar_start"), _aware(self.bar_end, "bar_end")
        if end <= start:
            raise ContractValidationError("bar boundary is invalid")
        if self.completion_status is CompletionStatus.FORMING:
            raise ContractValidationError("forming candle cannot be completed evidence")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close) or self.high < self.low:
            raise ContractValidationError("OHLC is inconsistent")
        if self.volume < 0:
            raise ContractValidationError("volume is invalid")


@dataclass(frozen=True, kw_only=True)
class VisualClaimCandidate(PerceptionRecord):
    claim_id: str
    claim_type: str
    direction: str
    predicates: Mapping[str, Any]
    declared_tolerance: float
    observation_id: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.claim_type not in {"TREND", "STRUCTURE_BREAK", "LEVEL_ACCEPTANCE", "LEVEL_REJECTION", "LIQUIDITY_SWEEP", "DISPLACEMENT", "COMPRESSION"}:
            raise ContractValidationError("unsupported visual claim type")
        if self.direction not in {"BULLISH", "BEARISH", "ABOVE", "BELOW", "UP", "DOWN", "NEUTRAL"}:
            raise ContractValidationError("unsupported claim direction")
        if self.declared_tolerance < 0 or not self.predicates:
            raise ContractValidationError("claim predicates/tolerance are invalid")


@dataclass(frozen=True, kw_only=True)
class VisualObservation(PerceptionRecord):
    observation_id: str
    detected_symbol: str | None
    visible_timeframe: str | None
    chart_metadata: Mapping[str, Any]
    artifact_reference: str | None
    visible_drawings: tuple[Mapping[str, Any], ...]
    visible_indicators: tuple[str, ...]
    claim_candidates: tuple[VisualClaimCandidate, ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.availability is Availability.AVAILABLE and self.detected_symbol and self.detected_symbol.upper() != self.symbol:
            raise ContractValidationError("cross-symbol visual observation")
        if self.availability is Availability.AVAILABLE and self.visible_timeframe and self.visible_timeframe != self.timeframe:
            raise ContractValidationError("cross-timeframe visual observation")
        if any(
            claim.observation_id != self.observation_id
            or claim.symbol != self.symbol
            or claim.timeframe != self.timeframe
            or not claim.verify_hash()
            for claim in self.claim_candidates
        ):
            raise ContractValidationError("invalid visual claim dependency")
        object.__setattr__(self, "chart_metadata", _freeze(self.chart_metadata))
        object.__setattr__(self, "visible_drawings", tuple(_freeze(item) for item in self.visible_drawings))


@dataclass(frozen=True, kw_only=True)
class VerifiedVisualClaim(PerceptionRecord):
    claim_id: str
    observation_id: str
    claim_type: str
    status: str
    predicates_evaluated: tuple[Mapping[str, Any], ...]
    input_record_ids: tuple[str, ...]
    numerical_values: Mapping[str, Any]
    tolerances: Mapping[str, float]
    supporting_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    verifier_version: str
    actionable_evidence_weight: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.status not in {"VERIFIED", "REJECTED", "UNVERIFIABLE", "PARTIALLY_VERIFIED"}:
            raise ContractValidationError("invalid verification status")
        if self.actionable_evidence_weight != 0.0:
            raise ContractValidationError("Phase-2 claims have zero actionable weight")
        object.__setattr__(self, "predicates_evaluated", tuple(_freeze(item) for item in self.predicates_evaluated))
        object.__setattr__(self, "numerical_values", _freeze(self.numerical_values))
        object.__setattr__(self, "tolerances", _freeze(self.tolerances))


@dataclass(frozen=True, kw_only=True)
class TimeframeContext(PerceptionRecord):
    lane_id: str
    cache_key: str
    candle: CanonicalCandleRef | None
    lane_state: str
    provisional: bool
    evidence_eligible: bool
    invalidation_reasons: tuple[str, ...]
    context_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.candle and (self.candle.symbol != self.symbol or self.candle.timeframe != self.timeframe):
            raise ContractValidationError("cross-symbol/timeframe lane dependency")
        if self.candle and not self.candle.verify_hash():
            raise ContractValidationError("candle hash mismatch")
        if self.candle and self.dependency_versions.get("candle_hash") != self.candle.content_hash:
            raise ContractValidationError("candle dependency mismatch")
        object.__setattr__(self, "context_payload", _freeze(self.context_payload))


@dataclass(frozen=True, kw_only=True)
class MarketContextSnapshot(PerceptionRecord):
    snapshot_id: str
    lane_hashes: Mapping[str, str]
    lanes: tuple[TimeframeContext, ...]
    composite_state: str
    mandatory_missing: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        actual = {lane.timeframe: lane.content_hash for lane in self.lanes}
        if set(actual) != set(SUPPORTED_TIMEFRAMES) or dict(self.lane_hashes) != actual:
            raise ContractValidationError("composite lane hash mismatch")
        if any(lane.symbol != self.symbol or not lane.verify_hash() for lane in self.lanes):
            raise ContractValidationError("invalid composite dependency")
        object.__setattr__(self, "lane_hashes", _freeze(self.lane_hashes))


def record_from_dict(record_type, raw: Mapping[str, Any]):
    """Strict recovery helper for durable Phase-2 records."""
    value = dict(raw)
    for key, enum_type in (("availability", Availability), ("freshness_state", FreshnessState), ("completion_status", CompletionStatus)):
        value[key] = enum_type(value[key])
    if record_type is TimeframeContext and isinstance(value.get("candle"), Mapping):
        value["candle"] = record_from_dict(CanonicalCandleRef, value["candle"])
    if record_type is MarketContextSnapshot:
        value["lanes"] = tuple(record_from_dict(TimeframeContext, item) for item in value.get("lanes") or ())
    if record_type is VisualObservation:
        value["claim_candidates"] = tuple(
            record_from_dict(VisualClaimCandidate, item) for item in value.get("claim_candidates") or ()
        )
    return record_type(**value)
