"""Versioned, typed records for Personal ORACLE."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional


SCHEMA_VERSION = 3
VALID_SIDES = {"BUY", "SELL", "LONG", "SHORT"}
VALID_OPTION_SIDES = {"CE", "PE", "NONE", "UNKNOWN"}
VALID_INGESTION_MODES = {"EVENT_DRIVEN", "RECONCILED", "LEGACY"}
TRI_STATE = {"YES", "NO", "UNKNOWN"}
ENTRY_TIMING = {"EARLY", "ON_TIME", "LATE", "UNKNOWN"}
EXIT_TIMING = {"EARLY", "PLAN_BASED", "LATE", "UNKNOWN"}
MISTAKE_TAGS = {
    "LATE_ENTRY", "EARLY_EXIT", "CHASE_ENTRY", "STOP_NOT_RESPECTED",
    "TARGET_NOT_RESPECTED", "NO_COOLDOWN", "OVERTRADING", "SIZE_TOO_HIGH",
    "TRADE_AFTER_LOSS", "TRADE_DURING_EVENT_RISK", "TRADE_AGAINST_STRUCTURE",
    "TRADE_WITH_HIGH_UNCERTAINTY", "TRADE_WITH_HIGH_REVERSAL_RISK",
    "MANUAL_OVERRIDE", "OTHER",
}


def canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def event_id(source_type: str, source_record_id: str) -> str:
    return hashlib.sha256(f"{source_type}|{source_record_id}".encode()).hexdigest()[:24]


@dataclass(frozen=True)
class OracleEvent:
    oracle_event_id: str
    source_type: str
    source_record_id: str
    immutable_source_hash: str
    captured_at: str
    entry_at: str
    exit_at: str
    trading_date: str
    symbol: str
    instrument_id: Optional[str]
    option_side: str
    strike: Optional[float]
    expiry: Optional[str]
    side: str
    quantity: int
    raw_quantity: int
    lot_size: Optional[int]
    number_of_lots: Optional[float]
    entry_price: float
    exit_price: float
    realized_pnl: float
    realized_points: float
    holding_seconds: Optional[float]
    outcome: str
    exit_reason: Optional[str]
    r_multiple: Optional[float]
    brokerage: Optional[float]
    slippage: Optional[float]
    strategy_name: Optional[str]
    strategy_version: Optional[str]
    trade_number_of_day: Optional[int]
    weekday: str
    time_bucket: str
    market_regime: Optional[str] = None
    technical_signal: Optional[str] = None
    argus_bias: Optional[str] = None
    kronos_direction: Optional[str] = None
    athena_risk_state: Optional[str] = None
    hermes_event_risk: Optional[str] = None
    previous_trade_outcome: Optional[str] = None
    cooldown_respected: Optional[bool] = None
    early_exit: Optional[bool] = None
    late_entry: Optional[bool] = None
    mistake_tags: tuple[str, ...] = field(default_factory=tuple)
    notes_reference: Optional[str] = None
    historical_backfill: bool = False
    context_complete: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    signal_at: Optional[str] = None
    entry_reference_price: Optional[float] = None
    planned_stop_price: Optional[float] = None
    planned_target_price: Optional[float] = None
    recommended_quantity: Optional[int] = None
    technical_bias: Optional[str] = None
    kronos_core_quality: Optional[float] = None
    kronos_alpha_direction: Optional[str] = None
    kronos_alpha_uncertainty: Optional[float] = None
    kronos_alpha_reversal_risk: Optional[float] = None
    athena_recommendation: Optional[str] = None
    athena_utilization: Optional[float] = None
    setup_tag: Optional[str] = None
    strategy_id: Optional[str] = None
    strategy_family: Optional[str] = None
    asset_class: Optional[str] = None
    timeframe: Optional[str] = None
    intraday_or_positional: Optional[str] = None
    order_id: Optional[str] = None
    fill_id: Optional[str] = None
    position_id: Optional[str] = None
    contract_security_id: Optional[str] = None
    mfe: Optional[float] = None
    mae: Optional[float] = None
    entry_reason: Optional[str] = None
    rejection_reason: Optional[str] = None
    diagnostic_reason: Optional[str] = None
    manual_action_source: Optional[str] = None
    kronos_snapshot_reference: Optional[str] = None
    chronos_snapshot_reference: Optional[str] = None
    argus_snapshot_reference: Optional[str] = None
    athena_snapshot_reference: Optional[str] = None
    aegis_snapshot_reference: Optional[str] = None
    hermes_snapshot_reference: Optional[str] = None
    session_compliant: Optional[bool] = None
    configured_cooldown_seconds: Optional[float] = None
    ingestion_mode: str = "LEGACY"
    source_event_id: Optional[str] = None
    context_captured: bool = False
    context_completeness_percentage: float = 0.0
    missing_context_fields: tuple[str, ...] = field(default_factory=tuple)
    entry_context: Mapping[str, Any] = field(default_factory=dict)
    signal_price: Optional[float] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in {1, 2, SCHEMA_VERSION}:
            raise ValueError("unsupported Personal ORACLE schema version")
        if self.ingestion_mode not in VALID_INGESTION_MODES:
            raise ValueError("invalid Personal ORACLE ingestion mode")
        if not 0 <= self.context_completeness_percentage <= 100:
            raise ValueError("invalid Personal ORACLE context completeness")
        if self.side not in VALID_SIDES or self.option_side not in VALID_OPTION_SIDES:
            raise ValueError("invalid trade side")
        if self.quantity <= 0 or self.raw_quantity <= 0:
            raise ValueError("quantity must be positive")
        if datetime.fromisoformat(self.exit_at) < datetime.fromisoformat(self.entry_at):
            raise ValueError("exit precedes entry")
        if self.notes_reference and len(self.notes_reference) > 160:
            raise ValueError("notes reference exceeds safe bound")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mistake_tags"] = list(self.mistake_tags)
        value["warnings"] = list(self.warnings)
        value["missing_context_fields"] = list(self.missing_context_fields)
        value["entry_context"] = dict(self.entry_context)
        return value

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "OracleEvent":
        value = dict(raw)
        original_missing = "missing_context_fields" in value
        value["mistake_tags"] = tuple(value.get("mistake_tags") or ())
        value["warnings"] = tuple(value.get("warnings") or ())
        value["missing_context_fields"] = tuple(value.get("missing_context_fields") or ())
        value["entry_context"] = dict(value.get("entry_context") or {})
        if int(value.get("schema_version") or 1) < 3:
            value.setdefault("ingestion_mode", "LEGACY")
            value.setdefault("source_event_id", None)
            value.setdefault("context_captured", False)
            value.setdefault("context_completeness_percentage", 0.0)
            if not original_missing:
                value["missing_context_fields"] = ("ENTRY_CONTEXT_ENVELOPE",)
            value.setdefault("signal_price", None)
        return cls(**value)


@dataclass(frozen=True)
class OracleAdvisory:
    advisory_id: str
    candidate_signal_id: str
    source_event_id: str
    generated_at: str
    proposed_entry_at: str
    symbol: Optional[str]
    underlying: Optional[str]
    option_side: Optional[str]
    strike: Optional[float]
    expiry: Optional[str]
    strategy: Optional[str]
    setup: Optional[str]
    timeframe: Optional[str]
    proposed_quantity: Optional[int]
    signal_price: Optional[float]
    reference_price: Optional[float]
    proposed_stop: Optional[float]
    proposed_target: Optional[float]
    market_regime: Optional[str]
    context_completeness_percentage: float
    missing_context_fields: tuple[str, ...]
    personal_metrics: Mapping[str, Any]
    sample_sizes: Mapping[str, int]
    classification: str
    confidence_band: str
    reason_codes: tuple[str, ...]
    applicable_cohort: str
    cohort_sample_size: int
    policy_version: str
    policy_source: str
    policy_parameters: Mapping[str, Any]
    data_provenance: Mapping[str, Any]
    execution_influence: str = "ZERO"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.execution_influence != "ZERO":
            raise ValueError("Personal ORACLE advisory cannot influence execution")
        if self.classification not in {
            "INSUFFICIENT_DATA", "NORMAL_HISTORICAL_PROFILE", "PERSONAL_CAUTION",
            "HIGH_PERSONAL_RISK", "POSITIVE_PERSONAL_FIT", "CONFLICTING_PERSONAL_EVIDENCE",
        }:
            raise ValueError("invalid Personal ORACLE advisory classification")
        if self.confidence_band not in {"UNCALIBRATED", "LOW", "MEDIUM", "HIGH"}:
            raise ValueError("invalid Personal ORACLE confidence band")
        if not 0 <= self.context_completeness_percentage <= 100:
            raise ValueError("invalid advisory context completeness")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["missing_context_fields"] = list(self.missing_context_fields)
        value["reason_codes"] = list(self.reason_codes)
        value["personal_metrics"] = dict(self.personal_metrics)
        value["sample_sizes"] = dict(self.sample_sizes)
        value["policy_parameters"] = dict(self.policy_parameters)
        value["data_provenance"] = dict(self.data_provenance)
        return value

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "OracleAdvisory":
        value = dict(raw)
        value["missing_context_fields"] = tuple(value.get("missing_context_fields") or ())
        value["reason_codes"] = tuple(value.get("reason_codes") or ())
        value["personal_metrics"] = dict(value.get("personal_metrics") or {})
        value["sample_sizes"] = dict(value.get("sample_sizes") or {})
        value["policy_parameters"] = dict(value.get("policy_parameters") or {})
        value["data_provenance"] = dict(value.get("data_provenance") or {})
        return cls(**value)


@dataclass(frozen=True)
class OracleOutcomeEvaluation:
    outcome_evaluation_id: str
    advisory_id: str
    candidate_signal_id: str
    source_trade_id: str
    linked_at: str
    realized_pnl: float
    outcome: str
    holding_seconds: Optional[float]
    mae: Optional[float]
    mfe: Optional[float]
    reason_evaluations: Mapping[str, str]
    execution_influence: str = "ZERO"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.execution_influence != "ZERO":
            raise ValueError("Personal ORACLE outcome cannot influence execution")
        if self.outcome not in {"WIN", "LOSS", "BREAKEVEN"}:
            raise ValueError("invalid Personal ORACLE outcome")
        if any(value not in {"SUPPORTED", "UNSUPPORTED", "UNVERIFIABLE"} for value in self.reason_evaluations.values()):
            raise ValueError("invalid advisory reason evaluation")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reason_evaluations"] = dict(self.reason_evaluations)
        return value

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "OracleOutcomeEvaluation":
        value = dict(raw)
        value["reason_evaluations"] = dict(value.get("reason_evaluations") or {})
        return cls(**value)


@dataclass(frozen=True)
class ManualJournalRecord:
    """Typed import contract only; this milestone exposes no write route."""

    external_id: str
    entry_at: str
    exit_at: str
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    realized_pnl: float
    option_side: str = "UNKNOWN"
    notes_reference: Optional[str] = None


@dataclass(frozen=True)
class BehavioralEnrichment:
    enrichment_id: str
    oracle_event_id: str
    reviewed_at: str
    reviewed_by_user: bool
    followed_plan: str = "UNKNOWN"
    stop_respected: str = "UNKNOWN"
    target_respected: str = "UNKNOWN"
    cooldown_respected: str = "UNKNOWN"
    mistake_tags: tuple[str, ...] = field(default_factory=tuple)
    setup_tags: tuple[str, ...] = field(default_factory=tuple)
    confidence_before_trade: Optional[float] = None
    confidence_after_trade: Optional[float] = None
    notes_reference: Optional[str] = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        for value in (self.followed_plan, self.stop_respected, self.target_respected, self.cooldown_respected):
            if value not in TRI_STATE:
                raise ValueError("invalid behavioral tri-state")
        if any(tag not in MISTAKE_TAGS for tag in self.mistake_tags):
            raise ValueError("invalid mistake tag")
        if len(self.mistake_tags) > 12 or len(self.setup_tags) > 12:
            raise ValueError("too many enrichment tags")
        if any(len(tag) > 48 or not tag.replace("_", "").replace("-", "").isalnum() for tag in self.setup_tags):
            raise ValueError("unsafe setup tag")
        if self.notes_reference and (len(self.notes_reference) > 160 or any(ch in self.notes_reference for ch in "\r\n\t")):
            raise ValueError("unsafe notes reference")
        for confidence in (self.confidence_before_trade, self.confidence_after_trade):
            if confidence is not None and not 0 <= confidence <= 100:
                raise ValueError("confidence must be between 0 and 100")
        datetime.fromisoformat(self.reviewed_at)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mistake_tags"] = list(self.mistake_tags)
        value["setup_tags"] = list(self.setup_tags)
        return value

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "BehavioralEnrichment":
        value = dict(raw)
        value["mistake_tags"] = tuple(value.get("mistake_tags") or ())
        value["setup_tags"] = tuple(value.get("setup_tags") or ())
        return cls(**value)


@dataclass(frozen=True)
class BehavioralObservation:
    oracle_event_id: str
    followed_plan: str = "UNKNOWN"
    stop_respected: str = "UNKNOWN"
    target_respected: str = "UNKNOWN"
    cooldown_respected: str = "UNKNOWN"
    entry_timing: str = "UNKNOWN"
    entry_distance_from_reference: Optional[float] = None
    signal_to_entry_delay_seconds: Optional[float] = None
    chase_entry: str = "UNKNOWN"
    exit_timing: str = "UNKNOWN"
    early_exit: str = "UNKNOWN"
    stop_moved: str = "UNKNOWN"
    target_moved: str = "UNKNOWN"
    trade_number_of_day: Optional[int] = None
    previous_trade_result: Optional[str] = None
    minutes_since_previous_trade: Optional[float] = None
    after_loss: str = "NO"
    after_consecutive_losses: int = 0
    same_direction_repeat: Optional[bool] = None
    same_setup_repeat: Optional[bool] = None
    size_multiplier_used: Optional[float] = None
    exceeded_recommended_size: str = "UNKNOWN"
    entered_during_athena_pause: str = "UNKNOWN"
    entered_near_daily_limit: str = "UNKNOWN"
    entered_against_technical_bias: str = "UNKNOWN"
    entered_against_argus: str = "UNKNOWN"
    entered_with_weak_kronos_core: str = "UNKNOWN"
    entered_with_weak_kronos_alpha: str = "UNKNOWN"
    entered_during_hermes_wait: str = "UNKNOWN"
    entered_during_high_uncertainty: str = "UNKNOWN"
    entered_during_high_reversal_risk: str = "UNKNOWN"
    mistake_tags: tuple[str, ...] = field(default_factory=tuple)
    setup_tags: tuple[str, ...] = field(default_factory=tuple)
    reviewed_by_user: bool = False
    coverage_count: int = 0
    observable_field_count: int = 16
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mistake_tags"] = list(self.mistake_tags)
        value["setup_tags"] = list(self.setup_tags)
        value["reason_codes"] = list(self.reason_codes)
        return value


@dataclass(frozen=True)
class OracleClassification:
    classification_id: str
    source_event_id: str
    classification_type: str
    evidence: Mapping[str, Any]
    confidence: float
    evidence_quality: str
    generated_at: str
    classifier_version: str = "PERSONAL_ORACLE_LITE_V1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "OracleClassification":
        value = dict(raw)
        value["evidence"] = dict(value.get("evidence") or {})
        return cls(**value)


@dataclass(frozen=True)
class OracleObservation:
    observation_id: str
    version: int
    title: str
    summary: str
    category: str
    severity: str
    confidence: float
    sample_size: int
    affected_strategy_count: int
    affected_strategy_ids: tuple[str, ...]
    strategy_family: Optional[str]
    actual_realized_impact: Optional[float]
    hypothetical_impact: Optional[float]
    first_detected_at: str
    last_updated_at: str
    evidence_references: tuple[str, ...]
    status: str = "NEW"
    execution_influence: str = "ZERO"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["affected_strategy_ids"] = list(self.affected_strategy_ids)
        value["evidence_references"] = list(self.evidence_references)
        return value

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "OracleObservation":
        value = dict(raw)
        value["affected_strategy_ids"] = tuple(value.get("affected_strategy_ids") or ())
        value["evidence_references"] = tuple(value.get("evidence_references") or ())
        return cls(**value)
