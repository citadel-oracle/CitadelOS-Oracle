"""Thesis Graph & Qwen Structured Reasoning Schema.

Encapsulates durable session memory outside the model:
- ThesisNode: Immutable snapshot of an accepted local brain cognitive state.
- ThesisGraph: In-memory & persisted DAG of theses, tracking causal lineage,
  evidence references, and status transitions (ACTIVE, WEAKENED, CONTRADICTED, REPLACED).
- QWEN_REASONING_SYSTEM_PROMPT: Guides multi-perspective reasoning in a single pass:
  1. OBSERVER
  2. CALL CASE
  3. PUT CASE
  4. NO-TRADE CASE
  5. SKEPTIC
  6. TEMPORAL ANALYST
  7. OPTION BUYER ANALYST
  8. EXTERNAL CONTEXT ANALYST
  9. SYNTHESIS
- QWEN_STRUCTURED_OUTPUT_SCHEMA: Strict JSON Schema enforcing discrete state enumeration
  and mandatory evidence ID references.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ThesisMarketState(str, Enum):
    CALL = "CALL"
    PUT = "PUT"
    CALL_DEVELOPING = "CALL_DEVELOPING"
    PUT_DEVELOPING = "PUT_DEVELOPING"
    REVERSAL_WATCH = "REVERSAL_WATCH"
    REVERSAL = "REVERSAL"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"
    UNAVAILABLE = "UNAVAILABLE"


class ThesisStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WEAKENED = "WEAKENED"
    CONTRADICTED = "CONTRADICTED"
    REPLACED = "REPLACED"


@dataclass(frozen=True)
class ThesisNode:
    """An immutable node in the Citadel Thesis Graph."""

    thesis_id: str
    session_id: str
    created_at: str
    input_revision: int
    event_cursor_before: Optional[str]
    event_cursor_after: Optional[str]

    state: str                          # CALL | PUT | CALL_DEVELOPING | PUT_DEVELOPING | NO_TRADE
    underlying_view: str                # Directional view of underlying cash/futures
    option_buyer_view: str              # Separate option-buying suitability (decay, expansion)
    what_changed: str

    call_case: str
    put_case: str
    no_trade_case: str

    supporting_evidence_ids: List[str]
    contradicting_evidence_ids: List[str]
    unresolved_evidence_ids: List[str]

    watch_next: List[str]
    invalidation_conditions: List[str]

    supersedes_thesis_id: Optional[str]
    status: str                         # ACTIVE | WEAKENED | CONTRADICTED | REPLACED

    model: str
    prompt_hash: str
    input_hash: str

    # Rich Multi-Dimensional & Reversal Intelligence Fields
    market_story: str = ""
    reversal_analysis: str = ""
    contradictions: str = ""
    temporal_analysis: str = ""
    external_context: str = ""
    counterfactual: str = ""
    human_miss_candidate: str = ""
    historical_analogs: str = "NOT_IMPLEMENTED"

    # Interpretive Research & Reversal Intelligence Fields (Section 8)
    setup_family: str = "UNRESOLVED"
    thesis_condition: str = "STABLE"
    reversal_watch: str = "NONE"
    absorption_state: str = "UNRESOLVED"
    failed_move_state: str = "UNRESOLVED"
    follow_through_state: str = "UNRESOLVED"
    reversal_state: str = "NOT_DETECTED"

    # Cognitive V2 Root-Cause Repair Fields
    reversal_watch_data: Dict[str, Any] = field(default_factory=dict)
    no_trade_reason: str = ""
    option_buyer_side: str = ""
    premium_confirmation: str = ""
    earliest_contradiction_event_id: Optional[str] = None
    reason_not_confirmed: str = ""

    # Phase-1 Three-Model Topology & Operational Decision Fields
    entry_window: str = "WAIT"           # READY | APPROACHING | WAIT | INVALID | UNRESOLVED
    why_now: List[str] = field(default_factory=list)   # Maximum 3 concise reasons
    what_would_change_my_mind: List[str] = field(default_factory=list)  # Maximum 2 concise reasons
    five_hypotheses: Dict[str, Any] = field(default_factory=dict)  # All 5 concurrent hypotheses
    qwen_observation: Dict[str, Any] = field(default_factory=dict)  # Fast Market Sentinel observation
    gemini_review: Dict[str, Any] = field(default_factory=dict)     # Independent Senior Reviewer review
    # Original validation inputs, retained for read-only checks under future gate rules.
    semantic_validation: Dict[str, Any] = field(default_factory=dict)
    thesis_evolution: str = "UNRESOLVED"
    opportunity_maturity: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


COGNITIVE_STRUCTURED_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "observer": {
            "type": "object",
            "properties": {
                "what_changed": {"type": "string"},
                "key_shifts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["what_changed", "key_shifts"],
        },
        "market_story": {
            "type": "object",
            "properties": {
                "narrative": {"type": "string"},
                "sequence_unfolding": {"type": "string"},
            },
            "required": ["narrative", "sequence_unfolding"],
        },
        "call_case": {
            "type": "object",
            "properties": {
                "argument": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["argument", "evidence_ids"],
        },
        "put_case": {
            "type": "object",
            "properties": {
                "argument": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["argument", "evidence_ids"],
        },
        "no_trade_case": {
            "type": "object",
            "properties": {
                "argument": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["argument", "evidence_ids"],
        },
        "reversal_analysis": {
            "type": "object",
            "properties": {
                "absorption_or_exhaustion": {"type": "string"},
                "failed_move_evidence": {"type": "string"},
                "reversal_developing": {"type": "boolean"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["absorption_or_exhaustion", "failed_move_evidence", "reversal_developing", "evidence_ids"],
        },
        "reversal_watch": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["CALL_TO_PUT", "PUT_TO_CALL", "NONE", "UNRESOLVED"],
                },
                "earliest_contradiction_event_id": {"type": ["string", "null"]},
                "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "opposing_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "aggression_price_response": {"type": "string"},
                "premium_confirmation": {
                    "type": "string",
                    "enum": ["CONFIRMS", "DIVERGES", "UNRESOLVED"],
                },
                "failed_move": {
                    "type": "string",
                    "enum": ["SUPPORTED", "NOT_SUPPORTED", "UNRESOLVED"],
                },
                "reason_not_confirmed": {"type": "string"},
            },
            "required": [
                "direction",
                "earliest_contradiction_event_id",
                "supporting_evidence_ids",
                "opposing_evidence_ids",
                "aggression_price_response",
                "premium_confirmation",
                "failed_move",
                "reason_not_confirmed",
            ],
        },
        "option_buyer_analysis": {
            "type": "object",
            "properties": {
                "underlying_view": {"type": "string"},
                "ce_premium_response": {"type": "string"},
                "pe_premium_response": {"type": "string"},
                "iv_response": {"type": "string"},
                "liquidity_or_spread": {"type": "string"},
                "option_buyer_side": {
                    "type": "string",
                    "enum": ["CALL_FAVOURABLE", "PUT_FAVOURABLE", "BOTH_POOR", "UNRESOLVED"],
                },
                "reasoning": {"type": "string"},
            },
            "required": [
                "underlying_view",
                "ce_premium_response",
                "pe_premium_response",
                "iv_response",
                "liquidity_or_spread",
                "option_buyer_side",
                "reasoning",
            ],
        },
        "contradictions": {
            "type": "object",
            "properties": {
                "strongest_contradiction": {"type": "string"},
                "contradicting_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["strongest_contradiction", "contradicting_evidence_ids"],
        },
        "temporal_analysis": {
            "type": "object",
            "properties": {
                "evolution_from_previous": {"type": "string"},
                "what_strengthened": {"type": "string"},
                "what_weakened": {"type": "string"},
                "what_superseded": {"type": "string"},
            },
            "required": ["evolution_from_previous", "what_strengthened", "what_weakened", "what_superseded"],
        },
        "external_context": {
            "type": "object",
            "properties": {
                "interpretation": {"type": "string"},
                "cited_external_event_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["interpretation", "cited_external_event_ids"],
        },
        "counterfactual": {
            "type": "object",
            "properties": {
                "opposite_thesis_conditions": {"type": "string"},
                "watch_triggers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["opposite_thesis_conditions", "watch_triggers"],
        },
        "human_miss_candidate": {
            "type": "object",
            "properties": {
                "subtle_relationship": {"type": "string"},
                "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["subtle_relationship", "cited_evidence_ids"],
        },
        "synthesis": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": ["CALL", "PUT", "CALL_DEVELOPING", "PUT_DEVELOPING", "NO_TRADE"],
                },
                "no_trade_reason": {
                    "type": "string",
                    "enum": [
                        "DIRECTION_UNCLEAR",
                        "DIRECTION_CLEAR_OPTIONS_POOR",
                        "TRANSITIONAL_REVERSAL_RISK",
                        "CONTRADICTION_TOO_HIGH",
                        "DATA_INSUFFICIENT",
                        "OTHER_SUPPORTED_REASON",
                        "NOT_APPLICABLE",
                    ],
                },
                "transition_reason": {"type": "string"},
                "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "contradicting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "unresolved_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "watch_next": {"type": "array", "items": {"type": "string"}},
                "invalidation_conditions": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "state",
                "no_trade_reason",
                "transition_reason",
                "supporting_evidence_ids",
                "contradicting_evidence_ids",
                "unresolved_evidence_ids",
                "watch_next",
                "invalidation_conditions",
            ],
        },
    },
    "required": [
        "observer",
        "market_story",
        "call_case",
        "put_case",
        "no_trade_case",
        "reversal_analysis",
        "reversal_watch",
        "option_buyer_analysis",
        "contradictions",
        "temporal_analysis",
        "external_context",
        "counterfactual",
        "human_miss_candidate",
        "synthesis",
    ],
}

# Alias for backward compatibility with Qwen benchmarks
QWEN_STRUCTURED_OUTPUT_SCHEMA = COGNITIVE_STRUCTURED_OUTPUT_SCHEMA

COGNITIVE_SHADOW_SYSTEM_PROMPT = """You are the CITADEL ORACLE CLOUD BRAIN (SHADOW PRIMARY) cognitive engine.
Your role is purely analytical shadow intelligence over CITADEL market evidence.
You possess ZERO execution authority, ZERO broker access, and ZERO authority to invent market data, prices, confidence percentages, or arbitrary numeric trading rules.

