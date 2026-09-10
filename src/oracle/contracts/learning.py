"""Immutable Phase-4 knowledge, similarity and learning contracts.

These records are explanatory only.  They deliberately carry no risk, mission,
condition, order, position or Guardian authority.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = "4.0.0"
_HASH = re.compile(r"^[0-9a-f]{64}$")


class LearningContractError(ValueError):
    pass


class ValidationStatus(str, Enum):
    HYPOTHESIS = "HYPOTHESIS"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    SOURCE_BACKED_UNVALIDATED = "SOURCE_BACKED_UNVALIDATED"
    USER_PROVIDED_UNVALIDATED = "USER_PROVIDED_UNVALIDATED"
    INTERNALLY_VALIDATED = "INTERNALLY_VALIDATED"
    CONFLICTED = "CONFLICTED"
    FUTURE_DATA_DEPENDENT = "FUTURE_DATA_DEPENDENT"
    PENDING_SOURCE = "PENDING_SOURCE"
    CONTRADICTED = "CONTRADICTED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


class CalibrationState(str, Enum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    IN_SAMPLE_ONLY = "IN_SAMPLE_ONLY"
    OOS_UNCALIBRATED = "OOS_UNCALIBRATED"
    OOS_CALIBRATED_WEAK = "OOS_CALIBRATED_WEAK"
    OOS_CALIBRATED = "OOS_CALIBRATED"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


def _aware(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise LearningContractError(f"{name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LearningContractError(f"{name} must be timezone-aware")
    return parsed


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in sorted(value.items(), key=lambda row: str(row[0]))})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


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


@dataclass(frozen=True, kw_only=True)
class ImmutableLearningRecord:
    record_id: str
    version: str
    created_at: str
    provenance: Mapping[str, Any]
    content_hash: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.record_id.strip() or not self.version.strip() or not self.provenance:
            raise LearningContractError("record identity, version and provenance are required")
        _aware(self.created_at, "created_at")
        object.__setattr__(self, "provenance", _freeze(self.provenance))
        if self.content_hash and (not _HASH.fullmatch(self.content_hash) or self.content_hash != self.compute_hash()):
            raise LearningContractError("content hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}

    def compute_hash(self) -> str:
        value = self.to_dict()
        value["content_hash"] = ""
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def verify_hash(self) -> bool:
        return bool(self.content_hash) and self.content_hash == self.compute_hash()


def seal(record: ImmutableLearningRecord):
    return replace(record, content_hash=record.compute_hash())


@dataclass(frozen=True, kw_only=True)
class CitationLocator:
    source_id: str
    source_version: str
    document_hash: str
    locator: str
    chapter: str | None = None
    section: str | None = None
    page: str | None = None
    paragraph: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_version.strip() or not self.locator.strip():
            raise LearningContractError("exact citation locator is required")
        if not _HASH.fullmatch(self.document_hash):
            raise LearningContractError("citation document hash is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, kw_only=True)
class ExcerptPolicy:
    policy_id: str
    excerpt_allowed: bool
    maximum_words: int
    attribution_required: bool = True
    full_text_runtime_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.policy_id or self.maximum_words < 0 or self.maximum_words > 50:
            raise LearningContractError("invalid excerpt policy")
        if not self.excerpt_allowed and self.maximum_words != 0:
            raise LearningContractError("disabled excerpts must have a zero word limit")
        if self.full_text_runtime_allowed:
            raise LearningContractError("whole-source runtime loading is forbidden")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, kw_only=True)
class KnowledgeSourceManifest(ImmutableLearningRecord):
    source_id: str
    title: str
    author_organisation: str
    edition_version: str
    publication_date: str | None
    source_type: str
    document_hash: str
    source_location: str
    ingestion_status: str
    excerpt_policy: ExcerptPolicy
    validation_status: ValidationStatus
    stable_locators: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.source_type not in {"BOOK", "PAPER", "OFFICIAL_DOCUMENTATION", "INTERNAL_EVIDENCE", "USER_PROVIDED"}:
            raise LearningContractError("unsupported knowledge source type")
        if not all(str(v).strip() for v in (self.source_id, self.title, self.author_organisation, self.edition_version, self.source_location)):
            raise LearningContractError("complete source manifest identity is required")
        if not self.stable_locators or any(not str(value).strip() for value in self.stable_locators):
            raise LearningContractError("source manifest requires stable citation locators")
        if not _HASH.fullmatch(self.document_hash) or self.ingestion_status != "VERIFIED":
            raise LearningContractError("source must be hash-pinned and verified")


@dataclass(frozen=True, kw_only=True)
class KnowledgeCardReference:
    card_id: str
    card_version: str
    card_hash: str
    validation_status: ValidationStatus
    citation: CitationLocator
    relevance: str

    def __post_init__(self) -> None:
        if not self.card_id or not self.relevance or not _HASH.fullmatch(self.card_hash):
            raise LearningContractError("invalid knowledge card reference")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, kw_only=True)
class KnowledgeConflict:
    conflict_id: str
    card_ids: tuple[str, ...]
    materiality: str
    explanation: str

    def __post_init__(self) -> None:
        if len(self.card_ids) < 2 or self.materiality not in {"DISCLOSURE", "MATERIAL"} or not self.explanation:
            raise LearningContractError("invalid knowledge conflict")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, kw_only=True)
class KnowledgeCard(ImmutableLearningRecord):
    card_id: str
    source_id: str
    concept: str
    principle: str
    required_evidence: tuple[str, ...]
    valid_conditions: tuple[str, ...]
    failure_conditions: tuple[str, ...]
    contradictions: tuple[str, ...]
    when_not_to_use: tuple[str, ...]
    option_buying_relevance: str
    relevant_timeframes: tuple[str, ...]
    relevant_citadel_fields: tuple[str, ...]
    citation: CitationLocator
    permitted_excerpt: str | None
    paraphrased_interpretation: str
    validation_status: ValidationStatus
    linked_empirical_evidence_ids: tuple[str, ...]
    domains: tuple[str, ...]
    regimes: tuple[str, ...] = ()
    setup_types: tuple[str, ...] = ()
    contradicts_card_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.card_id != self.record_id or self.source_id != self.citation.source_id:
            raise LearningContractError("knowledge card source identity mismatch")
        if not all((self.concept, self.principle, self.required_evidence, self.failure_conditions,
                    self.when_not_to_use, self.paraphrased_interpretation, self.relevant_citadel_fields)):
            raise LearningContractError("knowledge card evidence and failure boundaries are required")


@dataclass(frozen=True, kw_only=True)
class KnowledgeRetrievalQuery(ImmutableLearningRecord):
    instrument: str
    setup_type: str | None
    market_regime: str | None
    timeframe: str | None
    option_buying_relevance: str | None
    current_evidence_claims: tuple[str, ...]
    question: str
    allowed_validation_statuses: tuple[ValidationStatus, ...]
    maximum_cards: int = 5

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.instrument or not self.question or not 1 <= self.maximum_cards <= 5:
            raise LearningContractError("bounded knowledge query is required")


@dataclass(frozen=True, kw_only=True)
class KnowledgeRetrievalResult(ImmutableLearningRecord):
    query_hash: str
    vault_version: str
    vault_hash: str
    card_references: tuple[KnowledgeCardReference, ...]
    conflicts: tuple[KnowledgeConflict, ...]
    omitted_count: int
    whole_source_loaded: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if not _HASH.fullmatch(self.query_hash) or not _HASH.fullmatch(self.vault_hash):
            raise LearningContractError("retrieval lineage hash is invalid")
        if len(self.card_references) > 5 or self.whole_source_loaded:
            raise LearningContractError("knowledge retrieval exceeded its live-context boundary")


@dataclass(frozen=True, kw_only=True)
class SimilarityFeatureVector(ImmutableLearningRecord):
    symbol: str
    setup_version: str
    timeframe_alignment: tuple[str, ...]
    regime: str
    location_class: str
    structural_claims: tuple[str, ...]
    vob_state: str
    ose_state: str
    argus_state: str
    option_type: str
    strike_relation: str
    expiry_bucket: str
    iv_regime: str
    delta_bucket: str
    time_of_day_bucket: str
    spread_liquidity_bucket: str
    trigger_definition_id: str
    invalidation_definition_id: str
    target_definition_ids: tuple[str, ...]
    feature_versions: Mapping[str, str]
    numerical_features: Mapping[str, float]
    observed_at: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _aware(self.observed_at, "observed_at")
        forbidden = {"outcome", "mfe", "mae", "exit", "return", "target_hit", "stop_hit"}
        keys = {str(k).lower() for k in self.numerical_features} | {str(k).lower() for k in self.feature_versions}
        if any(any(token in key for token in forbidden) for key in keys):
            raise LearningContractError("outcome-derived/future feature is forbidden")
        object.__setattr__(self, "feature_versions", _freeze(self.feature_versions))
        object.__setattr__(self, "numerical_features", _freeze(self.numerical_features))


@dataclass(frozen=True, kw_only=True)
class OutcomeDefinition(ImmutableLearningRecord):
    outcome_definition_id: str
    decision_policy_version: str
    target_definition: str
    stop_definition: str
    evaluation_window: str
    tie_break_policy: str
    include_costs: bool
    required_metrics: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        required = {"TARGET_BEFORE_STOP", "STOP_BEFORE_TARGET", "NEITHER", "MFE", "MAE", "TIME_TO_TARGET", "TIME_TO_STOP", "AFTER_COST_RETURN", "SLIPPAGE", "INVALIDATION_TIMING", "PREMIUM_RESPONSE"}
        if self.outcome_definition_id != self.record_id or not required.issubset(set(self.required_metrics)):
            raise LearningContractError("complete versioned outcome definition is required")


@dataclass(frozen=True, kw_only=True)
class DatasetSplitManifest(ImmutableLearningRecord):
    dataset_version: str
    train_end: str
    oos_start: str
    source_record_hashes: Mapping[str, str]
    excluded_record_ids: tuple[str, ...]
    exclusion_reasons: Mapping[str, str]

    def __post_init__(self) -> None:
        super().__post_init__()
        train = _aware(self.train_end, "train_end")
        oos = _aware(self.oos_start, "oos_start")
        if train >= oos:
            raise LearningContractError("train/OOS boundary overlaps")
        if any(not _HASH.fullmatch(str(value)) for value in self.source_record_hashes.values()):
            raise LearningContractError("dataset source record hash is invalid")
        if set(self.excluded_record_ids) != set(self.exclusion_reasons):
            raise LearningContractError("dataset exclusions require an exact reason per record")


@dataclass(frozen=True, kw_only=True)
class HistoricalCaseReference(ImmutableLearningRecord):
    case_id: str
    source_record_id: str
    source_record_hash: str
    feature_vector: SimilarityFeatureVector
    split: str
    data_completeness: float
    outcome_record_id: str
    outcome_record_hash: str
    production_eligible: bool

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.case_id != self.record_id or self.split not in {"TRAIN", "OOS"}:
            raise LearningContractError("invalid historical case identity/split")
        if not self.feature_vector.verify_hash() or not _HASH.fullmatch(self.source_record_hash) or not _HASH.fullmatch(self.outcome_record_hash):
            raise LearningContractError("historical case lineage is invalid")
        if not 0 <= self.data_completeness <= 1:
            raise LearningContractError("case completeness must be 0..1")


@dataclass(frozen=True, kw_only=True)
class HistoricalOutcomeRecord(ImmutableLearningRecord):
    outcome_id: str
    source_record_id: str
    source_record_hash: str
    decision_id: str
    decision_hash: str
    outcome_definition_id: str
    target_definition_from_decision: str
    stop_definition_from_decision: str
    classification: str
    mfe: float | None
    mae: float | None
    time_to_target_seconds: float | None
    time_to_stop_seconds: float | None
    after_cost_return: float | None
    slippage: float | None
    invalidation_timing_seconds: float | None
    premium_response: float | None
    costs_included: bool
    completed_at: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.outcome_id != self.record_id or self.classification not in {"TARGET_BEFORE_STOP", "STOP_BEFORE_TARGET", "NEITHER"}:
            raise LearningContractError("invalid completed historical outcome")
        if not _HASH.fullmatch(self.source_record_hash) or not _HASH.fullmatch(self.decision_hash):
            raise LearningContractError("outcome must reference immutable source and decision hashes")
        _aware(self.completed_at, "completed_at")


@dataclass(frozen=True, kw_only=True)
class SimilarityMatch:
    case_id: str
    tier: str
    distance: float
    exact_features: tuple[str, ...]
    differing_features: Mapping[str, Any]
    reasons: tuple[str, ...]
    split: str
    data_completeness: float
    source_record_id: str
    source_record_hash: str

    def __post_init__(self) -> None:
        if self.tier not in {"EXACT", "RELAXED"} or self.distance < 0 or self.split not in {"TRAIN", "OOS"}:
            raise LearningContractError("invalid transparent similarity match")
        object.__setattr__(self, "differing_features", _freeze(self.differing_features))

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, kw_only=True)
class CohortDefinition(ImmutableLearningRecord):
    cohort_id: str
    query_feature_hash: str
    outcome_definition_id: str
    dataset_version: str
    exact_filters: Mapping[str, str]
    relaxed_filters: Mapping[str, tuple[str, ...]]
    numerical_weights: Mapping[str, float]
    maximum_distance: float

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.cohort_id != self.record_id or not _HASH.fullmatch(self.query_feature_hash):
            raise LearningContractError("invalid cohort identity")
        if self.maximum_distance < 0 or any(float(v) < 0 for v in self.numerical_weights.values()):
            raise LearningContractError("invalid published similarity weights")


@dataclass(frozen=True, kw_only=True)
class SimilarityResult(ImmutableLearningRecord):
    query_feature_hash: str
    cohort_id: str
    dataset_version: str
    outcome_definition_id: str
    matches: tuple[SimilarityMatch, ...]
    excluded_counts: Mapping[str, int]
    method_version: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if not _HASH.fullmatch(self.query_feature_hash):
            raise LearningContractError("similarity query hash is invalid")
        object.__setattr__(self, "excluded_counts", _freeze(self.excluded_counts))


@dataclass(frozen=True, kw_only=True)
class SampleSufficiencyPolicy(ImmutableLearningRecord):
    minimum_total_sample: int
    minimum_oos_sample: int
    minimum_regime_coverage: int
    minimum_expiry_bucket_coverage: int
    minimum_time_bucket_coverage: int
    maximum_missing_fraction: float
    confidence_level: float
    maximum_cohort_drift: float
    recency_half_life_days: int | None
    costs_required: bool

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.minimum_total_sample <= 0 or self.minimum_oos_sample <= 0:
            raise LearningContractError("sample thresholds must be explicit and positive")
        if not 0 < self.confidence_level < 1 or not 0 <= self.maximum_missing_fraction <= 1 or self.maximum_cohort_drift < 0:
            raise LearningContractError("invalid sample/calibration policy")


@dataclass(frozen=True, kw_only=True)
class CohortStatistics(ImmutableLearningRecord):
    cohort_id: str
    total_sample: int
    oos_sample: int
    target_before_stop: int
    stop_before_target: int
    neither: int
    target_rate: float | None
    confidence_interval: tuple[float, float] | None
    mean_mfe: float | None
    mean_mae: float | None
    mean_time_to_target_seconds: float | None
    mean_time_to_stop_seconds: float | None
    mean_after_cost_return: float | None
    mean_slippage: float | None
    costs_included: bool
    missing_fraction: float
    caveats: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.target_before_stop + self.stop_before_target + self.neither != self.total_sample:
            raise LearningContractError("cohort outcome counts do not reconcile")
        if self.target_rate is not None and not 0 <= self.target_rate <= 1:
            raise LearningContractError("invalid empirical rate")


@dataclass(frozen=True, kw_only=True)
class CalibrationReport(ImmutableLearningRecord):
    cohort_id: str
    cohort_statistics_hash: str
    policy_id: str
    state: CalibrationState
    historical_probability: float | None
    numerator: int
    denominator: int
    confidence_interval: tuple[float, float] | None
    oos_status: str
    costs_included: bool
    cohort_version: str
    brier_score: float | None
    calibration_error: float | None
    cohort_drift: float | None
    caveats: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        allowed = {CalibrationState.OOS_CALIBRATED_WEAK, CalibrationState.OOS_CALIBRATED}
        if self.state not in allowed and self.historical_probability is not None:
            raise LearningContractError("historical probability requires OOS calibration")
        if self.historical_probability is not None and not 0 <= self.historical_probability <= 1:
            raise LearningContractError("invalid historical probability")
        if self.numerator < 0 or self.denominator < self.numerator:
            raise LearningContractError("invalid calibration numerator/denominator")


@dataclass(frozen=True, kw_only=True)
class VisualEdgeLabel:
    label: str
    original_user_wording: str

    def __post_init__(self) -> None:
        if not self.label or not self.original_user_wording:
            raise LearningContractError("user label and original wording are required")

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "original_user_wording": self.original_user_wording}


@dataclass(frozen=True, kw_only=True)
class VisualEdgeReason:
    tags: tuple[str, ...]
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"tags": list(self.tags), "notes": self.notes}


@dataclass(frozen=True, kw_only=True)
class VisualArtifactReference:
    timeframe: str
    artifact_id: str | None
    artifact_hash: str | None
    availability: str
    tradingview_symbol: str | None
    layout_id: str | None
    permission: str

    def __post_init__(self) -> None:
        if self.availability not in {"AVAILABLE", "UNAVAILABLE"}:
            raise LearningContractError("invalid artifact availability")
        if self.availability == "AVAILABLE" and (not self.artifact_id or not self.artifact_hash or not _HASH.fullmatch(self.artifact_hash)):
            raise LearningContractError("available visual artifact requires hash-pinned identity")
        if self.availability == "UNAVAILABLE" and (self.artifact_id or self.artifact_hash):
            raise LearningContractError("unavailable visual artifact cannot be fabricated")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, kw_only=True)
class CaptureCompleteness:
    state: str
    available_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    training_eligible: bool
    policy_version: str

    def __post_init__(self) -> None:
        if self.state not in {"COMPLETE", "PARTIAL", "UNAVAILABLE"}:
            raise LearningContractError("invalid capture completeness")
        if self.state != "COMPLETE" and self.training_eligible:
            raise LearningContractError("incomplete capture cannot be training eligible")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, kw_only=True)
class RetentionPermission:
    actor_id: str
    permission: str
    retention_status: str
    retain_until: str | None
    source_licensed: bool

    def __post_init__(self) -> None:
        if not self.actor_id or self.permission not in {"PRIVATE_RESEARCH", "RESEARCH_ELIGIBLE", "DENIED"}:
            raise LearningContractError("explicit actor permission is required")
        if self.retention_status not in {"ACTIVE", "EXPIRED", "REVOKED"}:
            raise LearningContractError("invalid retention status")
        if self.retain_until:
            _aware(self.retain_until, "retain_until")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, kw_only=True)
class VisualEdgeObservation(ImmutableLearningRecord):
    observation_id: str
    correlation_id: str
    observed_at: str
    label: VisualEdgeLabel
    reason: VisualEdgeReason
    chart_artifacts: tuple[VisualArtifactReference, ...]
    option_chart_artifacts: tuple[VisualArtifactReference, ...]
    tradingview_metadata: Mapping[str, Any]
    canonical_context_hashes: Mapping[str, str]
    authority_snapshot_ids: Mapping[str, str]
    option_snapshot: Mapping[str, Any]
    decision_id: str | None
    decision_hash: str | None
    trigger_definition: Mapping[str, Any]
    invalidation_definition: Mapping[str, Any]
    target_definitions: tuple[Mapping[str, Any], ...]
    completeness: CaptureCompleteness
    retention_permission: RetentionPermission
    current_decision_influence: str = "ZERO"

    def __post_init__(self) -> None:
        super().__post_init__()
        _aware(self.observed_at, "observed_at")
        if self.observation_id != self.record_id or not self.correlation_id:
            raise LearningContractError("visual observation identity is required")
        if self.current_decision_influence != "ZERO":
            raise LearningContractError("Visual Edge cannot influence the current opportunity")
        for name in ("tradingview_metadata", "canonical_context_hashes", "authority_snapshot_ids", "option_snapshot", "trigger_definition", "invalidation_definition"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True, kw_only=True)
class LabelRevision(ImmutableLearningRecord):
    observation_id: str
    prior_version: int
    revision_version: int
    revised_label: VisualEdgeLabel
    reason: str
    actor_id: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.revision_version != self.prior_version + 1 or not self.reason or not self.actor_id:
            raise LearningContractError("label revision must append exactly one version")


@dataclass(frozen=True, kw_only=True)
class VisualEdgeOutcomeLink(ImmutableLearningRecord):
    observation_id: str
    completed_outcome_id: str
    completed_outcome_hash: str
    completed_at: str
    outcome: str
    mfe: float | None
    mae: float | None
    correctness_label: str
    source_record_id: str
    source_record_hash: str
    time_safe_validated: bool
    model_training_eligible: bool

    def __post_init__(self) -> None:
        super().__post_init__()
        _aware(self.completed_at, "completed_at")
        if not _HASH.fullmatch(self.completed_outcome_hash) or not _HASH.fullmatch(self.source_record_hash):
            raise LearningContractError("outcome link requires immutable completed source hashes")
        if self.model_training_eligible and not self.time_safe_validated:
            raise LearningContractError("unvalidated outcome cannot train")


@dataclass(frozen=True, kw_only=True)
class DecisionEvidenceEnrichment(ImmutableLearningRecord):
    decision_id: str
    decision_hash: str
    base_evidence_bundle_id: str
    base_evidence_bundle_hash: str
    original_action: str
    knowledge_result_hash: str
    similarity_result_hash: str
    cohort_statistics_hash: str
    calibration_report_hash: str
    knowledge_references: tuple[KnowledgeCardReference, ...]
    knowledge_conflicts: tuple[KnowledgeConflict, ...]
    historical_probability: float | None
    calibration_state: CalibrationState
    visual_edge_reference_ids: tuple[str, ...]
    proof_projection: Mapping[str, Any]
    same_decision_execution_influence: str = "ZERO"
    execution_authority: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        for value in (self.decision_hash, self.base_evidence_bundle_hash, self.knowledge_result_hash,
                      self.similarity_result_hash, self.cohort_statistics_hash, self.calibration_report_hash):
            if not _HASH.fullmatch(value):
                raise LearningContractError("enrichment lineage hash is invalid")
        if self.same_decision_execution_influence != "ZERO" or self.execution_authority:
            raise LearningContractError("Phase-4 evidence cannot acquire execution influence")
        if self.calibration_state not in {CalibrationState.OOS_CALIBRATED_WEAK, CalibrationState.OOS_CALIBRATED} and self.historical_probability is not None:
            raise LearningContractError("uncalibrated enrichment probability is forbidden")
        object.__setattr__(self, "proof_projection", _freeze(self.proof_projection))
