"""Typed schema-v1 contracts for order intent, lifecycle and observed fills."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

SCHEMA_VERSION = 1
SIDES = {"BUY", "SELL"}
ORDER_TYPES = {"MARKET", "LIMIT", "STOP", "STOP_LIMIT"}
TIFS = {"DAY", "IOC"}


def decimal_value(value: Any, name: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{name} must be decimal-compatible") from error
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"invalid {name}")
    return result


def stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}_{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    created_at: str
    symbol: str
    instrument_id: str
    exchange_segment: str
    side: str
    order_type: str
    time_in_force: str
    requested_quantity: int
    authorized_quantity: int
    lot_size: Optional[int]
    limit_price: Optional[Decimal]
    stop_price: Optional[Decimal]
    reference_price: Optional[Decimal]
    reference_price_source: str
    strategy_id: str
    strategy_version: Optional[str]
    aegis_decision_id: str
    aegis_decision: str
    risk_decision_id: str
    risk_decision: str
    market_data_timestamp: str
    session_state: str
    kill_switch_state: str
    live_trading_enabled: bool
    advisory_only: bool = True
    broker_submission_requested: bool = False
    execution_requested: bool = False
    schema_version: int = SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION or self.side not in SIDES or self.order_type not in ORDER_TYPES or self.time_in_force not in TIFS:
            raise ValueError("invalid order intent contract")
        if type(self.requested_quantity) is not int or self.requested_quantity <= 0:
            raise ValueError("requested quantity must be a positive integer")
        if type(self.authorized_quantity) is not int or not 0 <= self.authorized_quantity <= self.requested_quantity:
            raise ValueError("authorized quantity exceeds requested quantity")
        if self.lot_size is not None and (type(self.lot_size) is not int or self.lot_size <= 0 or self.requested_quantity % self.lot_size):
            raise ValueError("quantity is inconsistent with lot size")
        if self.live_trading_enabled or not self.advisory_only or self.broker_submission_requested or self.execution_requested:
            raise ValueError("unsafe order intent contract")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["metadata"] = _sanitize_mapping(self.metadata)
        return _serialize(value)


@dataclass(frozen=True)
class OrderEvent:
    event_id: str
    intent_id: str
    occurred_at: str
    from_state: Optional[str]
    to_state: str
    reason_code: str
    actor: str
    broker_order_id: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self):
        value = asdict(self); value["details"] = _sanitize_mapping(self.details)
        return _serialize(value)


@dataclass(frozen=True)
class FillEvent:
    fill_id: str
    intent_id: str
    occurred_at: str
    quantity: int
    price: Decimal
    side: str
    broker_order_id: Optional[str] = None
    broker_fill_id: Optional[str] = None
    source: str = "OBSERVED"
    raw_event_reference: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION or self.side not in SIDES or type(self.quantity) is not int or self.quantity <= 0 or self.price <= 0:
            raise ValueError("invalid fill contract")

    def to_dict(self): return _serialize(asdict(self))


@dataclass(frozen=True)
class FillApplicationRequest:
    fill_id: str
    intent_id: str
    applied: bool = False
    target: str = "PAPER_STATE"
    reason: str = "FUTURE_PAPER_EXECUTION_ENGINE_REQUIRED"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self): return asdict(self)


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal): return format(value, "f")
    if isinstance(value, dict): return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_serialize(item) for item in value]
    return value


def _sanitize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    prohibited = ("token", "secret", "password", "credential", "authorization", "cookie", "header")
    result = {}
    for key, item in list(value.items())[:32]:
        safe_key = str(key)[:64]
        if any(part in safe_key.lower() for part in prohibited): continue
        if isinstance(item, Mapping): result[safe_key] = _sanitize_mapping(item)
        elif isinstance(item, (list, tuple)): result[safe_key] = [_sanitize_mapping(entry) if isinstance(entry, Mapping) else entry[:256] if isinstance(entry, str) else entry for entry in item[:32] if isinstance(entry, (Mapping, str, int, float, bool)) or entry is None]
        elif isinstance(item, (str, int, float, bool)) or item is None: result[safe_key] = item[:256] if isinstance(item, str) else item
    return result