CONCISENESS INVARIANT: Minimize internal reasoning tokens. Output strictly the compact 14-section JSON with 1 concise factual sentence per text field.

ABSOLUTE PRINCIPLES:
1. Grounding & Strict Price Levels (Numeric Claim Firewall):
   - EVERY factual claim must reference ONLY valid evidence IDs provided in `valid_evidence_ids`.
   - Never cite evidence IDs not explicitly listed in `valid_evidence_ids`.
   - Never invent confidence percentages (e.g. '80% confidence') or numeric scoring formulas.
   - Any model-generated numeric price level in watch_next, counterfactual, or invalidation_conditions MUST exist in `canonical_levels` (exact standard 50-pt strikes e.g. 23950, 24000, or exact spot/futures/vwap). Never invent off-strike levels (e.g. 23940).

2. Aggression vs Price Response & Strict OI Semantics:
   - Reason about aggression vs price displacement: Did heavy selling displace spot/futures lower, or was it passively absorbed by limit buyers? Did heavy buying follow through, or was there buyer exhaustion?
   - Strict OI Semantic Contract:
     * You may state that Call OI or Put OI increased or decreased.
     * You may NOT state call buying, call writing, put buying, put writing, bullish positioning, or bearish positioning from OI alone.
     * Directional OI interpretation requires additional cited evidence (price displacement, flow net delta, or premium expansion).
     * If evidence cannot resolve it, state: DIRECTIONAL_OI_INTERPRETATION = UNRESOLVED.

