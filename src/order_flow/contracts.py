"""Immutable and deterministically serializable order-flow contracts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = 1
FLOW_FORMULA_VERSION = "ORDER_FLOW_V1_20260809"


class DataQuality(str, Enum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    UNUSABLE = "UNUSABLE"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"


class DirectionalState(str, Enum):
    CALL = "CALL"
    PUT = "PUT"
    NEUTRAL = "NEUTRAL"
    DATA_LOCKED = "DATA_LOCKED"


class AggressorSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    UNKNOWN = "UNKNOWN"


class ReversalState(str, Enum):
    STABLE_DIRECTION = "STABLE_DIRECTION"
    PRESSURE_FLIP = "PRESSURE_FLIP"
    REVERSAL_FORMING = "REVERSAL_FORMING"
    REVERSAL_CONFIRMED = "REVERSAL_CONFIRMED"


@dataclass(frozen=True, slots=True)
class DepthLevel:
    level: int
    bid_price: float
    bid_quantity: int
    bid_orders: int
    ask_price: float
    ask_quantity: int
    ask_orders: int


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    exchange_segment: str
    security_id: str
    role: str
    expiry: str | None = None
    strike: float | None = None
    option_type: str | None = None


@dataclass(frozen=True, slots=True)
class MarketEvent:
    schema_version: int
    session_id: str
    feed_generation: int
    event_id: str
    exchange_segment: str
    security_id: str
    instrument_role: str
    expiry: str | None
    strike: float | None
    option_type: str | None
    exchange_ltt: int
    receive_wall_utc: str
    feed_receive_ns: int
    decode_done_ns: int
    ltp: float
    ltq: int
    cumulative_volume: int
    atp: float
    oi: int
    high_oi: int
    low_oi: int
    total_buy_qty: int
    total_sell_qty: int
    depth_5: tuple[DepthLevel, ...]
    data_quality: DataQuality
    packet_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported order-flow event schema")
        if len(self.depth_5) != 5:
            raise ValueError("Full packet must contain exactly five depth levels")
        for value in (self.ltp, self.atp):
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError("market event contains non-finite price")
        for value in (
            self.feed_generation,
            self.exchange_ltt,
            self.feed_receive_ns,
            self.decode_done_ns,
            self.ltq,
            self.cumulative_volume,
            self.oi,
        ):
            if isinstance(value, bool) or value < 0:
                raise ValueError("market event contains invalid counter")


@dataclass(frozen=True, slots=True)
class ReconciledTradeState:
    event_id: str
    delta_volume: int
    classified_buy_qty: int
    classified_sell_qty: int
    unclassified_qty: int
    signer_method: str
    signer_confidence: float
    reconciliation_status: str
    aggressor_side: AggressorSide
    observed_trade_price: float | None
    observed_trade_qty: int
    data_quality: DataQuality

    def __post_init__(self) -> None:
        if min(
            self.delta_volume,
            self.classified_buy_qty,
            self.classified_sell_qty,
            self.unclassified_qty,
            self.observed_trade_qty,
        ) < 0:
            raise ValueError("reconciled volume cannot be negative")
        if (
            self.classified_buy_qty
            + self.classified_sell_qty
            + self.unclassified_qty
            != self.delta_volume
        ):
            raise ValueError("FLOW_DATA_DEGRADED: reconciliation invariant")
        if not 0.0 <= self.signer_confidence <= 1.0:
            raise ValueError("signer confidence outside [0,1]")


@dataclass(frozen=True, slots=True)
class FeatureValue:
    value: Any
    event_timestamp: int | None
    local_timestamp: str
    age_seconds: float
    confidence: float
    freshness: FreshnessState
    source: str
    status: str = "AVAILABLE"


@dataclass(frozen=True, slots=True)
class FlowProjection:
    schema_version: int
    formula_version: str
    revision: int
    snapshot_id: str
    session_id: str
    generated_at: str
    instruments: tuple[InstrumentIdentity, ...]
    call_strength: float
    put_strength: float
    directional_score: float
    directional_state: DirectionalState
    action_eligible: bool
    action_lock_reasons: tuple[str, ...]
    family_values: Mapping[str, Any]
    family_confidence: Mapping[str, float]
    freshness: Mapping[str, Any]
    data_quality: DataQuality
    signed_flow_coverage: float
    profile_coverage: float
    reversal_state: ReversalState
    location_diagnostics: Mapping[str, Any]
    latency_timestamps: Mapping[str, int]
    recorder_health: str
    latency_schema_version: int = 2
    execution_influence: str = "ZERO"
    authority_20_depth: str = "DISABLED"
    probability: None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported FlowProjection schema")
        if self.formula_version != FLOW_FORMULA_VERSION:
            raise ValueError("unexpected FlowProjection formula version")
        if self.execution_influence != "ZERO":
            raise ValueError("order flow must remain advisory-only")
        for value in (
            self.call_strength,
            self.put_strength,
            self.signed_flow_coverage,
            self.profile_coverage,
        ):
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError("projection contains non-finite value")
        if not 0.0 <= self.call_strength <= 100.0:
            raise ValueError("CALL strength outside [0,100]")
        if not 0.0 <= self.put_strength <= 100.0:
            raise ValueError("PUT strength outside [0,100]")
        if not -1.0 <= self.directional_score <= 1.0:
            raise ValueError("directional score outside [-1,1]")

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
