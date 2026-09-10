"""Strict Data Contracts and Type Definitions for Sol Market Brain (P0.3B Hardened).

Defines versioned, immutable schemas for Evidence Snapshots, Market Events,
Durable Event Store, Request Envelopes with Exact Input Replay, and Structured Outputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class SystemStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DATA_DEGRADED = "DATA_DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    OFF_MARKET = "OFF_MARKET"


class ReasoningStatus(str, Enum):
    ACTIVE_REASONING = "ACTIVE_REASONING"
    DEGRADED_ADVISORY = "DEGRADED_ADVISORY"
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    NOT_INVOKED = "NOT_INVOKED"


class MarketThesisVerdict(str, Enum):
    CALL = "CALL"
    PUT = "PUT"
    NO_TRADE = "NO_TRADE"


class DevelopingState(str, Enum):
    CALL_DEVELOPING = "CALL_DEVELOPING"
    PUT_DEVELOPING = "PUT_DEVELOPING"
    UNRESOLVED = "UNRESOLVED"
    NONE = "NONE"


def resolve_canonical_market_state(
    market_verdict: Any,
    developing_state: Any,
) -> Optional[str]:
    """Resolve the five-state presentation contract without inventing a verdict.

    Opposing verdict/developing pairs are invalid and therefore resolve to no
    market state.  A developing state is meaningful only while the explicit
    verdict remains NO_TRADE.
    """
    verdict = (
        market_verdict.value
        if isinstance(market_verdict, MarketThesisVerdict)
        else str(market_verdict or "").upper()
    )
    developing = (
        developing_state.value
        if isinstance(developing_state, DevelopingState)
        else str(developing_state or "").upper()
    )
    if verdict == MarketThesisVerdict.CALL.value:
        return None if developing == DevelopingState.PUT_DEVELOPING.value else "CALL"
    if verdict == MarketThesisVerdict.PUT.value:
        return None if developing == DevelopingState.CALL_DEVELOPING.value else "PUT"
    if verdict == MarketThesisVerdict.NO_TRADE.value:
        if developing == DevelopingState.CALL_DEVELOPING.value:
            return DevelopingState.CALL_DEVELOPING.value
        if developing == DevelopingState.PUT_DEVELOPING.value:
            return DevelopingState.PUT_DEVELOPING.value
        return MarketThesisVerdict.NO_TRADE.value
    return None


class DataAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    OBSERVED_ZERO = "OBSERVED_ZERO"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_HYDRATED = "NOT_HYDRATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ExpectationResult(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNRESOLVED = "UNRESOLVED"


class MarketEventType(str, Enum):
    SPOT_MOVE = "SPOT_MOVE"
    FUTURES_MOVE = "FUTURES_MOVE"
    ATM_MIGRATION = "ATM_MIGRATION"
    SUDDEN_OI_SURGE = "SUDDEN_OI_SURGE"
    CLOSED_OI_BUILDUP = "CLOSED_OI_BUILDUP"
    FLOW_AGGRESSION_BURST = "FLOW_AGGRESSION_BURST"
    FLOW_POLARITY_FLIP = "FLOW_POLARITY_FLIP"
    OPTION_RESPONSE_LAG = "OPTION_RESPONSE_LAG"
    GEX_SHIFT = "GEX_SHIFT"
    DATA_QUALITY_SHIFT = "DATA_QUALITY_SHIFT"
    STATE_TRANSITION = "STATE_TRANSITION"


@dataclass(frozen=True)
class MarketEvent:
    """A discrete chronological market occurrence with deterministic replay-stable identity."""
    event_id: str
    session_date: str
    timestamp_utc: str
    timestamp_ist: str
    event_type: str
    instrument: str
    summary: str
    security_id: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    supporting_values: Dict[str, Any] = field(default_factory=dict)
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExpectationRecord:
    """First-class immutable pre-registered prediction record."""
    expectation_id: str
    cycle_id: str
    thesis_id: str
    created_at_utc: str
    evidence_snapshot_id: str
    expected_condition: str
    invalidation_condition: str
    evidence_refs: List[str] = field(default_factory=list)
    model_identifier: str = "gpt-5.6-sol"
    schema_version: str = "3.1.0-p0.3b"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExpectationEvaluationRecord:
    """Separate append-only evaluation of an immutable expectation record."""
    evaluation_id: str
    expectation_id: str
    evaluated_at_utc: str
    actual_event_refs: List[str]
    result: ExpectationResult
    evaluation_notes: str
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "expectation_id": self.expectation_id,
            "evaluated_at_utc": self.evaluated_at_utc,
            "actual_event_refs": self.actual_event_refs,
            "result": self.result.value,
            "evaluation_notes": self.evaluation_notes,
            "evidence_refs": self.evidence_refs,
        }


@dataclass(frozen=True)
class ActiveMarketStory:
    """Event-sourced compressed active session narrative preserving event references."""
    story_revision: int
    session_date: str
    established_at_utc: str
    last_event_id: str
    total_events_processed: int
    session_open_summary: str
    structure_evolution_summary: str
    flow_regime_summary: str
    positioning_summary: str
    retained_event_refs: List[str] = field(default_factory=list)
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ThesisState:
    """The active market narrative maintained across Sol reasoning cycles."""
    thesis_id: str
    created_at_utc: str
    updated_at_utc: str
    market_verdict: Optional[MarketThesisVerdict]
    developing_state: DevelopingState
    core_narrative: str
    what_changed: str
    positioning_story: str
    oi_story: str
    flow_story: str
    option_response_story: str
    call_case: str
    put_case: str
    no_trade_case: str
    strongest_contradiction: str  # "NONE_OBSERVED" if no contradiction exists
    active_expectations: List[ExpectationRecord] = field(default_factory=list)
    evaluation_history: List[ExpectationEvaluationRecord] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)
    evidence_references: List[str] = field(default_factory=list)
    configured_model: str = "gpt-5.6-sol"
    actually_invoked_model: str = "NONE"
    reasoning_schema_version: str = "3.1.0-p0.3b"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thesis_id": self.thesis_id,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "market_verdict": self.market_verdict.value if self.market_verdict else None,
            "developing_state": self.developing_state.value if isinstance(self.developing_state, Enum) else str(self.developing_state),
            "core_narrative": self.core_narrative,
            "what_changed": self.what_changed,
            "positioning_story": self.positioning_story,
            "oi_story": self.oi_story,
            "flow_story": self.flow_story,
            "option_response_story": self.option_response_story,
            "call_case": self.call_case,
            "put_case": self.put_case,
            "no_trade_case": self.no_trade_case,
            "strongest_contradiction": self.strongest_contradiction,
            "active_expectations": [e.to_dict() for e in self.active_expectations],
            "evaluation_history": [e.to_dict() for e in self.evaluation_history],
            "data_gaps": list(self.data_gaps),
            "evidence_references": list(self.evidence_references),
            "configured_model": self.configured_model,
            "actually_invoked_model": self.actually_invoked_model,
            "reasoning_schema_version": self.reasoning_schema_version,
        }


@dataclass(frozen=True)
class SolEvidenceSnapshot:
    """Canonical, versioned, VOB-free snapshot across 7 typed sensorium domains."""
    snapshot_id: str
    canonical_snapshot_id: Optional[str]
    market_session_date: str
    identity_quality: str
    replay_stable: bool
    timestamp_utc: str
    timestamp_ist: str
    system_status: SystemStatus
    upstream_source_health: Dict[str, Any]
    dhan_quote_age_ms: Optional[float]
    order_flow_age_ms: Optional[float]
    option_chain_age_ms: Optional[float]
    
    # ── 1. Underlying ──
    spot_ltp: Optional[float]
    futures_ltp: Optional[float]
    futures_basis: Optional[float]
    session_vwap: Optional[float]
    spot_to_vwap_pts: Optional[float]
    
    # ── 2. Contract Context ──
    active_expiry: Optional[str]
    atm_strike: Optional[float]
    futures_security_id: Optional[str]
    
    # ── 3. Open Interest & Activity ──
    sudden_oi_call: Optional[Dict[str, Any]]
    sudden_oi_put: Optional[Dict[str, Any]]
    strike_ladder: List[Dict[str, Any]]
    
    # ── 4. Order Flow ──
    mlofi_5l: Optional[float]
    current_flow_x: Optional[float]
    mlofi_session_extreme: Optional[bool]
    
    # ── 5. Pricing & Liquidity ──
    ce_pricing: Optional[Dict[str, Any]]
    pe_pricing: Optional[Dict[str, Any]]
    
    # ── 6. Volatility ──
    atm_straddle_price: Optional[float]
    straddle_change_5m: Optional[float]
    atm_iv: Optional[float]
    skew_25d: Optional[float]
    skew_10d: Optional[float]
    expected_move_pts: Optional[float]
    
    # ── 7. Positioning & GEX ──
    net_gex_inr: Optional[float]
    highest_gex_strike: Optional[float]
    zero_gamma_level: Optional[float]
    
    availability_matrix: Dict[str, str]
    source_hashes: Dict[str, str]
    domestic_indices: Dict[str, float]
    vob_free_verified: str = "ZERO_VOB_ALLOWLIST_CONFIRMED"
    schema_version: str = "3.2.0-sol-p0"

    # ── 8. Phase-0 Extended Order Flow, Positioning & OSE Fields ──
    buyer_absorption: Optional[float] = None
    seller_absorption: Optional[float] = None
    failed_aggression: Optional[float] = None
    price_response_efficiency: Optional[float] = None
    continuation_efficiency: Optional[float] = None
    cvd: Optional[int] = None
    bid_depletion: Optional[int] = None
    ask_depletion: Optional[int] = None
    bid_refill: Optional[int] = None
    ask_refill: Optional[int] = None
    order_flow_response_state: Optional[str] = None
    total_net_gex_inr_cr: Optional[float] = None
    dealer_regime: Optional[str] = None
    straddle_change_15m: Optional[float] = None
    ose_ssi_score: Optional[int] = None
    ose_decision_window: Optional[str] = None
    pcr_oi: Optional[float] = None
    india_vix: Optional[float] = None
    india_vix_context: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "canonical_snapshot_id": self.canonical_snapshot_id,
            "market_session_date": self.market_session_date,
            "identity_quality": self.identity_quality,
            "replay_stable": self.replay_stable,
            "timestamp_utc": self.timestamp_utc,
            "timestamp_ist": self.timestamp_ist,
            "system_status": self.system_status.value,
            "upstream_source_health": self.upstream_source_health,
            "dhan_quote_age_ms": self.dhan_quote_age_ms,
            "order_flow_age_ms": self.order_flow_age_ms,
            "option_chain_age_ms": self.option_chain_age_ms,
            "spot_ltp": self.spot_ltp,
            "futures_ltp": self.futures_ltp,
            "futures_basis": self.futures_basis,
            "session_vwap": self.session_vwap,
            "spot_to_vwap_pts": self.spot_to_vwap_pts,
            "domestic_indices": self.domestic_indices,
            "active_expiry": self.active_expiry,
            "atm_strike": self.atm_strike,
            "futures_security_id": self.futures_security_id,
            "sudden_oi_call": self.sudden_oi_call,
            "sudden_oi_put": self.sudden_oi_put,
            "strike_ladder": self.strike_ladder,
            "mlofi_5l": self.mlofi_5l,
            "current_flow_x": self.current_flow_x,
            "mlofi_session_extreme": self.mlofi_session_extreme,
            "ce_pricing": self.ce_pricing,
            "pe_pricing": self.pe_pricing,
            "atm_straddle_price": self.atm_straddle_price,
            "straddle_change_5m": self.straddle_change_5m,
            "straddle_change_15m": self.straddle_change_15m,
            "atm_iv": self.atm_iv,
            "skew_25d": self.skew_25d,
            "skew_10d": self.skew_10d,
            "expected_move_pts": self.expected_move_pts,
            "net_gex_inr": self.net_gex_inr,
            "total_net_gex_inr_cr": self.total_net_gex_inr_cr,
            "dealer_regime": self.dealer_regime,
            "highest_gex_strike": self.highest_gex_strike,
            "zero_gamma_level": self.zero_gamma_level,
            "buyer_absorption": self.buyer_absorption,
            "seller_absorption": self.seller_absorption,
            "failed_aggression": self.failed_aggression,
            "price_response_efficiency": self.price_response_efficiency,
            "continuation_efficiency": self.continuation_efficiency,
            "cvd": self.cvd,
            "bid_depletion": self.bid_depletion,
            "ask_depletion": self.ask_depletion,
            "bid_refill": self.bid_refill,
            "ask_refill": self.ask_refill,
            "order_flow_response_state": self.order_flow_response_state,
            "ose_ssi_score": self.ose_ssi_score,
            "ose_decision_window": self.ose_decision_window,
            "pcr_oi": self.pcr_oi,
            "india_vix": self.india_vix,
            "india_vix_context": self.india_vix_context,
            "availability_matrix": self.availability_matrix,
            "source_hashes": self.source_hashes,
            "vob_free_verified": self.vob_free_verified,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class SolModelRequestEnvelope:
    """Bit-exact, normalized model request envelope persisted for 100% exact replay."""
    cycle_id: str
    prompt_version: str
    prompt_hash: str
    input_hash: str
    system_prompt: str
    user_payload: Dict[str, Any]
    configured_model: str
    requested_model: str
    reasoning_effort: str
    schema_version: str = "3.1.0-req-p0.3b"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SolBeaconOutput:
    """Minimal presentation state for the Beacon HUD separating System Health from Market Thesis."""
    system_status: str
    reasoning_status: str
    market_verdict: Optional[str]
    developing_state: str
    why_bullets: List[str]
    main_contradiction: str
    what_changed: str
    thesis_timestamp_ist: str
    feed_age_ms: Optional[float]
    configured_model: str
    actually_invoked_model: str
    replay_mode: bool = False
    schema_version: str = "3.1.0-beacon-p0.3b"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── OpenAI Structured Outputs JSON Schema (Strict mode) ──
SOL_STRUCTURED_OUTPUT_JSON_SCHEMA: Dict[str, Any] = {
    "name": "sol_market_thesis_output",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "market_verdict": {
                "type": "string",
                "enum": ["CALL", "PUT", "NO_TRADE"],
            },
            "developing_state": {
                "type": "string",
                "enum": ["CALL_DEVELOPING", "PUT_DEVELOPING", "UNRESOLVED", "NONE"],
            },
            "core_narrative": {"type": "string"},
            "what_changed": {"type": "string"},
            "positioning_story": {"type": "string"},
            "oi_story": {"type": "string"},
            "flow_story": {"type": "string"},
            "option_response_story": {"type": "string"},
            "call_case": {"type": "string"},
            "put_case": {"type": "string"},
            "no_trade_case": {"type": "string"},
            "strongest_contradiction": {"type": "string"},
            "why_bullets": {
                "type": "array",
                "items": {"type": "string"},
            },
            "expectation_evaluations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "expectation_id": {"type": "string"},
                        "result": {
                            "type": "string",
                            "enum": ["SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "UNRESOLVED"],
                        },
                        "actual_event_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["expectation_id", "result", "actual_event_refs", "notes"],
                    "additionalProperties": False,
                },
            },
            "pre_registered_expectations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "expected_condition": {"type": "string"},
                        "invalidation_condition": {"type": "string"},
                    },
                    "required": ["expected_condition", "invalidation_condition"],
                    "additionalProperties": False,
                },
            },
            "data_gaps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "evidence_references": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "market_verdict",
            "developing_state",
            "core_narrative",
            "what_changed",
            "positioning_story",
            "oi_story",
            "flow_story",
            "option_response_story",
            "call_case",
            "put_case",
            "no_trade_case",
            "strongest_contradiction",
            "why_bullets",
            "expectation_evaluations",
            "pre_registered_expectations",
            "data_gaps",
            "evidence_references",
        ],
        "additionalProperties": False,
    },
}


# =============================================================================
# PHASE-1 THREE-MODEL TOPOLOGY DATA CONTRACTS
# =============================================================================

# =============================================================================
# PHASE-1 THREE-MODEL TOPOLOGY DATA CONTRACTS
# =============================================================================

@dataclass
class ProviderCallTelemetry:
    """Explicit lifecycle truth for an individual provider model invocation."""
    request_attempted: bool = False
    request_sent: bool = False
    response_received: bool = False
    request_id: Optional[str] = None
    provider_request_id: Optional[str] = None
    model_id: str = ""
    http_status: Optional[int] = None  # MUST default to None, NOT 200
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    latency_ms: Optional[float] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    schema_status: Optional[str] = None
    error_category: Optional[str] = None
    rate_headers: Optional[Dict[str, Any]] = None
    input_revision: int = 0
    input_hash: str = ""
    output_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QwenObservation:
    """Fast Market Sentinel structured output (Qwen 3.8 27B)."""
    observed_at: str
    input_revision: int
    market_phase: str
    continuation_status: str  # CONTINUATION_STRENGTHENING, CONTINUATION_INTACT, CONTINUATION_LOSING_PROGRESS, REVERSAL_WATCH, REVERSAL_DEVELOPING, TRANSITION_UNRESOLVED
    current_side_pressure: str
    earliest_contradiction: Dict[str, Any]  # {"summary": str, "evidence_ids": List[str]}
    aggression_price_response: str
    call_premium_response: str
    put_premium_response: str
    reversal_watch: Dict[str, Any]  # {"status": str, "direction": str, "why": str, "evidence_ids": List[str]}
    strongest_new_relationship: str
    unresolved: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    model_name: str = "qwen/qwen3.8-27b"
    status: str = "CURRENT"  # CURRENT, RATE_LIMITED, UNAVAILABLE, AWAITING_FIRST_ANALYSIS
    latency_ms: float = 0.0
    telemetry: Optional[ProviderCallTelemetry] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GeminiReview:
    """Independent Senior Reviewer structured output (Gemini 3.7 Flash)."""
    reviewed_at: str
    input_revision: int
    interpretation: str
    strongest_agreement: str
    strongest_disagreement: str
    relationship_primary_may_have_missed: str
    reversal_risk: str  # LOW, MODERATE, ELEVATED, HIGH, UNKNOWN
    premium_warning: str
    late_state_warning: str
    evidence_ids: List[str] = field(default_factory=list)
    status: str = "CURRENT"  # CURRENT, QUOTA_BLOCKED, RATE_LIMITED, UNAVAILABLE, AWAITING_FIRST_ANALYSIS
    model_name: str = "gemini-3.8-flash"
    latency_ms: float = 0.0
    telemetry: Optional[ProviderCallTelemetry] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HypothesisState:
    """State and grounding for one of the 5 concurrent hypotheses."""
    name: str
    status: str  # SUPPORTED, WEAKENING, CONTRADICTED, UNRESOLVED
    why: str
    supporting_evidence_ids: List[str] = field(default_factory=list)
    opposing_evidence_ids: List[str] = field(default_factory=list)
    premium_confirmation: str = "UNRESOLVED"
    what_changed_since_previous: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PrimarySynthesisOutput:
    """Primary Deep Synthesizer (GPT-OSS 120B) operational output."""
    current_state: str  # CALL, PUT, CALL_DEVELOPING, PUT_DEVELOPING, REVERSAL_WATCH, NO_TRADE, AWAITING_FIRST_ANALYSIS
    setup_family: str   # CONTINUATION, REVERSAL, TRANSITION, UNRESOLVED
    entry_window: str   # READY, APPROACHING, WAIT, INVALID, UNRESOLVED
    why_now: List[str]  # Maximum 3 concise short bullets
    reversal_watch: Dict[str, Any]  # {"direction": str, "status": str, "first_contradiction": str, "what_failed": str, "premium_confirmation": str, "what_still_opposes": str, "why_not_confirmed": str, "evidence_ids": List[str]}
    option_buyer_side: str  # CALL_FAVOURABLE, PUT_FAVOURABLE, BOTH_POOR, UNRESOLVED
    premium_confirmation: str  # CONFIRMING, PARTIAL, DIVERGING, UNRESOLVED
    what_would_change_my_mind: List[str]  # Maximum 2 short bullets
    five_hypotheses: Dict[str, Any]  # call_continuation, put_continuation, put_to_call_reversal, call_to_put_reversal, no_trade_transition
    evidence_ids: List[str] = field(default_factory=list)
    model_name: str = "openai/gpt-oss-120b"
    status: str = "CURRENT"  # CURRENT, RATE_LIMITED, UNAVAILABLE, AWAITING_FIRST_ANALYSIS
    input_revision: int = 0
    synthesized_at: str = ""
    latency_ms: float = 0.0
    telemetry: Optional[ProviderCallTelemetry] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
