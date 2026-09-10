"""Immutable Phase-3 Oracle intelligence, evidence and decision contracts."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from enum import Enum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

from src.oracle.contracts.perception import Availability, FreshnessState, VerifiedVisualClaim, record_from_dict as perception_from_dict


SCHEMA_VERSION = "3.0.0"


class AnalysisContractError(ValueError):
    pass


def _aware(value: str, name: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise AnalysisContractError(f"{name} must be ISO-8601") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise AnalysisContractError(f"{name} must be timezone-aware")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True, kw_only=True)
class AnalysisRecord:
    correlation_id: str
    snapshot_id: str
    decision_id: str | None
    instrument_id: str
    security_id: str
    symbol: str
    timeframe: str
    source_timestamp: str
    generated_at: str
    as_of: str
    availability: Availability
    freshness_state: FreshnessState
    source_ids: Mapping[str, str]
    source_hashes: Mapping[str, str]
    dependency_versions: Mapping[str, str]
    provenance: Mapping[str, Any]
    missing_evidence: tuple[str, ...] = ()
    contradictory_evidence: tuple[str, ...] = ()
    content_hash: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("correlation_id", "snapshot_id", "instrument_id", "security_id", "symbol", "timeframe"):
            if not str(getattr(self, name)).strip():
                raise AnalysisContractError(f"{name} is required")
        source = _aware(self.source_timestamp, "source_timestamp")
        generated = _aware(self.generated_at, "generated_at")
        as_of = _aware(self.as_of, "as_of")
        if source > generated or as_of > generated:
            raise AnalysisContractError("future source/as_of timestamp")
        if not self.source_ids or not self.source_hashes or not self.dependency_versions or not self.provenance:
            raise AnalysisContractError("lineage metadata is required")
        object.__setattr__(self, "symbol", self.symbol.upper())
        for name in ("source_ids", "source_hashes", "dependency_versions", "provenance"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        if self.content_hash and self.content_hash != self.compute_hash():
            raise AnalysisContractError("content hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}

    def compute_hash(self) -> str:
        value = self.to_dict()
        value["content_hash"] = ""
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    def verify_hash(self) -> bool:
        return bool(self.content_hash) and self.content_hash == self.compute_hash()


def seal(record: AnalysisRecord):
    return replace(record, content_hash=record.compute_hash())


@dataclass(frozen=True, kw_only=True)
class OptionContractQuote(AnalysisRecord):
    contract_id: str
    trading_symbol: str
    expiry: str
    strike: float
    option_type: str
    bid: float | None
    ask: float | None
    mid: float | None
    ltp: float | None
    spread_abs: float | None
    spread_pct: float | None
    bid_depth: int | None
    ask_depth: int | None
    volume: int | None
    oi: int | None
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    distance_atm: float | None
    authority_rank: int | None
    authority_score: float | None
    authority_status: str
    rejection_reason: str | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.contract_id or not self.expiry or not self.trading_symbol or self.option_type not in {"CE", "PE"}:
            raise AnalysisContractError("option contract identity is required")
        if self.strike <= 0 or self.security_id != self.contract_id:
            raise AnalysisContractError("cross-contract identity mismatch")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise AnalysisContractError("crossed option quote")


@dataclass(frozen=True, kw_only=True)
class StructuralTrigger(AnalysisRecord):
    trigger_id: str
    trigger_type: str
    direction: str
    level: float | None
    predicate: Mapping[str, Any]
    status: str

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "predicate", _freeze(self.predicate))


@dataclass(frozen=True, kw_only=True)
class StructuralInvalidation(AnalysisRecord):
    invalidation_id: str
    invalidation_type: str
    direction: str
    level: float | None
    predicate: Mapping[str, Any]
    mapping_status: str

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "predicate", _freeze(self.predicate))


@dataclass(frozen=True, kw_only=True)
class NaturalTarget(AnalysisRecord):
    target_id: str
    target_type: str
    direction: str
    level: float
    authority: str


@dataclass(frozen=True, kw_only=True)
class ExecutionEstimate(AnalysisRecord):
    contract_id: str
    expected_entry: float | None
    entry_band: tuple[float, float] | None
    estimated_one_way_slippage: float | None
    estimated_round_trip_cost: float | None
    premium_hard_stop_candidate: float | None
    stop_mapping_status: str
    target_premiums: tuple[float, ...]
    resulting_rr: tuple[float, ...]
    executable: bool
    blockers: tuple[str, ...]
    components: Mapping[str, Any]

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "components", _freeze(self.components))


@dataclass(frozen=True, kw_only=True)
class AnalysisSnapshot(AnalysisRecord):
    analysis_id: str
    context_snapshot_id: str
    context_hash: str
    lane_hashes: Mapping[str, str]
    expiry: str | None
    market_state: str
    time_remaining_seconds: float | None
    source_states: Mapping[str, str]
    source_timestamps: Mapping[str, str]
    source_records: Mapping[str, Any]
    visual_claims: tuple[VerifiedVisualClaim, ...]
    candidate_contracts: tuple[OptionContractQuote, ...]
    compatible: bool
    compatibility_reasons: tuple[str, ...]
    data_completeness: int

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.analysis_id != self.snapshot_id or not self.context_snapshot_id or not self.context_hash:
            raise AnalysisContractError("analysis/context identity mismatch")
        if not 0 <= self.data_completeness <= 100:
            raise AnalysisContractError("data completeness must be 0..100")
        if any(not claim.verify_hash() or claim.symbol != self.symbol for claim in self.visual_claims):
            raise AnalysisContractError("invalid visual claim dependency")
        if any(not quote.verify_hash() or quote.symbol != self.symbol or (self.expiry and quote.expiry != self.expiry) for quote in self.candidate_contracts):
            raise AnalysisContractError("invalid option contract dependency")
        for name in ("lane_hashes", "source_states", "source_timestamps", "source_records"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True, kw_only=True)
class UnderlyingAssessment(AnalysisRecord):
    assessment_id: str
    directional_posture: str
    location_quality: str
    permitted_thesis_types: tuple[str, ...]
    blockers: tuple[str, ...]
    triggers: tuple[StructuralTrigger, ...]
    invalidations: tuple[StructuralInvalidation, ...]
    natural_targets: tuple[NaturalTarget, ...]
    setup_quality: int
    score_components: Mapping[str, float]

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0 <= self.setup_quality <= 100:
            raise AnalysisContractError("setup quality must be 0..100")
        if any(not value.verify_hash() or value.snapshot_id != self.snapshot_id for value in (*self.triggers, *self.invalidations, *self.natural_targets)):
            raise AnalysisContractError("invalid structural dependency")
        object.__setattr__(self, "score_components", _freeze(self.score_components))


@dataclass(frozen=True, kw_only=True)
class TimingAssessment(AnalysisRecord):
    assessment_id: str
    timing_state: str
    trigger_satisfied: bool
    entry_extended: bool
    opportunity_expired: bool
    blockers: tuple[str, ...]
    score: int
    score_components: Mapping[str, float]

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0 <= self.score <= 100:
            raise AnalysisContractError("timing score must be 0..100")
        object.__setattr__(self, "score_components", _freeze(self.score_components))


@dataclass(frozen=True, kw_only=True)
class OptionCaptureAssessment(AnalysisRecord):
    assessment_id: str
    option_state: str
    requested_side: str | None
    selected_contract_id: str | None
    eligible_contract_ids: tuple[str, ...]
    rejected_contracts: Mapping[str, tuple[str, ...]]
    execution_estimate: ExecutionEstimate | None
    blockers: tuple[str, ...]
    execution_quality: int
    score_components: Mapping[str, float]

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0 <= self.execution_quality <= 100:
            raise AnalysisContractError("execution quality must be 0..100")
        if self.execution_estimate and (not self.execution_estimate.verify_hash() or self.execution_estimate.contract_id != self.selected_contract_id):
            raise AnalysisContractError("execution estimate dependency mismatch")
        object.__setattr__(self, "rejected_contracts", _freeze(self.rejected_contracts))
        object.__setattr__(self, "score_components", _freeze(self.score_components))


@dataclass(frozen=True, kw_only=True)
class EvidenceItem(AnalysisRecord):
    evidence_id: str
    claim: str
    source: str
    source_record_id: str
    source_record_hash: str
    classification: str
    materiality: str
    explanation: str
    numerical_values: Mapping[str, Any]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.classification not in {"SUPPORT", "CONTRADICT", "MISSING"}:
            raise AnalysisContractError("invalid evidence classification")
        object.__setattr__(self, "numerical_values", _freeze(self.numerical_values))


@dataclass(frozen=True, kw_only=True)
class EvidenceConflict(AnalysisRecord):
    conflict_id: str
    claim: str
    source_record_ids: tuple[str, ...]
    severity: str
    explanation: str
    resolution: str


@dataclass(frozen=True, kw_only=True)
class EvidenceBundle(AnalysisRecord):
    bundle_id: str
    items: tuple[EvidenceItem, ...]
    conflicts: tuple[EvidenceConflict, ...]
    supporting_count: int
    contradicting_count: int
    missing_count: int
    data_completeness: int
    evidence_agreement: int
    visual_certainty: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if any(not value.verify_hash() for value in (*self.items, *self.conflicts)):
            raise AnalysisContractError("invalid evidence dependency")
        if not 0 <= self.data_completeness <= 100 or not 0 <= self.evidence_agreement <= 100:
            raise AnalysisContractError("evidence quality must be 0..100")


@dataclass(frozen=True, kw_only=True)
class OracleDecisionEnvelope(AnalysisRecord):
    action: str
    policy_version: str
    analysis_snapshot_hash: str
    assessment_hashes: Mapping[str, str]
    evidence_bundle_id: str
    evidence_bundle_hash: str
    selected_contract_id: str | None
    contract_label: str | None
    setup_quality: int
    score_components: Mapping[str, Any]
    visual_certainty: str
    data_completeness: int
    execution_quality: int
    evidence_agreement: int
    calibration_status: str
    historical_probability: None
    trigger_summary: str | None
    entry_band: tuple[float, float] | None
    structural_invalidation_id: str | None
    premium_hard_stop_candidate: float | None
    stop_mapping_status: str
    target_ids: tuple[str, ...]
    target_premiums: tuple[float, ...]
    resulting_rr: tuple[float, ...]
    estimated_cost: float | None
    why: str
    risk: str
    reason_codes: tuple[str, ...]
    blockers: tuple[str, ...]
    execution_authority: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.action not in {"BUY", "WAIT", "NO_TRADE"}:
            raise AnalysisContractError("invalid Phase-3 decision")
        if self.execution_authority is not False:
            raise AnalysisContractError("Decision Envelope cannot own execution authority")
        if self.historical_probability is not None or self.calibration_status != "NOT_AVAILABLE":
            raise AnalysisContractError("Phase-3 probability/calibration unavailable")
        for value in (self.setup_quality, self.data_completeness, self.execution_quality, self.evidence_agreement):
            if not 0 <= value <= 100:
                raise AnalysisContractError("quality field must be 0..100")
        object.__setattr__(self, "assessment_hashes", _freeze(self.assessment_hashes))
        object.__setattr__(self, "score_components", _freeze(self.score_components))


def record_from_dict(record_type, raw: Mapping[str, Any]):
    """Strict durable recovery for nested Phase-3 records."""
    value = dict(raw)
    value["availability"] = Availability(value["availability"])
    value["freshness_state"] = FreshnessState(value["freshness_state"])
    if record_type is AnalysisSnapshot:
        value["visual_claims"] = tuple(perception_from_dict(VerifiedVisualClaim, row) for row in value.get("visual_claims") or ())
        value["candidate_contracts"] = tuple(record_from_dict(OptionContractQuote, row) for row in value.get("candidate_contracts") or ())
    if record_type is UnderlyingAssessment:
        value["triggers"] = tuple(record_from_dict(StructuralTrigger, row) for row in value.get("triggers") or ())
        value["invalidations"] = tuple(record_from_dict(StructuralInvalidation, row) for row in value.get("invalidations") or ())
        value["natural_targets"] = tuple(record_from_dict(NaturalTarget, row) for row in value.get("natural_targets") or ())
    if record_type is OptionCaptureAssessment and isinstance(value.get("execution_estimate"), Mapping):
        value["execution_estimate"] = record_from_dict(ExecutionEstimate, value["execution_estimate"])
    if record_type is EvidenceBundle:
        value["items"] = tuple(record_from_dict(EvidenceItem, row) for row in value.get("items") or ())
        value["conflicts"] = tuple(record_from_dict(EvidenceConflict, row) for row in value.get("conflicts") or ())
    return record_type(**value)
