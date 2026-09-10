"""Typed, versioned AEGIS input and output contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


SCHEMA_VERSION = 1
DECISIONS = {"APPROVE", "APPROVE_REDUCED", "WAIT", "REJECT", "BLOCK"}
SIDES = {"CE", "PE", "LONG", "SHORT", "NONE"}


def fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class StrategyEligibility:
    strategy_id: str
    strategy_name: str
    strategy_version: Optional[str]
    enabled: bool
    eligible: bool
    allowed_symbols: tuple[str, ...]
    allowed_timeframes: tuple[str, ...]
    allowed_sessions: tuple[str, ...]
    allowed_regimes: tuple[str, ...]
    required_modules: tuple[str, ...]
    maximum_freshness_seconds: float
    minimum_setup_quality: float
    minimum_option_buying_quality: Optional[float]
    expiry_rules: Mapping[str, Any]
    reason_codes: tuple[str, ...]

    def to_dict(self):
        value = asdict(self)
        for key in ("allowed_symbols", "allowed_timeframes", "allowed_sessions", "allowed_regimes", "required_modules", "reason_codes"):
            value[key] = list(value[key])
        return value


@dataclass(frozen=True)
class AegisInputSnapshot:
    generated_at: str
    symbol: str
    timeframe: str
    strategy_id: str
    strategy_name: str
    strategy_version: Optional[str]
    requested_side: str
    session_state: str
    session_date: str
    technical: Mapping[str, Any]
    argus: Mapping[str, Any]
    kronos_core: Mapping[str, Any]
    kronos_alpha: Mapping[str, Any]
    athena: Mapping[str, Any]
    hermes: Mapping[str, Any]
    personal_oracle: Mapping[str, Any]
    risk_authorization: Mapping[str, Any]
    kill_switch_active: Optional[bool]
    kill_switch_state: str
    live_trading_enabled: Optional[bool]
    live_path_requested: bool
    paper_state_health: str
    market_data_freshness: str
    duplicate_request: bool
    strategy_eligibility: StrategyEligibility
    required_input_presence: Mapping[str, bool]
    source_timestamps: Mapping[str, Optional[str]]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION or self.requested_side not in SIDES:
            raise ValueError("invalid AEGIS input contract")

    def semantic_dict(self):
        value = asdict(self)
        value.pop("generated_at", None)
        value.pop("source_timestamps", None)
        value.get("kronos_core", {}).pop("signal_age", None)
        value.get("hermes", {}).pop("freshness", None)
        return value

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class AegisConflict:
    conflict_id: str
    modules: tuple[str, ...]
    description: str
    severity: str
    resolution: str
    score_impact: float
    reason_codes: tuple[str, ...]

    def to_dict(self):
        value = asdict(self)
        value["modules"] = list(self.modules)
        value["reason_codes"] = list(self.reason_codes)
        return value


@dataclass(frozen=True)
class AegisDecision:
    decision_id: str
    generated_at: str
    symbol: str
    timeframe: str
    strategy_id: str
    strategy_name: str
    strategy_version: Optional[str]
    requested_side: str
    decision: str
    decision_score: Optional[float]
    decision_quality: str
    data_coverage_percentage: float
    hard_gate_status: str
    hard_gate_reasons: tuple[str, ...]
    hard_gate_details: Mapping[str, Any]
    component_scores: Mapping[str, Optional[float]]
    weighted_contributions: Mapping[str, Optional[float]]
    component_details: Mapping[str, Any]
    conflicts: tuple[AegisConflict, ...]
    recommended_size_multiplier: float
    dominant_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    maturity: str
    advisory_only: bool
    execution_permission: bool
    risk_authorization_required: bool
    live_trading_enabled: Optional[bool]
    source_timestamps: Mapping[str, Optional[str]]
    input_fingerprint: str
    input_snapshot: Mapping[str, Any]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if self.decision not in DECISIONS or self.execution_permission or not self.advisory_only:
            raise ValueError("unsafe AEGIS decision contract")
        if not 0 <= self.recommended_size_multiplier <= 1:
            raise ValueError("invalid AEGIS size multiplier")

    def to_dict(self):
        value = asdict(self)
        for key in ("hard_gate_reasons", "dominant_reasons", "warnings", "missing_inputs"):
            value[key] = list(value[key])
        value["conflicts"] = [item.to_dict() for item in self.conflicts]
        recommendation = {
            "APPROVE": "NORMAL", "APPROVE_REDUCED": "CAUTION",
            "WAIT": "PAUSE", "REJECT": "REJECT", "BLOCK": "REJECT",
        }[self.decision]
        stale = str(self.input_snapshot.get("market_data_freshness") or "UNAVAILABLE").upper() == "STALE"
        unavailable = bool(self.missing_inputs)
        value.update({
            "mode": "ADVISORY",
            "recommendation": recommendation,
            "would_recommend": recommendation,
            "recommendation_is_execution_decision": False,
            "execution_influence": "ZERO",
            "calculation_timestamp": self.generated_at,
            "input_snapshot_version": self.input_snapshot.get("schema_version"),
            "input_status": "UNAVAILABLE" if unavailable else "STALE" if stale else "AVAILABLE",
            "freshness": "UNAVAILABLE" if unavailable else "STALE" if stale else "FRESH",
            "stale_reason": "AEGIS_INPUT_MARKET_DATA_STALE" if stale else None,
            "unavailable_reason": "AEGIS_REQUIRED_INPUT_UNAVAILABLE" if unavailable else None,
        })
        return value