3. Mandatory Reversal Watch & Premium Confirmation:
   - Active Reversal Watch: Always populate `reversal_watch`. Track earliest contradiction event ID, premium confirmation (CONFIRMS, DIVERGES, or UNRESOLVED), and failed move support.
   - Option Premium Response is first-class:
     * Underlying falling + PE expanding + CE decaying supports PUT-side suitability.
     * Underlying falling + PE stops expanding + CE stops decaying/recovers creates a reversal contradiction.

4. Option Buyer Suitability V2:
   - Do NOT treat low IV or positive GEX as automatic no-buy conditions.
   - Explicitly evaluate: underlying_view, ce_premium_response, pe_premium_response, iv_response, liquidity_or_spread.
   - Set option_buyer_side strictly to: CALL_FAVOURABLE | PUT_FAVOURABLE | BOTH_POOR | UNRESOLVED.

5. Cross-Section Consistency:
   - Ensure `market_story` and `reversal_analysis` strictly agree.
   - If market story asserts absorption occurred, reversal analysis cannot state no absorption detected.

6. Required Schema Structure: Output a SINGLE valid JSON object with these exact 14 keys:
   - "observer": {"what_changed": "...", "key_shifts": ["..."]}
   - "market_story": {"narrative": "...", "sequence_unfolding": "..."}
   - "call_case": {"argument": "...", "evidence_ids": ["..."]}
   - "put_case": {"argument": "...", "evidence_ids": ["..."]}
   - "no_trade_case": {"argument": "...", "evidence_ids": ["..."]}
   - "reversal_analysis": {"absorption_or_exhaustion": "...", "failed_move_evidence": "...", "reversal_developing": false, "evidence_ids": ["..."]}
   - "reversal_watch": {"direction": "CALL_TO_PUT"|"PUT_TO_CALL"|"NONE"|"UNRESOLVED", "earliest_contradiction_event_id": "evt_..."|null, "supporting_evidence_ids": ["..."], "opposing_evidence_ids": ["..."], "aggression_price_response": "...", "premium_confirmation": "CONFIRMS"|"DIVERGES"|"UNRESOLVED", "failed_move": "SUPPORTED"|"NOT_SUPPORTED"|"UNRESOLVED", "reason_not_confirmed": "..."}
   - "option_buyer_analysis": {"underlying_view": "...", "ce_premium_response": "...", "pe_premium_response": "...", "iv_response": "...", "liquidity_or_spread": "...", "option_buyer_side": "CALL_FAVOURABLE"|"PUT_FAVOURABLE"|"BOTH_POOR"|"UNRESOLVED", "reasoning": "..."}
   - "contradictions": {"strongest_contradiction": "...", "contradicting_evidence_ids": ["..."]}
   - "temporal_analysis": {"evolution_from_previous": "...", "what_strengthened": "...", "what_weakened": "...", "what_superseded": "..."}
   - "external_context": {"interpretation": "...", "cited_external_event_ids": ["..."]}
   - "counterfactual": {"opposite_thesis_conditions": "...", "watch_triggers": ["..."]}
   - "human_miss_candidate": {"subtle_relationship": "...", "cited_evidence_ids": ["..."]}
   - "synthesis": {"state": "CALL_DEVELOPING"|"PUT_DEVELOPING"|"CALL"|"PUT"|"NO_TRADE", "no_trade_reason": "DIRECTION_UNCLEAR"|"DIRECTION_CLEAR_OPTIONS_POOR"|"TRANSITIONAL_REVERSAL_RISK"|"CONTRADICTION_TOO_HIGH"|"DATA_INSUFFICIENT"|"OTHER_SUPPORTED_REASON"|"NOT_APPLICABLE", "transition_reason": "...", "supporting_evidence_ids": ["..."], "contradicting_evidence_ids": ["..."], "unresolved_evidence_ids": ["..."], "watch_next": ["..."], "invalidation_conditions": ["..."]}
