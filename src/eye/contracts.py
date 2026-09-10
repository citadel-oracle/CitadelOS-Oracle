"""Canonical Market-Event Contracts for CITADEL Eye Engine (Phase E1 Hardened)."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.eye.serialization import canonical_json, compute_sha256

SCHEMA_VERSION = "0.1.0"


class EyeContractError(ValueError):
    pass


def _freeze(value: Any) -> Any:
    """Recursively converts mutable dicts/lists to immutable MappingProxyType/tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in sorted(value.items(), key=lambda r: str(r[0]))})
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze(v) for v in value)
    return value


class EventFamily(str, Enum):
    STRUCTURE = "STRUCTURE"
    LIQUIDITY = "LIQUIDITY"
    IMBALANCE = "IMBALANCE"
    ZONE = "ZONE"
    BREAKOUT = "BREAKOUT"
    RETEST = "RETEST"
    DISPLACEMENT = "DISPLACEMENT"
    REGIME = "REGIME"
    CONTEXT = "CONTEXT"


class EventType(str, Enum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"
    BOS_BULLISH = "BOS_BULLISH"
    BOS_BEARISH = "BOS_BEARISH"
    CHOCH_BULLISH = "CHOCH_BULLISH"
    CHOCH_BEARISH = "CHOCH_BEARISH"
    LIQUIDITY_POOL_HIGH = "LIQUIDITY_POOL_HIGH"
    LIQUIDITY_POOL_LOW = "LIQUIDITY_POOL_LOW"
    LIQUIDITY_SWEEP_HIGH = "LIQUIDITY_SWEEP_HIGH"
    LIQUIDITY_SWEEP_LOW = "LIQUIDITY_SWEEP_LOW"
    RECLAIM_BULLISH = "RECLAIM_BULLISH"
    RECLAIM_BEARISH = "RECLAIM_BEARISH"
    FVG_BULLISH = "FVG_BULLISH"
    FVG_BEARISH = "FVG_BEARISH"
    ORDER_BLOCK_BULLISH = "ORDER_BLOCK_BULLISH"
    ORDER_BLOCK_BEARISH = "ORDER_BLOCK_BEARISH"
    SUPPLY_ZONE = "SUPPLY_ZONE"
    DEMAND_ZONE = "DEMAND_ZONE"
    BREAKOUT_BULLISH = "BREAKOUT_BULLISH"
    BREAKOUT_BEARISH = "BREAKOUT_BEARISH"
    ACCEPTANCE_ABOVE = "ACCEPTANCE_ABOVE"
    ACCEPTANCE_BELOW = "ACCEPTANCE_BELOW"
    RETEST_BULLISH = "RETEST_BULLISH"
    RETEST_BEARISH = "RETEST_BEARISH"
    FAILED_BREAKOUT_BULLISH = "FAILED_BREAKOUT_BULLISH"
    FAILED_BREAKOUT_BEARISH = "FAILED_BREAKOUT_BEARISH"
    DISPLACEMENT_BULLISH = "DISPLACEMENT_BULLISH"
    DISPLACEMENT_BEARISH = "DISPLACEMENT_BEARISH"
    COMPRESSION = "COMPRESSION"
    RANGE = "RANGE"
    TREND_BULLISH = "TREND_BULLISH"
    TREND_BEARISH = "TREND_BEARISH"


class EventDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    NON_DIRECTIONAL = "NON_DIRECTIONAL"


class PayloadKind(str, Enum):
    POINT = "POINT"
    ZONE = "ZONE"
    STATE = "STATE"
    RELATIONSHIP = "RELATIONSHIP"


class DetectionState(str, Enum):
    PROVISIONAL_INTRABAR = "PROVISIONAL_INTRABAR"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED_CLOSED_BAR = "CONFIRMED_CLOSED_BAR"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class LifecycleState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    TESTED = "TESTED"
    PARTIALLY_MITIGATED = "PARTIALLY_MITIGATED"
    MITIGATED = "MITIGATED"
    WEAKENING = "WEAKENING"
    EXHAUSTED = "EXHAUSTED"
    BROKEN = "BROKEN"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class AuthorityType(str, Enum):
    OBSERVATION_ONLY = "OBSERVATION_ONLY"


class ProbabilityStatus(str, Enum):
    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    ESTABLISHED = "ESTABLISHED"


class MarketSessionState(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    POST_MARKET = "POST_MARKET"
    HOLIDAY = "HOLIDAY"
    UNKNOWN = "UNKNOWN"


class DataState(str, Enum):
    LIVE = "LIVE"
    ONE_BAR_LATE = "ONE_BAR_LATE"
    STALE = "STALE"
    POST_MARKET_COMPLETE = "POST_MARKET_COMPLETE"
    WARMUP_MISSING = "WARMUP_MISSING"
    UNAVAILABLE = "UNAVAILABLE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


def _check_tz(dt: datetime, name: str) -> None:
    if not isinstance(dt, datetime):
        raise EyeContractError(f"{name} must be a datetime instance")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise EyeContractError(f"{name} must be timezone-aware (UTC required)")


@dataclass(frozen=True, kw_only=True, slots=True)
class PriceAtom:
    ticks: int
    quantum: str = "0.01"

    def __post_init__(self) -> None:
        if not isinstance(self.ticks, int) or isinstance(self.ticks, bool):
            raise EyeContractError("ticks must be an integer (bool not allowed)")
        try:
            q_dec = Decimal(str(self.quantum))
            if q_dec <= 0 or not q_dec.is_finite():
                raise EyeContractError("Invalid quantum: must be positive finite decimal")
            # Normalize trailing zeros
            object.__setattr__(self, "quantum", str(q_dec.normalize()))
        except InvalidOperation:
            raise EyeContractError(f"Invalid quantum string: {self.quantum}")

    @property
    def value(self) -> float:
        return float(Decimal(self.ticks) * Decimal(self.quantum))

    def to_dict(self) -> dict[str, Any]:
        return {"ticks": self.ticks, "quantum": self.quantum}


@dataclass(frozen=True, kw_only=True, slots=True)
class InstrumentIdentity:
    raw_symbol: str
    normalized_symbol: str
    exchange: str
    instrument_type: str  # "UNDERLYING_INDEX" | "EXACT_OPTION" | "UNDERLYING_STOCK"
    underlying: str
    source: str
    market: str
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None  # "CALL" | "PUT"
    security_id: Optional[str] = None
    identity_epoch: Optional[str] = None
    replay_run_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.instrument_type == "UNDERLYING_INDEX":
            if self.expiry or self.strike or self.option_type:
                raise EyeContractError("Underlying index must not carry option fields")
        elif self.instrument_type == "EXACT_OPTION":
            if not self.expiry or self.strike is None or not self.option_type:
                raise EyeContractError("Exact option requires complete option identity (expiry, strike, option_type)")
            norm_opt = "CALL" if self.option_type in ("CALL", "CE") else "PUT" if self.option_type in ("PUT", "PE") else None
            if not norm_opt:
                raise EyeContractError("option_type must be CALL, PUT, CE, or PE")
            object.__setattr__(self, "option_type", norm_opt)

    @property
    def instrument_key(self) -> str:
        if self.instrument_type == "EXACT_OPTION":
            return f"EXACT_OPTION:{self.underlying}:{self.expiry}:{self.strike}:{self.option_type}"
        return f"{self.instrument_type}:{self.underlying}"

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, kw_only=True, slots=True)
class EvaluationContext:
    market_time: datetime
    available_at: datetime
    detected_at: datetime
    as_of: datetime
    confirmed_at: Optional[datetime] = None
    calculated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        _check_tz(self.market_time, "market_time")
        _check_tz(self.available_at, "available_at")
        _check_tz(self.detected_at, "detected_at")
        _check_tz(self.as_of, "as_of")
        if self.confirmed_at:
            _check_tz(self.confirmed_at, "confirmed_at")
        if self.calculated_at:
            _check_tz(self.calculated_at, "calculated_at")
        if self.published_at:
            _check_tz(self.published_at, "published_at")
        if self.available_at > self.as_of:
            raise EyeContractError("available_at cannot exceed evaluation watermark as_of")

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_time": self.market_time.astimezone(timezone.utc).isoformat(),
            "available_at": self.available_at.astimezone(timezone.utc).isoformat(),
            "detected_at": self.detected_at.astimezone(timezone.utc).isoformat(),
            "as_of": self.as_of.astimezone(timezone.utc).isoformat(),
            "confirmed_at": self.confirmed_at.astimezone(timezone.utc).isoformat() if self.confirmed_at else None,
            "calculated_at": self.calculated_at.astimezone(timezone.utc).isoformat() if self.calculated_at else None,
            "published_at": self.published_at.astimezone(timezone.utc).isoformat() if self.published_at else None,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class BarReference:
    instrument_key: str
    timeframe: str
    open_time: datetime
    expected_close_time: datetime
    available_at: datetime
    bar_key: str
    is_closed: bool
    source_name: str
    actual_close_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        _check_tz(self.open_time, "open_time")
        _check_tz(self.expected_close_time, "expected_close_time")
        _check_tz(self.available_at, "available_at")
        if self.actual_close_time:
            _check_tz(self.actual_close_time, "actual_close_time")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_key": self.instrument_key,
            "timeframe": self.timeframe,
            "open_time": self.open_time.astimezone(timezone.utc).isoformat(),
            "expected_close_time": self.expected_close_time.astimezone(timezone.utc).isoformat(),
            "actual_close_time": self.actual_close_time.astimezone(timezone.utc).isoformat() if self.actual_close_time else None,
            "available_at": self.available_at.astimezone(timezone.utc).isoformat(),
            "bar_key": self.bar_key,
            "is_closed": self.is_closed,
            "source_name": self.source_name,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class PointEventPayload:
    primary_level: PriceAtom
    direction: EventDirection
    breached_level: Optional[PriceAtom] = None
    payload_kind: PayloadKind = PayloadKind.POINT

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_kind": self.payload_kind.value,
            "primary_level": self.primary_level.to_dict(),
            "direction": self.direction.value,
            "breached_level": self.breached_level.to_dict() if self.breached_level else None,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class ZoneEventPayload:
    lower: PriceAtom
    upper: PriceAtom
    zone_role: str  # "SUPPORT" | "RESISTANCE" | "IMBALANCE"
    payload_kind: PayloadKind = PayloadKind.ZONE

    def __post_init__(self) -> None:
        if self.lower.ticks > self.upper.ticks:
            raise EyeContractError("Zone lower bound cannot exceed upper bound")
        if self.lower.quantum != self.upper.quantum:
            raise EyeContractError("Zone lower and upper bounds must share identical price quantum")

    @property
    def midpoint(self) -> PriceAtom:
        # Integer division truncation towards zero for odd ticks
        mid_ticks = (self.lower.ticks + self.upper.ticks) // 2
        return PriceAtom(ticks=mid_ticks, quantum=self.lower.quantum)

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_kind": self.payload_kind.value,
            "lower": self.lower.to_dict(),
            "upper": self.upper.to_dict(),
            "midpoint": self.midpoint.to_dict(),
            "zone_role": self.zone_role,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class StateEventPayload:
    state_code: str
    effective_from_bar: str
    effective_until_bar: Optional[str] = None
    payload_kind: PayloadKind = PayloadKind.STATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_kind": self.payload_kind.value,
            "state_code": self.state_code,
            "effective_from_bar": self.effective_from_bar,
            "effective_until_bar": self.effective_until_bar,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class RelationshipEventPayload:
    parent_event_keys: Tuple[str, ...]
    relationship_type: str
    payload_kind: PayloadKind = PayloadKind.RELATIONSHIP

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent_event_keys", tuple(self.parent_event_keys))

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_kind": self.payload_kind.value,
            "parent_event_keys": list(self.parent_event_keys),
            "relationship_type": self.relationship_type,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class EyeEvidence:
    evidence_id: str
    evidence_code: str
    evidence_type: str
    source_bars: Tuple[str, ...]
    observed_measurement: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_bars", tuple(self.source_bars))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_code": self.evidence_code,
            "evidence_type": self.evidence_type,
            "source_bars": list(self.source_bars),
            "observed_measurement": self.observed_measurement,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class ProducerProvenance:
    engine_name: str
    source_file: str
    source_symbol: str
    source_commit: str
    producer_version: str
    rule_id: str
    rule_version: str
    authority: AuthorityType = AuthorityType.OBSERVATION_ONLY

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "source_file": self.source_file,
            "source_symbol": self.source_symbol,
            "source_commit": self.source_commit,
            "producer_version": self.producer_version,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "authority": self.authority.value,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class FreshnessSnapshot:
    source_timestamp: datetime
    received_at: datetime
    calculated_at: datetime
    published_at: datetime
    evaluation_as_of: datetime
    market_session_state: MarketSessionState
    data_state: DataState

    def __post_init__(self) -> None:
        _check_tz(self.source_timestamp, "source_timestamp")
        _check_tz(self.received_at, "received_at")
        _check_tz(self.calculated_at, "calculated_at")
        _check_tz(self.published_at, "published_at")
        _check_tz(self.evaluation_as_of, "evaluation_as_of")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_timestamp": self.source_timestamp.astimezone(timezone.utc).isoformat(),
            "received_at": self.received_at.astimezone(timezone.utc).isoformat(),
            "calculated_at": self.calculated_at.astimezone(timezone.utc).isoformat(),
            "published_at": self.published_at.astimezone(timezone.utc).isoformat(),
            "evaluation_as_of": self.evaluation_as_of.astimezone(timezone.utc).isoformat(),
            "market_session_state": self.market_session_state.value,
            "data_state": self.data_state.value,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class ProbabilityAssessment:
    status: ProbabilityStatus = ProbabilityStatus.NOT_ESTABLISHED
    probability: Optional[float] = None
    sample_size: Optional[int] = None

    def __post_init__(self) -> None:
        if self.status == ProbabilityStatus.NOT_ESTABLISHED and self.probability is not None:
            raise EyeContractError("Numeric probability requires ESTABLISHED status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "probability": self.probability,
            "sample_size": self.sample_size,
        }


@dataclass(frozen=True, kw_only=True, slots=True)
class EyeEventRecord:
    schema_version: str
    event_key: str
    record_id: str
    event_revision: int
    family: EventFamily
    event_type: EventType
    direction: EventDirection
    instrument: InstrumentIdentity
    timeframe: str
    payload: Any
    detection_state: DetectionState
    lifecycle_state: LifecycleState
    evaluation_context: EvaluationContext
    observed_at: datetime
    detected_at: datetime
    source_bars: Tuple[BarReference, ...]
    producer: ProducerProvenance
    authority: AuthorityType = AuthorityType.OBSERVATION_ONLY
    previous_record_id: Optional[str] = None
    supersedes_record_id: Optional[str] = None

    def __post_init__(self) -> None:
        _check_tz(self.observed_at, "observed_at")
        _check_tz(self.detected_at, "detected_at")
        object.__setattr__(self, "source_bars", tuple(self.source_bars))

        if self.supersedes_record_id and self.supersedes_record_id == self.record_id:
            raise EyeContractError("Supersession cannot reference self record_id")

        # Temporal & Bitemporal No-Look-Ahead Validation across ALL source bars
        as_of = self.evaluation_context.as_of
        for bar in self.source_bars:
            if bar.available_at > as_of:
                raise EyeContractError(f"Source bar available_at ({bar.available_at}) exceeds evaluation as_of ({as_of})")
            if bar.is_closed:
                if bar.expected_close_time > as_of:
                    raise EyeContractError(f"Closed source bar expected_close_time ({bar.expected_close_time}) exceeds as_of ({as_of})")
                if bar.actual_close_time and bar.actual_close_time > as_of:
                    raise EyeContractError(f"Closed source bar actual_close_time ({bar.actual_close_time}) exceeds as_of ({as_of})")
            elif self.detection_state == DetectionState.CONFIRMED_CLOSED_BAR:
                raise EyeContractError("CONFIRMED_CLOSED_BAR event cannot reference unclosed forming source bar")

    @classmethod
    def create(
        cls,
        *,
        event_revision: int = 1,
        family: EventFamily,
        event_type: EventType,
        direction: EventDirection,
        instrument: InstrumentIdentity,
        timeframe: str,
        payload: Any,
        detection_state: DetectionState,
        lifecycle_state: LifecycleState,
        evaluation_context: EvaluationContext,
        observed_at: datetime,
        detected_at: datetime,
        source_bars: Sequence[BarReference],
        producer: ProducerProvenance,
        previous_record_id: Optional[str] = None,
        supersedes_record_id: Optional[str] = None,
    ) -> EyeEventRecord:
        bars_tuple = tuple(source_bars)

        # Hash projection for semantic event_key (stable across retries, reconnects & lifecycle updates)
        semantic_projection = {
            "instrument_key": instrument.instrument_key,
            "event_type": event_type.value,
            "timeframe": timeframe,
            "source_bar_keys": sorted(b.bar_key for b in bars_tuple),
            "payload": payload.to_dict(),
            "rule_id": producer.rule_id,
            "rule_version": producer.rule_version,
        }
        event_key = compute_sha256(semantic_projection)

        # Hash projection for immutable record_id (changes on revision/state update)
        record_projection = {
            "event_key": event_key,
            "event_revision": event_revision,
            "detection_state": detection_state.value,
            "lifecycle_state": lifecycle_state.value,
            "identity_epoch": instrument.identity_epoch,
            "producer_version": producer.producer_version,
            "previous_record_id": previous_record_id or "",
        }
        record_id = compute_sha256(record_projection)

        return cls(
            schema_version=SCHEMA_VERSION,
            event_key=event_key,
            record_id=record_id,
            event_revision=event_revision,
            family=family,
            event_type=event_type,
            direction=direction,
            instrument=instrument,
            timeframe=timeframe,
            payload=payload,
            detection_state=detection_state,
            lifecycle_state=lifecycle_state,
            evaluation_context=evaluation_context,
            observed_at=observed_at,
            detected_at=detected_at,
            source_bars=bars_tuple,
            producer=producer,
            authority=AuthorityType.OBSERVATION_ONLY,
            previous_record_id=previous_record_id,
            supersedes_record_id=supersedes_record_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_key": self.event_key,
            "record_id": self.record_id,
            "event_revision": self.event_revision,
            "family": self.family.value,
            "event_type": self.event_type.value,
            "direction": self.direction.value,
            "instrument": self.instrument.to_dict(),
            "timeframe": self.timeframe,
            "payload": self.payload.to_dict(),
            "detection_state": self.detection_state.value,
            "lifecycle_state": self.lifecycle_state.value,
            "evaluation_context": self.evaluation_context.to_dict(),
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "detected_at": self.detected_at.astimezone(timezone.utc).isoformat(),
            "source_bars": [b.to_dict() for b in self.source_bars],
            "producer": self.producer.to_dict(),
            "authority": self.authority.value,
            "previous_record_id": self.previous_record_id,
            "supersedes_record_id": self.supersedes_record_id,
        }
