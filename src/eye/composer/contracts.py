"""Immutable Setup & Composer Contracts for CITADEL Eye Engine E3."""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence, Tuple

from src.eye.contracts import (
    AuthorityType,
    DetectionState,
    EventDirection,
    EventFamily,
    EventType,
    InstrumentIdentity,
    LifecycleState,
    PriceAtom,
    ProbabilityStatus,
    ProducerProvenance,
    canonical_json,
    compute_sha256,
)


class ContiguityPolicy(str, Enum):
    STRICT_NEXT = "STRICT_NEXT"
    RELAXED_NEXT = "RELAXED_NEXT"
    ANY_FOLLOWING = "ANY_FOLLOWING"
    NON_DETERMINISTIC_RELAXED = "NON_DETERMINISTIC_RELAXED"


class MatchSkipPolicy(str, Enum):
    NO_SKIP = "NO_SKIP"
    SKIP_TO_NEXT_START = "SKIP_TO_NEXT_START"
    SKIP_PAST_LAST_EVENT = "SKIP_PAST_LAST_EVENT"


class EventReusePolicy(str, Enum):
    ALLOW_ACROSS_MATCHES = "ALLOW_ACROSS_MATCHES"
    FORBID_ACROSS_MATCHES = "FORBID_ACROSS_MATCHES"
    ALLOW_CONTEXT_ONLY = "ALLOW_CONTEXT_ONLY"


class OverlapPolicy(str, Enum):
    RETAIN_ALL = "RETAIN_ALL"
    SUPPRESS_IDENTICAL = "SUPPRESS_IDENTICAL"
    SUPPRESS_SAME_START = "SUPPRESS_SAME_START"
    KEEP_EARLIEST_COMPLETION = "KEEP_EARLIEST_COMPLETION"


class CandidateStatus(str, Enum):
    PARTIAL = "PARTIAL"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class PartialMatchStatus(str, Enum):
    STARTED = "STARTED"
    ADVANCING = "ADVANCING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class PatternStep:
    step_id: str
    accepted_families: Tuple[EventFamily, ...]
    accepted_types: Tuple[EventType, ...]
    direction_constraint: Optional[EventDirection] = None
    timeframe_constraint: Optional[str] = None
    required_detection_state: DetectionState = DetectionState.CONFIRMED_CLOSED_BAR
    required_lifecycle_state: Optional[LifecycleState] = None
    contiguity: ContiguityPolicy = ContiguityPolicy.RELAXED_NEXT
    max_bars_from_prev: int = 20
    max_elapsed_minutes: float = 120.0
    optional_step: bool = False
    geometry_rules: Tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class SetupDefinition:
    setup_id: str
    setup_version: str
    setup_family: str
    name: str
    status: str  # ACTIVE | RESEARCH | UNRESOLVED | DEPRECATED
    provenance: str
    steps: Tuple[PatternStep, ...]
    direction_policy: str = "MATCH_STEP_DIRECTION"
    contiguity_policy: ContiguityPolicy = ContiguityPolicy.RELAXED_NEXT
    match_skip_policy: MatchSkipPolicy = MatchSkipPolicy.SKIP_TO_NEXT_START
    event_reuse_policy: EventReusePolicy = EventReusePolicy.ALLOW_ACROSS_MATCHES
    overlap_policy: OverlapPolicy = OverlapPolicy.KEEP_EARLIEST_COMPLETION
    max_active_matches: int = 50
    max_event_age_bars: int = 50
    authority: AuthorityType = AuthorityType.OBSERVATION_ONLY

    @property
    def fingerprint(self) -> str:
        d = {
            "setup_id": self.setup_id,
            "setup_version": self.setup_version,
            "setup_family": self.setup_family,
            "status": self.status,
            "provenance": self.provenance,
            "steps_count": len(self.steps),
        }
        return compute_sha256(canonical_json(d))


@dataclass(frozen=True)
class PartialMatch:
    partial_match_id: str
    setup_id: str
    setup_version: str
    partition_key: str
    current_step_index: int
    bound_event_keys: Tuple[str, ...]
    bound_record_ids: Tuple[str, ...]
    started_at: datetime
    last_advanced_at: datetime
    expires_at: datetime
    direction: EventDirection
    status: PartialMatchStatus = PartialMatchStatus.STARTED
    failure_reason: Optional[str] = None
    revision: int = 1
    previous_revision_id: Optional[str] = None


@dataclass(frozen=True)
class SetupCandidateRecord:
    schema_version: str
    setup_key: str
    record_id: str
    setup_revision: int
    setup_id: str
    setup_version: str
    setup_family: str
    instrument: InstrumentIdentity
    direction: EventDirection
    status: CandidateStatus
    started_at: datetime
    confirmed_at: Optional[datetime]
    invalidated_at: Optional[datetime]
    evaluation_as_of: datetime
    atomic_event_keys: Tuple[str, ...]
    atomic_record_ids: Tuple[str, ...]
    ordered_step_bindings: Tuple[Mapping[str, Any], ...]
    primary_level: Optional[PriceAtom] = None
    setup_definition_fingerprint: str = ""
    composer_version: str = "1.0.0"
    authority: AuthorityType = AuthorityType.OBSERVATION_ONLY
    probability_status: ProbabilityStatus = ProbabilityStatus.NOT_ESTABLISHED
    previous_record_id: Optional[str] = None
