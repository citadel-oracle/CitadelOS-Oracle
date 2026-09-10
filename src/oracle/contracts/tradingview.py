"""Immutable Phase-6A TradingView identity and live-workspace contracts.

TradingView is an identity/visual-perception source only.  Market values and
decisions remain owned by canonical CITADEL services.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from enum import Enum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = "oracle-tradingview-6a.1.0"
SYNC_POLICY_VERSION = "oracle-tradingview-sync-6a.1.0"
SUPPORTED_TIMEFRAMES = ("1D", "4H", "1H", "15m", "5m", "3m", "1m")


class TradingViewContractError(ValueError):
    pass


class TradingViewAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"


class TradingViewFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class TradingViewRoute(str, Enum):
    UNDERLYING_INDEX = "UNDERLYING_INDEX"
    UNDERLYING_STOCK = "UNDERLYING_STOCK"
    EXACT_OPTION = "EXACT_OPTION"
    FUTURE = "FUTURE"
    CRYPTO = "CRYPTO"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"


def _aware(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise TradingViewContractError(f"{name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TradingViewContractError(f"{name} must be timezone-aware")
    return parsed


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items())})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, kw_only=True)
class TradingViewRecord:
    event_id: str
    correlation_id: str
    source_timestamp: str
    received_timestamp: str
    generated_timestamp: str
    provenance: Mapping[str, Any]
    content_hash: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_id or not self.correlation_id or not self.provenance:
            raise TradingViewContractError("identity and provenance are required")
        source = _aware(self.source_timestamp, "source_timestamp")
        received = _aware(self.received_timestamp, "received_timestamp")
        generated = _aware(self.generated_timestamp, "generated_timestamp")
        if source > received or received > generated:
            raise TradingViewContractError("future or inverted chart-state timestamps")
        object.__setattr__(self, "provenance", _freeze(self.provenance))
        if self.content_hash and self.content_hash != self.compute_hash():
            raise TradingViewContractError("content hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}

    def compute_hash(self) -> str:
        value = self.to_dict()
        value["content_hash"] = ""
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def verify_hash(self) -> bool:
        return bool(self.content_hash) and self.content_hash == self.compute_hash()


def seal(record: TradingViewRecord):
    return replace(record, content_hash=record.compute_hash())


@dataclass(frozen=True, kw_only=True)
class TradingViewSymbolIdentity:
    raw_symbol: str
    normalized_symbol: str
    exchange: str | None
    route: TradingViewRoute
    ambiguity_status: str

    def __post_init__(self) -> None:
        if not self.raw_symbol or not self.normalized_symbol:
            raise TradingViewContractError("symbol identity is required")
        if self.route is TradingViewRoute.AMBIGUOUS and self.ambiguity_status == "RESOLVED":
            raise TradingViewContractError("ambiguous route cannot be resolved")


@dataclass(frozen=True, kw_only=True)
class TradingViewInstrumentIdentity:
    route: TradingViewRoute
    instrument_id: str | None
    security_id: str | None
    underlying: str
    analysis_supported: bool
    mapping_status: str


@dataclass(frozen=True, kw_only=True)
class TradingViewOptionIdentity:
    underlying: str
    expiry: str
    strike: float
    option_side: str
    trading_symbol: str
    security_id: str | None = None

    def __post_init__(self) -> None:
        try:
            expiry = datetime.fromisoformat(self.expiry).date()
        except (TypeError, ValueError) as error:
            raise TradingViewContractError("malformed option expiry") from error
        if not expiry or self.strike <= 0 or self.option_side not in {"CE", "PE"}:
            raise TradingViewContractError("malformed option identity")


@dataclass(frozen=True, kw_only=True)
class TradingViewLayoutIdentity:
    session_identity: str
    browser_identity: str
    chart_identity: str
    layout_identity: str
    active_pane_index: int | None
    chart_count: int

    def __post_init__(self) -> None:
        if not all((self.session_identity, self.browser_identity, self.chart_identity, self.layout_identity)):
            raise TradingViewContractError("chart/layout/session identity is required")
        if self.chart_count < 1 or (self.active_pane_index is not None and not 0 <= self.active_pane_index < self.chart_count):
            raise TradingViewContractError("cross-chart layout mismatch")


@dataclass(frozen=True, kw_only=True)
class TradingViewChartState(TradingViewRecord):
    symbol: TradingViewSymbolIdentity
    instrument: TradingViewInstrumentIdentity
    option: TradingViewOptionIdentity | None
    layout: TradingViewLayoutIdentity
    timeframe: str
    chart_state_version: str
    availability: TradingViewAvailability
    freshness: TradingViewFreshness
    previous_state_hash: str | None
    change_reason: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.timeframe not in SUPPORTED_TIMEFRAMES:
            raise TradingViewContractError("impossible timeframe")
        if self.symbol.route is TradingViewRoute.EXACT_OPTION and self.option is None:
            raise TradingViewContractError("unsupported option format")
        if self.option and self.option.underlying != self.instrument.underlying:
            raise TradingViewContractError("cross-chart option/underlying mismatch")
        if self.freshness is TradingViewFreshness.STALE and self.availability is TradingViewAvailability.AVAILABLE:
            raise TradingViewContractError("stale state cannot be available")


@dataclass(frozen=True, kw_only=True)
class TradingViewStateChangeEvent(TradingViewRecord):
    chart_state_hash: str
    previous_state_hash: str | None
    change_reason: str
    deduplication_key: str


@dataclass(frozen=True, kw_only=True)
class TradingViewCaptureReference(TradingViewRecord):
    chart_state_hash: str
    capture_status: str
    artifact_reference: str | None
    permission_status: str
    numerical_verification_required: bool = True
    actionable_evidence_weight: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.actionable_evidence_weight != 0.0:
            raise TradingViewContractError("unverified capture must have zero evidence weight")


@dataclass(frozen=True, kw_only=True)
class TradingViewSyncProjection(TradingViewRecord):
    sync_state: str
    chart_state: TradingViewChartState | None
    decision: Mapping[str, Any]
    knowledge: Mapping[str, Any]
    phase5: Mapping[str, Any]
    personal_oracle: Mapping[str, Any]
    health: Mapping[str, Any]
    safety: Mapping[str, Any]
    alert_event: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.sync_state not in {"DETECTING", "LOADING_CONTEXT", "BUY", "WAIT", "NO_TRADE", "WATCHING", "REVALIDATING", "PAPER_ORDER", "MANAGE", "EXIT", "EXITED", "UNAVAILABLE", "AMBIGUOUS"}:
            raise TradingViewContractError("unsupported live workspace state")
        safety = dict(self.safety)
        required = {"paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                    "advisory_only": True, "execution_influence": "ZERO", "execution_authority": False}
        if any(safety.get(key) != value for key, value in required.items()):
            raise TradingViewContractError("Phase-6A safety boundary violation")
        for name in ("decision", "knowledge", "phase5", "personal_oracle", "health", "safety"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        if self.alert_event is not None:
            object.__setattr__(self, "alert_event", _freeze(self.alert_event))
