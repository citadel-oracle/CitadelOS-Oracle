"""Immutable Phase-5 paper-condition, revalidation and protection contracts."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping
from types import MappingProxyType


SCHEMA_VERSION = "5.0.0"
CONDITION_POLICY_VERSION = "oracle-condition-5.0.0"
REVALIDATION_POLICY_VERSION = "oracle-revalidation-5.0.0"
PAPER_EXECUTION_POLICY_VERSION = "oracle-paper-execution-5.0.0"
GUARDIAN_POLICY_VERSION = "oracle-guardian-5.0.0"


class ConditionContractError(ValueError):
    pass


class ConditionState(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    WATCHING = "WATCHING"
    TRIGGERED = "TRIGGERED"
    REVALIDATING = "REVALIDATING"
    RISK_APPROVED = "RISK_APPROVED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    MANAGING = "MANAGING"
    EXITED = "EXITED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED_SAFE = "FAILED_SAFE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


TERMINAL_CONDITION_STATES = {
    ConditionState.EXITED, ConditionState.EXPIRED, ConditionState.CANCELLED,
    ConditionState.REJECTED, ConditionState.FAILED_SAFE,
}


def _aware(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ConditionContractError(f"{name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConditionContractError(f"{name} must be timezone-aware")
    return parsed


def _positive(value: float | int | None, name: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if isinstance(value, bool) or value is None or not math.isfinite(float(value)) or float(value) <= 0:
        raise ConditionContractError(f"{name} must be positive")


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, kw_only=True)
class SealedRecord:
    content_hash: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ConditionContractError("unsupported Phase-5 schema")
        if self.content_hash and self.content_hash != self.compute_hash():
            raise ConditionContractError("content hash mismatch")
        for value_field in fields(self):
            current = getattr(self, value_field.name)
            if isinstance(current, Mapping):
                object.__setattr__(self, value_field.name, _freeze(current))

    def to_dict(self) -> dict[str, Any]:
        return {value_field.name: _plain(getattr(self, value_field.name)) for value_field in fields(self)}

    def compute_hash(self) -> str:
        value = self.to_dict()
        value["content_hash"] = ""
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def verify_hash(self) -> bool:
        return bool(self.content_hash) and self.content_hash == self.compute_hash()


def seal(record):
    return replace(record, content_hash=record.compute_hash())


@dataclass(frozen=True, kw_only=True)
class CandleClosePredicate(SealedRecord):
    timeframe: str
    comparator: str
    level: float
    require_completed: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.timeframe not in {"1m", "3m", "5m", "15m", "1H", "4H", "1D"}:
            raise ConditionContractError("unsupported candle timeframe")
        if self.comparator not in {"ABOVE", "BELOW"} or self.require_completed is not True:
            raise ConditionContractError("completed candle comparator required")
        _positive(self.level, "candle level")


@dataclass(frozen=True, kw_only=True)
class LevelPredicate(SealedRecord):
    field: str
    comparator: str
    level: float
    tolerance: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.comparator not in {"ABOVE", "AT_OR_ABOVE", "BELOW", "AT_OR_BELOW", "WITHIN"}:
            raise ConditionContractError("invalid level comparator")
        _positive(self.level, "level")
        if self.tolerance < 0:
            raise ConditionContractError("negative tolerance")


@dataclass(frozen=True, kw_only=True)
class RetestPredicate(SealedRecord):
    level: float
    direction: str
    tolerance: float
    maximum_candles: int

    def __post_init__(self) -> None:
        super().__post_init__()
        _positive(self.level, "retest level")
        if self.direction not in {"HOLD_ABOVE", "HOLD_BELOW"} or self.tolerance < 0 or self.maximum_candles < 1:
            raise ConditionContractError("invalid retest predicate")


@dataclass(frozen=True, kw_only=True)
class PremiumConfirmationPredicate(SealedRecord):
    contract_id: str
    option_type: str
    minimum_price: float | None = None
    require_ose_confirmation: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.contract_id or self.option_type not in {"CE", "PE"}:
            raise ConditionContractError("exact option identity required")
        _positive(self.minimum_price, "minimum premium", optional=True)


@dataclass(frozen=True, kw_only=True)
class SpreadPredicate(SealedRecord):
    maximum_absolute: float
    maximum_percent: float

    def __post_init__(self) -> None:
        super().__post_init__()
        _positive(self.maximum_absolute, "maximum spread")
        _positive(self.maximum_percent, "maximum spread percent")


@dataclass(frozen=True, kw_only=True)
class FreshnessPredicate(SealedRecord):
    maximum_quote_age_seconds: float
    maximum_context_age_seconds: float

    def __post_init__(self) -> None:
        super().__post_init__()
        _positive(self.maximum_quote_age_seconds, "quote freshness")
        _positive(self.maximum_context_age_seconds, "context freshness")


@dataclass(frozen=True, kw_only=True)
class ContextPredicate(SealedRecord):
    required_direction: str
    required_vob_state: str | None = None
    required_ose_state: str | None = None
    required_argus_side: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.required_direction not in {"BULLISH", "BEARISH"}:
            raise ConditionContractError("direction must be deterministic")


@dataclass(frozen=True, kw_only=True)
class ConditionPredicateAST(SealedRecord):
    operator: str
    candle_close: CandleClosePredicate
    retest: RetestPredicate
    premium_confirmation: PremiumConfirmationPredicate
    spread: SpreadPredicate
    freshness: FreshnessPredicate
    context: ContextPredicate
    additional_levels: tuple[LevelPredicate, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.operator != "ALL":
            raise ConditionContractError("only deterministic ALL composition is supported")
        dependencies = (self.candle_close, self.retest, self.premium_confirmation, self.spread, self.freshness, self.context, *self.additional_levels)
        if any(not value.verify_hash() for value in dependencies):
            raise ConditionContractError("unsealed predicate dependency")


@dataclass(frozen=True, kw_only=True)
class ConditionExpiryPolicy(SealedRecord):
    expires_at: str
    maximum_completed_candles: int

    def __post_init__(self) -> None:
        super().__post_init__()
        _aware(self.expires_at, "expires_at")
        if self.maximum_completed_candles < 1:
            raise ConditionContractError("maximum completed candles must be positive")


@dataclass(frozen=True, kw_only=True)
class ConditionCancellationPolicy(SealedRecord):
    cancel_on_context_reversal: bool = True
    cancel_on_contract_stale: bool = True
    cancel_on_kill_switch: bool = True
    cancel_on_existing_position: bool = True


@dataclass(frozen=True, kw_only=True)
class OracleCondition(SealedRecord):
    condition_id: str
    correlation_id: str
    actor_id: str
    user_confirmed: bool
    original_user_wording: str
    predicate_ast: ConditionPredicateAST
    instrument_id: str
    security_id: str
    symbol: str
    timeframe: str
    expected_candle_close_boundary: str
    selected_option_id: str
    trigger_tolerance: float
    expiry_policy: ConditionExpiryPolicy
    cancellation_policy: ConditionCancellationPolicy
    source_decision_id: str
    source_decision_hash: str
    source_analysis_id: str
    source_analysis_hash: str
    expected_prior_version: int
    policy_versions: Mapping[str, str]
    created_at: str
    current_state: ConditionState
    paper_only: bool = True
    live_trading_enabled: bool = False
    broker_submission: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        required = (self.condition_id, self.correlation_id, self.actor_id, self.original_user_wording,
                    self.instrument_id, self.security_id, self.symbol, self.timeframe,
                    self.selected_option_id, self.source_decision_id, self.source_decision_hash,
                    self.source_analysis_id, self.source_analysis_hash)
        if any(not str(value).strip() for value in required):
            raise ConditionContractError("condition identity and lineage are required")
        if not self.user_confirmed or self.current_state is not ConditionState.WATCHING:
            raise ConditionContractError("only exact user-confirmed conditions may be armed")
        if not self.predicate_ast.verify_hash() or not self.expiry_policy.verify_hash() or not self.cancellation_policy.verify_hash():
            raise ConditionContractError("unsealed condition dependency")
        if self.predicate_ast.candle_close.timeframe != self.timeframe:
            raise ConditionContractError("cross-timeframe condition")
        if self.predicate_ast.premium_confirmation.contract_id != self.selected_option_id or self.security_id != self.selected_option_id:
            raise ConditionContractError("cross-contract condition")
        if self.trigger_tolerance < 0 or self.expected_prior_version != 0:
            raise ConditionContractError("invalid initial condition version")
        boundary = _aware(self.expected_candle_close_boundary, "expected_candle_close_boundary")
        created = _aware(self.created_at, "created_at")
        if _aware(self.expiry_policy.expires_at, "expires_at") <= created or boundary > _aware(self.expiry_policy.expires_at, "expires_at"):
            raise ConditionContractError("invalid condition time window")
        if self.paper_only is not True or self.live_trading_enabled or self.broker_submission:
            raise ConditionContractError("unsafe condition safety declaration")
        object.__setattr__(self, "symbol", self.symbol.upper())


@dataclass(frozen=True, kw_only=True)
class TriggerEvent(SealedRecord):
    trigger_id: str
    condition_id: str
    correlation_id: str
    canonical_event_id: str
    candle_id: str
    candle_timeframe: str
    candle_closed_at: str
    candle_close: float
    quote_timestamp: str
    observed_at: str
    predicate_results: Mapping[str, bool]
    source_hashes: Mapping[str, str]
    non_live_fixture: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if not all((self.trigger_id, self.condition_id, self.canonical_event_id, self.candle_id)):
            raise ConditionContractError("trigger identity required")
        _aware(self.candle_closed_at, "candle_closed_at")
        _aware(self.quote_timestamp, "quote_timestamp")
        observed = _aware(self.observed_at, "observed_at")
        if _aware(self.candle_closed_at, "candle_closed_at") > observed:
            raise ConditionContractError("forming/future candle rejected")
        if not self.predicate_results or not all(self.predicate_results.values()):
            raise ConditionContractError("trigger requires all predicates")


@dataclass(frozen=True, kw_only=True)
class DynamicPaperPlan(SealedRecord):
    contract_id: str
    option_type: str
    entry_band: tuple[float, float]
    expected_entry: float
    structural_invalidation_id: str
    premium_hard_stop: float
    stop_mapping_status: str
    natural_target_ids: tuple[str, ...]
    natural_target_premiums: tuple[float, ...]
    resulting_rr: tuple[float, ...]
    estimated_round_trip_cost: float
    maximum_slippage: float

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.option_type not in {"CE", "PE"} or not self.contract_id or not self.structural_invalidation_id:
            raise ConditionContractError("dynamic plan identity incomplete")
        if len(self.entry_band) != 2 or self.entry_band[0] <= 0 or self.entry_band[0] > self.entry_band[1]:
            raise ConditionContractError("invalid entry band")
        if not self.entry_band[0] <= self.expected_entry <= self.entry_band[1]:
            raise ConditionContractError("entry outside executable band")
        if self.premium_hard_stop <= 0 or self.premium_hard_stop >= self.expected_entry:
            raise ConditionContractError("unsupported hard stop")
        if not self.natural_target_ids or len(self.natural_target_ids) != len(self.natural_target_premiums):
            raise ConditionContractError("natural targets required")
        if any(value <= self.expected_entry for value in self.natural_target_premiums):
            raise ConditionContractError("target stretching or invalid target")
        if not self.resulting_rr or len(self.resulting_rr) != len(self.natural_target_premiums):
            raise ConditionContractError("resulting RR required")
        if self.estimated_round_trip_cost < 0 or self.maximum_slippage < 0:
            raise ConditionContractError("negative cost")


@dataclass(frozen=True, kw_only=True)
class RevalidationRequest(SealedRecord):
    request_id: str
    condition_id: str
    trigger_id: str
    source_condition_hash: str
    requested_at: str
    policy_version: str = REVALIDATION_POLICY_VERSION

    def __post_init__(self) -> None:
        super().__post_init__()
        _aware(self.requested_at, "requested_at")
        if not all((self.request_id, self.condition_id, self.trigger_id, self.source_condition_hash)):
            raise ConditionContractError("revalidation lineage required")


@dataclass(frozen=True, kw_only=True)
class RevalidationResult(SealedRecord):
    revalidation_id: str
    request_id: str
    condition_id: str
    trigger_id: str
    fresh_analysis_id: str
    fresh_analysis_hash: str
    fresh_decision_id: str
    fresh_decision_hash: str
    passed: bool
    material_drift: tuple[str, ...]
    checks: Mapping[str, bool]
    dynamic_plan: DynamicPaperPlan | None
    completed_at: str
    execution_authority: bool = False
    historical_probability_used: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        _aware(self.completed_at, "completed_at")
        if self.execution_authority or self.historical_probability_used:
            raise ConditionContractError("revalidation is not authorization")
        if self.passed != (not self.material_drift and bool(self.checks) and all(self.checks.values())):
            raise ConditionContractError("revalidation result inconsistent")
        if self.passed != (self.dynamic_plan is not None):
            raise ConditionContractError("passing result requires dynamic plan")
        if self.dynamic_plan and not self.dynamic_plan.verify_hash():
            raise ConditionContractError("unsealed dynamic plan")


@dataclass(frozen=True, kw_only=True)
class PaperOrderRequest(SealedRecord):
    order_request_id: str
    condition_id: str
    revalidation_id: str
    decision_id: str
    contract_id: str
    exchange_segment: str
    expiry: str
    strike: float
    symbol: str
    option_type: str
    side: str
    quantity: int
    lot_size: int
    order_type: str
    limit_price: float
    executable_price_band: tuple[float, float]
    stop_price: float
    target_prices: tuple[float, ...]
    estimated_maximum_loss: float
    market_data_timestamp: str
    expires_at: str
    idempotency_key: str
    paper_only: bool = True
    live_trading_enabled: bool = False
    broker_submission: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.side != "BUY" or self.option_type not in {"CE", "PE"}:
            raise ConditionContractError("Phase-5 entry must be an option buy")
        if not self.contract_id or not self.exchange_segment or not self.expiry:
            raise ConditionContractError("exact option identity incomplete")
        _positive(self.strike, "strike")
        if self.order_type not in {"LIMIT", "MARKETABLE_LIMIT"}:
            raise ConditionContractError("unsupported paper order type")
        if type(self.quantity) is not int or type(self.lot_size) is not int or self.quantity <= 0 or self.lot_size <= 0 or self.quantity % self.lot_size:
            raise ConditionContractError("quantity must be whole lots")
        _positive(self.limit_price, "limit price")
        _positive(self.stop_price, "stop price")
        if self.stop_price >= self.limit_price or not self.target_prices:
            raise ConditionContractError("invalid stop/targets")
        if self.executable_price_band[0] <= 0 or self.executable_price_band[0] > self.executable_price_band[1] or not self.executable_price_band[0] <= self.limit_price <= self.executable_price_band[1]:
            raise ConditionContractError("invalid executable band")
        expected_loss = (self.limit_price - self.stop_price) * self.quantity
        if not math.isclose(expected_loss, self.estimated_maximum_loss, rel_tol=1e-6, abs_tol=0.01):
            raise ConditionContractError("maximum loss mismatch")
        if _aware(self.expires_at, "expires_at") <= _aware(self.market_data_timestamp, "market_data_timestamp"):
            raise ConditionContractError("order authorization window invalid")
        if self.paper_only is not True or self.live_trading_enabled or self.broker_submission:
            raise ConditionContractError("unsafe order request")


@dataclass(frozen=True, kw_only=True)
class ProtectionPlan(SealedRecord):
    protection_id: str
    condition_id: str
    position_id: str
    risk_grant_id: str
    initial_hard_stop: float
    current_hard_stop: float
    natural_targets: tuple[float, ...]
    structural_invalidation_id: str
    time_exit_at: str
    emergency_exit_on_stale_data: bool
    protected_quantity: int
    created_at: str
    status: str = "ACTIVE"

    def __post_init__(self) -> None:
        super().__post_init__()
        _aware(self.time_exit_at, "time_exit_at")
        _aware(self.created_at, "created_at")
        if self.initial_hard_stop <= 0 or self.current_hard_stop < self.initial_hard_stop:
            raise ConditionContractError("Guardian may not loosen stop")
        if not self.natural_targets or self.protected_quantity <= 0 or self.status not in {"ACTIVE", "EXITED", "RECONCILIATION_REQUIRED"}:
            raise ConditionContractError("invalid protection")


@dataclass(frozen=True, kw_only=True)
class ConditionStateProjection(SealedRecord):
    condition_id: str
    state: ConditionState
    version: int
    latest_event_hash: str
    trigger_id: str | None
    revalidation_id: str | None
    authorization_id: str | None
    order_id: str | None
    position_id: str | None
    protection_id: str | None
    guardian_action: str | None
    explanation: str
    updated_at: str
    paper_only: bool = True
    live_trading_enabled: bool = False
    broker_submission: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        _aware(self.updated_at, "updated_at")
        if self.version < 1 or not self.condition_id or not self.latest_event_hash:
            raise ConditionContractError("invalid state projection")
        if self.paper_only is not True or self.live_trading_enabled or self.broker_submission:
            raise ConditionContractError("unsafe projection")


def predicate_ast_from_dict(raw: Mapping[str, Any]) -> ConditionPredicateAST:
    value = dict(raw)
    value["candle_close"] = CandleClosePredicate(**value["candle_close"])
    value["retest"] = RetestPredicate(**value["retest"])
    value["premium_confirmation"] = PremiumConfirmationPredicate(**value["premium_confirmation"])
    value["spread"] = SpreadPredicate(**value["spread"])
    value["freshness"] = FreshnessPredicate(**value["freshness"])
    value["context"] = ContextPredicate(**value["context"])
    value["additional_levels"] = tuple(LevelPredicate(**row) for row in value.get("additional_levels") or ())
    return ConditionPredicateAST(**value)


def condition_from_dict(raw: Mapping[str, Any]) -> OracleCondition:
    value = dict(raw)
    value["current_state"] = ConditionState(value["current_state"])
    value["predicate_ast"] = predicate_ast_from_dict(value["predicate_ast"])
    value["expiry_policy"] = ConditionExpiryPolicy(**value["expiry_policy"])
    value["cancellation_policy"] = ConditionCancellationPolicy(**value["cancellation_policy"])
    return OracleCondition(**value)