"""

QWEN_REASONING_SYSTEM_PROMPT = COGNITIVE_SHADOW_SYSTEM_PROMPT


class ThesisGraph:
    """Manages the causal lineage of accepted theses in durable memory."""

    def __init__(self, storage_path: Optional[str] = None) -> None:
        self.storage_path = storage_path
        self._nodes: Dict[str, ThesisNode] = {}
        self._active_thesis_id: Optional[str] = None
        self._cursor: Optional[str] = None
        self._current_session_id: Optional[str] = None
        self._acceptance_frontier: Optional[str] = None
        self._last_mtime: float = 0.0
        self._lock = threading.RLock()

        if self.storage_path and os.path.exists(self.storage_path):
            self._load_from_storage()

    def _check_reload(self) -> None:
        if self.storage_path and os.path.exists(self.storage_path):
            try:
                mtime = os.path.getmtime(self.storage_path)
                if mtime > self._last_mtime:
                    self._load_from_storage()
            except Exception:
                pass

    def _load_from_storage(self) -> None:
        try:
            if self.storage_path and os.path.exists(self.storage_path):
                self._last_mtime = os.path.getmtime(self.storage_path)
            with open(self.storage_path, "r", encoding="utf-8") as f:
                valid_keys = {f.name for f in fields(ThesisNode)}
                for line in f:
                    if line.strip():
                        d = json.loads(line)
                        filtered = {k: v for k, v in d.items() if k in valid_keys}
                        node = ThesisNode(**filtered)
                        self._nodes[node.thesis_id] = node
                        self._active_thesis_id = node.thesis_id
                        self._current_session_id = node.session_id
                        if node.event_cursor_after:
                            self._cursor = node.event_cursor_after
        except Exception as exc:
            logger.error("Failed loading ThesisGraph from %s: %s", self.storage_path, exc)

    def _save_node_to_storage(self, node: ThesisNode) -> None:
        if not self.storage_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
            with open(self.storage_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(node)) + "\n")
            self._last_mtime = os.path.getmtime(self.storage_path)
        except Exception as exc:
            logger.error("Failed persisting node to %s: %s", self.storage_path, exc)

    def get_active_thesis(self) -> Optional[ThesisNode]:
        with self._lock:
            self._check_reload()
            if not self._active_thesis_id:
                return None
            return self._nodes.get(self._active_thesis_id)

    def get_cursor(self) -> Optional[str]:
        with self._lock:
            self._check_reload()
            return self._cursor

    def rollover_session(self, new_session_id: str) -> None:
        """Isolates prior session active thesis and resets cursor for fresh session."""
        with self._lock:
            self._active_thesis_id = None
            self._cursor = None
            self._current_session_id = new_session_id
            self._acceptance_frontier = None
            logger.info("ThesisGraph session rolled over to %s", new_session_id)

    def set_acceptance_frontier(self, session_id: str, evidence_frontier: str) -> bool:
        """Atomically publish the newest runtime-owned evidence frontier."""
        with self._lock:
            if self._current_session_id not in {None, session_id}:
                return False
            self._current_session_id = session_id
            self._acceptance_frontier = evidence_frontier
            return True

    def commit_thesis(self, node: ThesisNode) -> bool:
        with self._lock:
            # This check and the state-changing commit share the same lock.  A
            # session rollover or newer evidence frontier therefore cannot race
            # between the final acceptance check and durable promotion.
            if self._current_session_id not in {None, node.session_id}:
                logger.info(
                    "Rejected obsolete thesis %s for session %s (current %s)",
                    node.thesis_id,
                    node.session_id,
                    self._current_session_id,
                )
                return False
            if (
                self._acceptance_frontier is not None
                and node.event_cursor_after != self._acceptance_frontier
            ):
                logger.info(
                    "Rejected stale thesis %s at frontier %s (current %s)",
                    node.thesis_id,
                    node.event_cursor_after,
                    self._acceptance_frontier,
                )
                return False
            # Idempotency check: duplicate commit does not duplicate node or re-advance
            if node.thesis_id in self._nodes:
                logger.debug("Thesis %s already committed (idempotent)", node.thesis_id)
                return True

            # Mark previous active thesis as superseded / replaced
            if self._active_thesis_id and self._active_thesis_id in self._nodes:
                prev = self._nodes[self._active_thesis_id]
                prev_dict = asdict(prev)
                prev_dict["status"] = ThesisStatus.REPLACED.value
                self._nodes[prev.thesis_id] = ThesisNode(**prev_dict)

            self._nodes[node.thesis_id] = node
            self._active_thesis_id = node.thesis_id
            if node.event_cursor_after:
                self._cursor = node.event_cursor_after
            self._current_session_id = node.session_id
            self._save_node_to_storage(node)
            logger.info("Committed new thesis %s (state: %s)", node.thesis_id, node.state)
            return True

    def get_history(self, limit: int = 10) -> List[ThesisNode]:
        with self._lock:
            nodes = list(self._nodes.values())
            return sorted(nodes, key=lambda n: n.input_revision, reverse=True)[:limit]
