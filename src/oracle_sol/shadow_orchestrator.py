"""CITADEL Multi-Model Shadow Orchestrator V1.2 — Challenger Escalation Damping.

Design + Dry-Run Validation Only.
NO LIVE EXECUTION / NO PRODUCTION MODEL ACTIVATION YET.

V1.2 changes from V1.1:
- Challenger finding != Luna invocation: default behavior is to queue compact
  challenge context without immediately waking Luna.
- Natural cognitive frontiers (STATE_TRANSITION, ATM_MIGRATION, GAMMA_REGIME_SHIFT,
  STALE_CADENCE_FALLBACK) consume all active pending challenger context.
- Immediate Luna escalation is exceptional: permitted only on genuine material
  contradictions (e.g. dual divergence across independent evidence families or
  explicit thesis contradictions).
- Pending challenge coalescing: simultaneous or sequential findings from Sol and
  Gemini are coalesced into a single structured digest for the next Luna cycle.
- Receipt truth: consumed challenger context retains source_receipt_id, source_revision,
  source_cutoff, and payload_hash, and is explicitly labeled as PRIOR CHALLENGE CONTEXT.
- Staleness & resolution: queued challenges expire when underlying state resolves
  (e.g. basis returns to normal, flow reverses back) or are superseded by newer findings.
- No recursive loops: Luna consuming challenger findings never re-triggers challengers.
- Threshold registry expanded with challenge staleness horizons.

Core Invariants (unchanged):
- AI_EXECUTION_INFLUENCE = 0.0
- BROKER_SUBMISSION = False
- AI_VOB_INFLUENCE = 0.0
- MULTI_MODEL_SHADOW_ENABLED = False
- LIVE_PROVIDER_CALLS = 0 (dry-run / replay only)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# =====================================================================
# 1. HARDENED SAFETY INVARIANTS & FEATURE FLAGS
# =====================================================================

MULTI_MODEL_SHADOW_ENABLED: bool = False
AI_EXECUTION_INFLUENCE: float = 0.0
BROKER_SUBMISSION: bool = False
AI_VOB_INFLUENCE: float = 0.0
SOL_DISPATCH_ENABLED: bool = False

PRIMARY_MODEL_ID = "gpt-5.6-luna"
SOL_CHALLENGER_MODEL_ID = "gpt-5.6-sol"
GEMINI_SCOUT_MODEL_ID = "gemini-3.7-flash"


# =====================================================================
# 2. THRESHOLD CLASSIFICATION REGISTRY
# =====================================================================
# Every numeric value that influences routing is labelled with its
# classification so no value is silently treated as market intelligence.

THRESHOLD_REGISTRY: Dict[str, Dict[str, Any]] = {
    # Rate-limit guards — operational only, no market semantics
    "luna_min_interval_seconds":   {"value": 120.0, "class": "RATE_LIMIT_ONLY",
                                    "note": "Prevents repeated Luna calls before provider returns"},
    "sol_min_interval_seconds":    {"value": 60.0,  "class": "RATE_LIMIT_ONLY",
                                    "note": "Sol response time floor (~23-104s observed)"},
    "gemini_min_interval_seconds": {"value": 30.0,  "class": "RATE_LIMIT_ONLY",
                                    "note": "Gemini response time floor (~19-29s observed)"},
    # Cadence fallback — safety net, not primary routing
    "luna_stale_fallback_seconds": {"value": 300.0, "class": "RATE_LIMIT_ONLY",
                                    "note": "5-minute safety fallback, not market semantics"},
    "luna_stale_fallback_events":  {"value": 15,    "class": "ARBITRARY",
                                    "note": "Calibration point only; prefer edge triggers"},
    # Basis regime thresholds
    "basis_elevated_pts":  {"value": 25.0, "class": "EMPIRICALLY_SUPPORTED",
                             "note": "Basis above this consistently signals elevated carry"},
    "basis_dislocated_pts":{"value": 60.0, "class": "ARBITRARY",
                             "note": "Midpoint chosen conservatively; no canonical Oracle level"},
    "basis_extreme_pts":   {"value": 100.0,"class": "ARBITRARY",
                             "note": "Extreme level chosen from Sept-9 observation range"},
    "basis_material_delta_pts": {"value": 15.0, "class": "ARBITRARY",
                                  "note": "Within-regime rescan trigger; tune after more sessions"},
    # Zero-gamma proximity
    "zero_gamma_proximity_pts": {"value": 25.0, "class": "EMPIRICALLY_SUPPORTED",
                                  "note": "Observed pin / gamma squeeze interactions in test data"},
    # Challenger queue horizons (V1.2)
    "challenge_staleness_seconds": {"value": 600.0, "class": "RATE_LIMIT_ONLY",
                                    "note": "Safety horizon for queued challenger context"},
    "challenge_staleness_revs":    {"value": 100,   "class": "ARBITRARY",
                                    "note": "Revision staleness horizon for queued challenger findings"},
}


def threshold(key: str) -> Any:
    return THRESHOLD_REGISTRY[key]["value"]


# =====================================================================
# 3. CATEGORICAL RESULT TYPES
# =====================================================================

class GeminiScoutCategory(str, Enum):
    NO_MATERIAL_DELTA = "NO_MATERIAL_DELTA"
    STRUCTURAL_CHANGE = "STRUCTURAL_CHANGE"
    CONTROL_SHIFT_WATCH = "CONTROL_SHIFT_WATCH"
    CONTRADICTION_FOUND = "CONTRADICTION_FOUND"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSUPPORTED_INFERENCE = "UNSUPPORTED_INFERENCE"


class SolChallengerCategory(str, Enum):
    NO_OPTION_ECONOMIC_CONFLICT = "NO_OPTION_ECONOMIC_CONFLICT"
    PREMIUM_REPRICED = "PREMIUM_REPRICED"
    DECAY_RISK = "DECAY_RISK"
    ASYMMETRY_POOR = "ASYMMETRY_POOR"
    ASYMMETRY_IMPROVING = "ASYMMETRY_IMPROVING"
    QUOTE_QUALITY_CONCERN = "QUOTE_QUALITY_CONCERN"
    DIRECTION_TRADE_QUALITY_CONFLICT = "DIRECTION_TRADE_QUALITY_CONFLICT"


# =====================================================================
# 4. CANONICAL RECEIPT CONTRACT
# =====================================================================

def canonical_digest(value: Any) -> str:
    """Deterministic SHA-256 digest of arbitrary JSON-compatible data."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CanonicalShadowReceipt:
    """Immutable receipt binding all model evaluations for one cognitive moment."""
    packet_id: str
    receipt_id: str
    packet_hash: str
    session_date: str
    decision_cutoff_ist: str
    frozen_at_utc: str
    evidence_frontier: List[str]
    revision: int
    security_ids: Dict[str, Optional[str]]
    known_missing_inputs: List[str]
    current_facts: Dict[str, Any]

    @classmethod
    def from_packet_payload(cls, payload: Dict[str, Any], revision: int = 0) -> "CanonicalShadowReceipt":
        facts = payload.get("current_facts", {})
        frontier = payload.get("evidence_frontier", [])
        if isinstance(frontier, str):
            frontier = [frontier]
        security_ids = {
            "ce_atm": (facts.get("ce_atm_security_id", {}).get("value")
                       if isinstance(facts.get("ce_atm_security_id"), dict)
                       else facts.get("ce_atm_security_id")),
            "pe_atm": (facts.get("pe_atm_security_id", {}).get("value")
                       if isinstance(facts.get("pe_atm_security_id"), dict)
                       else facts.get("pe_atm_security_id")),
        }
        packet_hash = canonical_digest(payload)
        receipt_id = hashlib.sha256(packet_hash.encode("utf-8")).hexdigest()
        return cls(
            packet_id=payload.get("packet_id", f"pkt_{receipt_id[:12]}"),
            receipt_id=receipt_id,
            packet_hash=packet_hash,
            session_date=payload.get("session_date", "UNKNOWN"),
            decision_cutoff_ist=payload.get("decision_cutoff_ist", "UNKNOWN"),
            frozen_at_utc=payload.get("frozen_at_utc", datetime.now(timezone.utc).isoformat()),
            evidence_frontier=list(frontier),
            revision=revision or payload.get("revision", 0),
            security_ids=security_ids,
            known_missing_inputs=list(payload.get("known_missing_inputs", [])),
            current_facts=facts,
        )


@dataclass(frozen=True)
class ChallengerRecordHeader:
    """Binding header for challenger payloads — preserves parent receipt identity."""
    parent_receipt_id: str
    parent_packet_hash: str
    parent_revision: int
    challenger_model: str
    challenger_payload_hash: str
    evaluated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =====================================================================
# 5. OBSERVATIONAL RECORDS & CHALLENGE QUEUE (V1.2)
# =====================================================================

@dataclass(frozen=True)
class GeminiScoutRecord:
    receipt_id: str
    model: str = GEMINI_SCOUT_MODEL_ID
    category: GeminiScoutCategory = GeminiScoutCategory.NO_MATERIAL_DELTA
    what_changed: str = ""
    why_it_matters: str = ""
    what_human_might_miss: str = ""
    missing_evidence: List[str] = field(default_factory=list)
    deserves_deeper_review: bool = False
    evidence_ids: List[str] = field(default_factory=list)
    unsupported_inference_flag: bool = False
    unsupported_inference_reason: Optional[str] = None
    evaluated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class SolChallengerRecord:
    receipt_id: str
    model: str = SOL_CHALLENGER_MODEL_ID
    category: SolChallengerCategory = SolChallengerCategory.NO_OPTION_ECONOMIC_CONFLICT
    direction_vs_trade_quality_conflict: bool = False
    option_buyer_trap: str = ""
    pricing_evidence: str = ""
    what_makes_option_attractive: str = ""
    strongest_counter_case: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    evaluated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class QueuedChallengerFinding:
    """Compact structured context for the next Luna cycle. Zero verbose prose.
    Preserves exact receipt provenance and structural state at queue time.
    """
    source_model: str
    challenge_type: str
    finding: str
    evidence_ids: List[str]
    source_receipt_id: str
    source_revision: int
    source_cutoff: str
    payload_hash: str
    queued_at_epoch: float
    regime_at_queue: str
    flow_polarity_at_queue: Optional[str] = None
    is_material_contradiction: bool = False


@dataclass
class ChallengerLifecycleMetrics:
    """Exact lifecycle accounting for challenger findings."""
    queued: int = 0
    superseded: int = 0
    expired_stale: int = 0
    consumed: int = 0
    coalesced_events: int = 0


# =====================================================================
# 6. BASIS REGIME CLASSIFICATION
# =====================================================================

class BasisRegime(str, Enum):
    UNKNOWN = "UNKNOWN"
    NORMAL = "NORMAL"        # |basis| < 25 — EMPIRICALLY_SUPPORTED
    ELEVATED = "ELEVATED"    # |basis| 25–60 — ARBITRARY midpoint
    DISLOCATED = "DISLOCATED"  # |basis| 60–100 — ARBITRARY
    EXTREME = "EXTREME"      # |basis| >= 100 — ARBITRARY

    @classmethod
    def classify(cls, basis: Optional[float]) -> "BasisRegime":
        if basis is None:
            return cls.UNKNOWN
        b = abs(basis)
        if b < threshold("basis_elevated_pts"):
            return cls.NORMAL
        if b < threshold("basis_dislocated_pts"):
            return cls.ELEVATED
        if b < threshold("basis_extreme_pts"):
            return cls.DISLOCATED
        return cls.EXTREME


# =====================================================================
# 7. EDGE-TRIGGER STATE MACHINE & CHALLENGE BUFFER (V1.2)
# =====================================================================

@dataclass
class RouterStateMemory:
    """Persists last-dispatched state across receipts to detect true transitions."""
    # Basis
    last_basis_regime: BasisRegime = BasisRegime.UNKNOWN
    last_dispatched_basis: Optional[float] = None

    # ATM / Strike Spine
    last_atm_strike: Optional[float] = None

    # GEX / Gamma Regime
    last_gex_sign: int = 0  # -1, 0, +1

    # Zero-Gamma Boundary
    last_boundary_state: Optional[str] = None  # 'INSIDE' | 'OUTSIDE'

    # Flow Polarity
    last_flow_polarity: Optional[str] = None  # 'POS' | 'NEG' | 'NEUTRAL'

    # OI Surge identity (strike + side)
    last_surged_strike_key: Optional[str] = None

    # Skew inversion
    last_skew_inverted: Optional[bool] = None

    # V1.2 Challenger Queue: keyed by source_model for automatic coalescing & superseding
    pending_challenges: Dict[str, QueuedChallengerFinding] = field(default_factory=dict)
    metrics: ChallengerLifecycleMetrics = field(default_factory=ChallengerLifecycleMetrics)

    # Dispatch timestamps (rate-limit guards — RATE_LIMIT_ONLY)
    last_luna_ts: float = 0.0
    last_sol_ts: float = 0.0
    last_gemini_ts: float = 0.0
    last_luna_rev: int = 0


# =====================================================================
# 8. DETERMINISTIC EDGE-TRIGGER ROUTER V1.2
# =====================================================================

@dataclass
class RouterDecision:
    receipt_id: str
    cutoff_ist: str
    invoke_luna: bool
    luna_reason: Optional[str]
    is_luna_natural: bool
    is_luna_immediate_escalation: bool
    consumed_challenge_context: List[str]  # Truth-labeled context consumed from prior receipts
    invoke_sol: bool
    sol_reason: Optional[str]
    invoke_gemini: bool
    gemini_reason: Optional[str]
    models_skipped: List[str]
    edge_transitions: List[str]  # Named transitions detected this cycle
    repeated_state_calls: int    # Calls that would have fired on V1.0 but suppressed


class ShadowOrchestratorRouter:
    """Event-driven edge-trigger router with challenger escalation damping (V1.2).
    STATE CHANGING not STATE EXISTING.
    Challengers inform natural frontiers; immediate escalations are exceptional.
    """

    def __init__(
        self,
        luna_min_interval: float = threshold("luna_min_interval_seconds"),
        sol_min_interval: float = threshold("sol_min_interval_seconds"),
        gemini_min_interval: float = threshold("gemini_min_interval_seconds"),
        luna_stale_fallback: float = threshold("luna_stale_fallback_seconds"),
        luna_stale_fallback_events: int = threshold("luna_stale_fallback_events"),
        challenge_staleness_seconds: float = threshold("challenge_staleness_seconds"),
        challenge_staleness_revs: int = threshold("challenge_staleness_revs"),
        sol_enabled: Optional[bool] = None,
        gemini_enabled: Optional[bool] = None,
    ) -> None:
        # Rate-limit guards (RATE_LIMIT_ONLY)
        self.luna_min_interval = luna_min_interval
        self.sol_min_interval = sol_min_interval
        self.gemini_min_interval = gemini_min_interval
        self.luna_stale_fallback = luna_stale_fallback
        self.luna_stale_fallback_events = luna_stale_fallback_events
        self.challenge_staleness_seconds = challenge_staleness_seconds
        self.challenge_staleness_revs = challenge_staleness_revs
        if sol_enabled is not None:
            self.sol_enabled = sol_enabled
        else:
            env = os.getenv("CITADEL_SOL_OPTION_SPECIALIST_ENABLED")
            if env is not None:
                self.sol_enabled = env.strip().lower() in {"1", "true", "yes"}
            elif os.getenv("CITADEL_PAUSE_SOL", "0").strip().lower() in {"1", "true", "yes"}:
                self.sol_enabled = False
            else:
                self.sol_enabled = True

        if gemini_enabled is not None:
            self.gemini_enabled = gemini_enabled
        else:
            env = os.getenv("CITADEL_GEMINI_FAST_SCOUT_ENABLED")
            if env is not None:
                self.gemini_enabled = env.strip().lower() in {"1", "true", "yes"}
            elif os.getenv("CITADEL_PAUSE_GEMINI", "0").strip().lower() in {"1", "true", "yes"}:
                self.gemini_enabled = False
            else:
                self.gemini_enabled = True

        self._state = RouterStateMemory()
        self.routing_ledger: List[Dict[str, Any]] = []

    @property
    def metrics(self) -> ChallengerLifecycleMetrics:
        return self._state.metrics

    @staticmethod
    def _extract_value(fact_entry: Any) -> Any:
        if isinstance(fact_entry, dict):
            if fact_entry.get("availability") == "AVAILABLE":
                return fact_entry.get("value")
            return None
        return fact_entry

    def _detect_edges(
        self,
        receipt: CanonicalShadowReceipt,
        recent_events: Sequence[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Detect state transitions (edges) from the current receipt.
        Returns (edge_flags dict, list of transition label strings).
        """
        facts = receipt.current_facts
        transitions: List[str] = []

        spot     = self._extract_value(facts.get("spot_price"))
        basis    = self._extract_value(facts.get("basis"))
        zero_gam = self._extract_value(facts.get("zero_gamma"))
        gex      = self._extract_value(facts.get("total_net_gex_inr_cr"))
        atm      = self._extract_value(facts.get("atm_strike"))
        skew10d  = self._extract_value(facts.get("skew_10d"))
        skew25d  = self._extract_value(facts.get("skew_25d"))

        ev_types = {e.get("event_type") for e in recent_events}

        # ── A. Basis Regime Edge ──────────────────────────────────────
        current_regime = BasisRegime.classify(basis)
        basis_edge = False
        basis_edge_reason: Optional[str] = None
        if current_regime != BasisRegime.UNKNOWN:
            if self._state.last_basis_regime == BasisRegime.UNKNOWN:
                if current_regime != BasisRegime.NORMAL:
                    basis_edge = True
                    basis_edge_reason = f"BASIS_REGIME_ENTERED({current_regime.value},{basis:.1f})"
                    transitions.append(basis_edge_reason)
            elif current_regime != self._state.last_basis_regime:
                basis_edge = True
                basis_edge_reason = (
                    f"BASIS_REGIME_SHIFT({self._state.last_basis_regime.value}"
                    f"->{current_regime.value},{basis:.1f})"
                )
                transitions.append(basis_edge_reason)
            elif (
                self._state.last_dispatched_basis is not None
                and basis is not None
                and current_regime != BasisRegime.NORMAL
                and BasisRegime.classify(self._state.last_dispatched_basis) == current_regime
                and abs(basis - self._state.last_dispatched_basis)
                    >= threshold("basis_material_delta_pts")
            ):
                basis_edge = True
                delta = basis - self._state.last_dispatched_basis
                basis_edge_reason = f"BASIS_MATERIAL_DELTA_WITHIN_{current_regime.value}({delta:+.1f})"
                transitions.append(basis_edge_reason)

        # ── B. ATM Strike Migration Edge ──────────────────────────────
        atm_edge = False
        atm_edge_reason: Optional[str] = None
        if (
            atm is not None
            and self._state.last_atm_strike is not None
            and atm != self._state.last_atm_strike
        ):
            atm_edge = True
            atm_edge_reason = (
                f"ATM_STRIKE_MIGRATED({self._state.last_atm_strike:.0f}"
                f"->{atm:.0f})"
            )
            transitions.append(atm_edge_reason)

        # ── C. Gamma Regime Flip Edge ─────────────────────────────────
        gex_sign = 1 if (gex and gex > 0) else -1 if (gex and gex < 0) else 0
        gex_flipped = (
            gex_sign != 0
            and self._state.last_gex_sign != 0
            and gex_sign != self._state.last_gex_sign
        )
        if gex_flipped:
            transitions.append(
                f"GAMMA_REGIME_FLIP({'-ve' if self._state.last_gex_sign < 0 else '+ve'}"
                f"->{'−ve' if gex_sign < 0 else '+ve'})"
            )

        # ── D. Zero-Gamma Boundary Transition Edge ────────────────────
        boundary_state: Optional[str] = None
        if spot is not None and zero_gam is not None:
            boundary_state = (
                "INSIDE" if abs(spot - zero_gam) <= threshold("zero_gamma_proximity_pts")
                else "OUTSIDE"
            )
        boundary_edge = (
            self._state.last_boundary_state is not None
            and boundary_state is not None
            and boundary_state != self._state.last_boundary_state
        )
        if boundary_edge:
            transitions.append(
                f"ZERO_GAMMA_BOUNDARY_TRANSITION"
                f"({self._state.last_boundary_state}->{boundary_state})"
            )

        # ── E. Flow Polarity Transition Edge ──────────────────────────
        flow_edge = False
        flow_edge_reason: Optional[str] = None
        current_pol: Optional[str] = None
        flow_event = next(
            (e for e in recent_events if e.get("event_type") == "FLOW_POLARITY_FLIP"), None
        )
        if flow_event:
            after = flow_event.get("supporting_values", {}).get("after_mlofi")
            current_pol = (
                "POS" if (after is not None and after > 0)
                else "NEG" if (after is not None and after < 0)
                else "NEUTRAL"
            )
            if self._state.last_flow_polarity is None or current_pol != self._state.last_flow_polarity:
                flow_edge = True
                prev = self._state.last_flow_polarity or "UNKNOWN"
                flow_edge_reason = f"FLOW_POLARITY_TRANSITION({prev}->{current_pol})"
                transitions.append(flow_edge_reason)
                self._state.last_flow_polarity = current_pol

        # ── F. Sudden OI Surge — New Strike/Side Combination ─────────
        surge_edge = False
        surge_edge_reason: Optional[str] = None
        surge_event = next(
            (e for e in recent_events if e.get("event_type") == "SUDDEN_OI_SURGE"), None
        )
        if surge_event:
            sv = surge_event.get("supporting_values", {})
            top = sv.get("top_strike", {})
            strike = top.get("strike")
            side = sv.get("side")
            surge_key = f"{strike}_{side}"
            if surge_key != self._state.last_surged_strike_key:
                surge_edge = True
                surge_edge_reason = f"NEW_OI_SURGE_AT({strike}_{side})"
                transitions.append(surge_edge_reason)
                self._state.last_surged_strike_key = surge_key

        # ── G. Skew Inversion/Reversal Edge ───────────────────────────
        skew_edge = False
        if skew10d is not None and skew25d is not None:
            inverted = skew10d < skew25d
            if (
                self._state.last_skew_inverted is not None
                and inverted != self._state.last_skew_inverted
            ):
                skew_edge = True
                transitions.append(
                    f"SKEW_INVERSION_STATE_CHANGE(inverted={inverted})"
                )
            self._state.last_skew_inverted = inverted

        # ── H. STATE_TRANSITION canonical Oracle event ────────────────
        canonical_state_transition = "STATE_TRANSITION" in ev_types
        if canonical_state_transition:
            transitions.append("CANONICAL_STATE_TRANSITION")

        return {
            "basis_edge": basis_edge,
            "basis_edge_reason": basis_edge_reason,
            "atm_edge": atm_edge,
            "atm_edge_reason": atm_edge_reason,
            "gex_flipped": gex_flipped,
            "boundary_edge": boundary_edge,
            "boundary_state": boundary_state,
            "flow_edge": flow_edge,
            "flow_edge_reason": flow_edge_reason,
            "current_pol": current_pol,
            "surge_edge": surge_edge,
            "surge_edge_reason": surge_edge_reason,
            "skew_edge": skew_edge,
            "canonical_state_transition": canonical_state_transition,
            "current_regime": current_regime,
            "gex_sign": gex_sign,
            "atm": atm,
            "basis": basis,
        }, transitions

    def _clean_stale_or_resolved_challenges(
        self,
        receipt: CanonicalShadowReceipt,
        now: float,
        current_regime: BasisRegime,
        current_pol: Optional[str],
    ) -> None:
        """Evicts queued challenger findings if the underlying state resolved or timed out."""
        to_drop: List[Tuple[str, str]] = []
        for src, ch in list(self._state.pending_challenges.items()):
            # 1. State resolution: basis dislocation resolved back to normal
            if src == SOL_CHALLENGER_MODEL_ID and "BASIS" in ch.challenge_type:
                if current_regime == BasisRegime.NORMAL:
                    to_drop.append((src, "STATE_RESOLVED(NORMAL_BASIS)"))
            # 2. State resolution: flow polarity reversed back to prior state
            if src == GEMINI_SCOUT_MODEL_ID and "FLOW" in ch.challenge_type:
                if ch.flow_polarity_at_queue and current_pol and current_pol != ch.flow_polarity_at_queue:
                    to_drop.append((src, "STATE_RESOLVED(FLOW_REVERSED_BACK)"))
            # 3. Staleness horizon: age in seconds or revision lag
            if (
                (receipt.revision - ch.source_revision > self.challenge_staleness_revs)
                or (now - ch.queued_at_epoch > self.challenge_staleness_seconds)
            ):
                to_drop.append((src, "STALE_HORIZON_EXPIRED"))

        for src, drop_reason in to_drop:
            if src in self._state.pending_challenges:
                del self._state.pending_challenges[src]
                self._state.metrics.expired_stale += 1

    def evaluate_routing(
        self,
        receipt: CanonicalShadowReceipt,
        recent_events: Sequence[Dict[str, Any]],
        current_time_epoch: Optional[float] = None,
        material_contradiction_override: bool = False,
    ) -> RouterDecision:
        """Evaluate which models (if any) to dispatch for this receipt.
        V1.2: Damps challenger escalation into Luna.
        """
        now = current_time_epoch if current_time_epoch is not None else datetime.now(timezone.utc).timestamp()

        edges, transitions = self._detect_edges(receipt, recent_events)

        # Clean stale or resolved challenges prior to routing
        self._clean_stale_or_resolved_challenges(
            receipt, now, edges["current_regime"], edges.get("current_pol")
        )

        time_luna   = now - self._state.last_luna_ts
        time_sol    = now - self._state.last_sol_ts
        time_gemini = now - self._state.last_gemini_ts
        rev_delta   = receipt.revision - self._state.last_luna_rev

        # ── SOL (Option-Economics Challenger) ────────────────────────
        # Trigger on EDGE transitions only, not on level conditions.
        invoke_sol = False
        sol_reason: Optional[str] = None
        if self.sol_enabled and time_sol >= self.sol_min_interval:
            if edges["basis_edge"]:
                invoke_sol = True
                sol_reason = edges["basis_edge_reason"]
            elif edges["skew_edge"]:
                invoke_sol = True
                sol_reason = "SKEW_INVERSION_STATE_CHANGE"
            elif edges["atm_edge"]:
                invoke_sol = True
                sol_reason = edges["atm_edge_reason"]

        # ── GEMINI (Fast Reflexivity Scout) ──────────────────────────
        # Trigger on polarity/structural TRANSITIONS only.
        invoke_gemini = False
        gemini_reason: Optional[str] = None
        if self.gemini_enabled and time_gemini >= self.gemini_min_interval:
            if edges["flow_edge"]:
                invoke_gemini = True
                gemini_reason = edges["flow_edge_reason"]
            elif edges["surge_edge"]:
                invoke_gemini = True
                gemini_reason = edges["surge_edge_reason"]
            elif edges["boundary_edge"]:
                invoke_gemini = True
                gemini_reason = (
                    f"ZERO_GAMMA_BOUNDARY_TRANSITION"
                    f"({self._state.last_boundary_state}->{edges['boundary_state']})"
                )
            elif edges["gex_flipped"]:
                invoke_gemini = True
                gemini_reason = "GAMMA_REGIME_FLIP"

        # ── Queue Challenger Findings (V1.2) ─────────────────────────
        # Default behavior: queue finding; DO NOT immediately invoke Luna.
        if invoke_sol and sol_reason:
            self._state.last_sol_ts = now
            if SOL_CHALLENGER_MODEL_ID in self._state.pending_challenges:
                self._state.metrics.superseded += 1
            sol_ch = QueuedChallengerFinding(
                source_model=SOL_CHALLENGER_MODEL_ID,
                challenge_type=sol_reason.split("(")[0],
                finding=sol_reason,
                evidence_ids=["metric:basis"] if "BASIS" in sol_reason else ["metric:strike_spine"],
                source_receipt_id=receipt.receipt_id,
                source_revision=receipt.revision,
                source_cutoff=receipt.decision_cutoff_ist,
                payload_hash=receipt.packet_hash,
                queued_at_epoch=now,
                regime_at_queue=edges["current_regime"].value,
                is_material_contradiction=material_contradiction_override,
            )
            self._state.pending_challenges[SOL_CHALLENGER_MODEL_ID] = sol_ch
            self._state.metrics.queued += 1

        if invoke_gemini and gemini_reason:
            self._state.last_gemini_ts = now
            if GEMINI_SCOUT_MODEL_ID in self._state.pending_challenges:
                self._state.metrics.superseded += 1
            gem_ch = QueuedChallengerFinding(
                source_model=GEMINI_SCOUT_MODEL_ID,
                challenge_type=gemini_reason.split("(")[0],
                finding=gemini_reason,
                evidence_ids=(
                    ["metric:mlofi_5l", "metric:flow_net_delta"]
                    if "FLOW" in gemini_reason
                    else ["metric:gex"]
                ),
                source_receipt_id=receipt.receipt_id,
                source_revision=receipt.revision,
                source_cutoff=receipt.decision_cutoff_ist,
                payload_hash=receipt.packet_hash,
                queued_at_epoch=now,
                regime_at_queue=edges["current_regime"].value,
                flow_polarity_at_queue=edges.get("current_pol"),
                is_material_contradiction=material_contradiction_override,
            )
            self._state.pending_challenges[GEMINI_SCOUT_MODEL_ID] = gem_ch
            self._state.metrics.queued += 1

        # ── LUNA (Primary Temporal Analyst) ──────────────────────────
        # Category A: Natural Frontier
        invoke_luna = False
        luna_reason: Optional[str] = None
        is_natural = False
        is_immediate_escalation = False

        if edges["canonical_state_transition"]:
            invoke_luna = True
            luna_reason = "CANONICAL_STATE_TRANSITION"
            is_natural = True
        elif edges["atm_edge"]:
            invoke_luna = True
            luna_reason = edges["atm_edge_reason"]
            is_natural = True
        elif edges["gex_flipped"]:
            invoke_luna = True
            luna_reason = "GAMMA_REGIME_STRUCTURAL_SHIFT"
            is_natural = True
        elif time_luna >= self.luna_stale_fallback and rev_delta >= self.luna_stale_fallback_events:
            invoke_luna = True
            luna_reason = f"STALE_CADENCE_FALLBACK(dt={time_luna:.0f}s,dRev={rev_delta})"
            is_natural = True
        else:
            # Category B: Immediate Escalation (Exceptional)
            # Allowed ONLY on genuine material contradictions (e.g. dual divergence or explicit flag)
            if time_luna >= self.luna_min_interval:
                has_material_challenge = (
                    material_contradiction_override
                    or any(ch.is_material_contradiction for ch in self._state.pending_challenges.values())
                )
                dual_divergence = (invoke_sol and invoke_gemini)
                if has_material_challenge or dual_divergence:
                    invoke_luna = True
                    is_immediate_escalation = True
                    luna_reason = (
                        f"IMMEDIATE_CHALLENGER_ESCALATION("
                        f"{'DUAL_DIVERGENCE' if dual_divergence else 'MATERIAL_CONTRADICTION'})"
                    )

        # ── Consume Pending Challenges on Luna Dispatch ───────────────
        consumed_context: List[str] = []
        if invoke_luna:
            self._state.last_luna_ts = now
            self._state.last_luna_rev = receipt.revision

            if self._state.pending_challenges:
                n_ch = len(self._state.pending_challenges)
                self._state.metrics.consumed += n_ch
                if n_ch >= 2:
                    self._state.metrics.coalesced_events += 1

                for ch in self._state.pending_challenges.values():
                    # Receipt truth: label explicitly as prior challenge context from older receipt
                    consumed_context.append(
                        f"PRIOR CHALLENGE CONTEXT FROM RECEIPT {ch.source_receipt_id[:12]} "
                        f"(Rev {ch.source_revision}, Cutoff {ch.source_cutoff}): "
                        f"[{ch.source_model}] {ch.challenge_type} -> {ch.finding} "
                        f"(evidence: {ch.evidence_ids})"
                    )
                self._state.pending_challenges.clear()

        # ── Update State Memories ─────────────────────────────────────
        if edges["current_regime"] != BasisRegime.UNKNOWN:
            self._state.last_basis_regime = edges["current_regime"]
        if edges["basis"] is not None and invoke_sol and edges["basis_edge"]:
            self._state.last_dispatched_basis = edges["basis"]
        if edges["atm"] is not None:
            self._state.last_atm_strike = edges["atm"]
        if edges["gex_sign"] != 0:
            self._state.last_gex_sign = edges["gex_sign"]
        if edges["boundary_state"] is not None:
            self._state.last_boundary_state = edges["boundary_state"]

        skipped: List[str] = []
        if not invoke_luna:
            skipped.append(PRIMARY_MODEL_ID)
        if not invoke_gemini:
            skipped.append(GEMINI_SCOUT_MODEL_ID)
        if not invoke_sol:
            skipped.append(SOL_CHALLENGER_MODEL_ID)

        decision = RouterDecision(
            receipt_id=receipt.receipt_id,
            cutoff_ist=receipt.decision_cutoff_ist,
            invoke_luna=invoke_luna,
            luna_reason=luna_reason,
            is_luna_natural=is_natural,
            is_luna_immediate_escalation=is_immediate_escalation,
            consumed_challenge_context=consumed_context,
            invoke_sol=invoke_sol,
            sol_reason=sol_reason,
            invoke_gemini=invoke_gemini,
            gemini_reason=gemini_reason,
            models_skipped=skipped,
            edge_transitions=transitions,
            repeated_state_calls=0,
        )

        self.routing_ledger.append({
            "receipt_id": receipt.receipt_id[:12],
            "revision": receipt.revision,
            "transitions": transitions,
            "luna": {
                "invoked": invoke_luna,
                "reason": luna_reason,
                "natural": is_natural,
                "immediate": is_immediate_escalation,
                "consumed_challenges": len(consumed_context),
            },
            "sol": {"invoked": invoke_sol, "reason": sol_reason if invoke_sol else ("PAUSED_INPUT_HARDENING" if not self.sol_enabled else None)},
            "gemini": {"invoked": invoke_gemini, "reason": gemini_reason if invoke_gemini else ("PAUSED_INPUT_ARCHITECTURE_HARDENING" if not self.gemini_enabled else None)},
        })
        return decision


# =====================================================================
# 9. GEMINI MISSING-EVIDENCE PRE-INJECTION & POST-VALIDATION GUARD
# =====================================================================

class GeminiEvidenceGuard:
    """Guards Gemini from hallucinating or inferring unavailable order flow."""

    FORBIDDEN_ORDER_FLOW_PHRASES = (
        "institutional buying",
        "institutional selling",
        "aggressive buyers",
        "aggressive sellers",
        "aggressive buying",
        "aggressive selling",
        "order flow shows",
        "cvd indicates",
        "mlofi shows",
        "buyer aggression",
        "seller aggression",
    )

    @classmethod
    def prepare_gemini_prompt_constraints(cls, receipt: CanonicalShadowReceipt) -> str:
        missing = receipt.known_missing_inputs
        facts = receipt.current_facts

        order_flow_unavailable = (
            "flow_net_delta" in missing
            or "mlofi_5l" in missing
            or (isinstance(facts.get("flow_net_delta"), dict)
                and facts["flow_net_delta"].get("availability") != "AVAILABLE")
            or (isinstance(facts.get("mlofi_5l"), dict)
                and facts["mlofi_5l"].get("availability") != "AVAILABLE")
        )

        if order_flow_unavailable:
            return (
                "EVIDENCE STATUS: ORDER_FLOW = UNAVAILABLE\n"
                "CRITICAL INFERENCE CONSTRAINT:\n"
                "- Do NOT infer order flow, buyer aggression, or seller aggression from OI, "
                "price action, or option positioning.\n"
                "- Explicitly report order flow as UNAVAILABLE in 'missing_evidence'."
            )
        return "EVIDENCE STATUS: ORDER_FLOW = AVAILABLE"

    @classmethod
    def validate_gemini_response(
        cls,
        response_text: str,
        receipt: CanonicalShadowReceipt,
    ) -> Tuple[bool, Optional[str]]:
        missing = receipt.known_missing_inputs
        facts = receipt.current_facts

        order_flow_unavailable = (
            "flow_net_delta" in missing
            or "mlofi_5l" in missing
            or (isinstance(facts.get("flow_net_delta"), dict)
                and facts["flow_net_delta"].get("availability") != "AVAILABLE")
            or (isinstance(facts.get("mlofi_5l"), dict)
                and facts["mlofi_5l"].get("availability") != "AVAILABLE")
        )

        if order_flow_unavailable:
            lower = response_text.lower()
            for phrase in cls.FORBIDDEN_ORDER_FLOW_PHRASES:
                if phrase in lower:
                    return False, (
                        f"UNSUPPORTED_INFERENCE: asserted '{phrase}' "
                        f"while ORDER_FLOW is UNAVAILABLE"
                    )
        return True, None


# =====================================================================
# 10. SHADOW ORCHESTRATOR DISPATCH ENGINE (DRY-RUN ONLY)
# =====================================================================

class ShadowOrchestrator:
    """Isolated multi-model shadow orchestrator for simulation and dry-run testing."""

    def __init__(
        self,
        router: Optional[ShadowOrchestratorRouter] = None,
        shadow_enabled: bool = MULTI_MODEL_SHADOW_ENABLED,
    ) -> None:
        self.enabled = shadow_enabled
        self.router = router or ShadowOrchestratorRouter()
        self.ledger: List[Dict[str, Any]] = []

    def dispatch_shadow_cycle(
        self,
        receipt: CanonicalShadowReceipt,
        recent_events: Sequence[Dict[str, Any]],
        current_time_epoch: Optional[float] = None,
        material_contradiction_override: bool = False,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Simulates a shadow cycle. Zero execution influence by assertion."""
        assert AI_EXECUTION_INFLUENCE == 0.0, "FATAL: AI execution influence must be ZERO"
        assert BROKER_SUBMISSION is False, "FATAL: Broker submission must be FALSE"
        assert AI_VOB_INFLUENCE == 0.0, "FATAL: AI VOB influence must be ZERO"

        decision = self.router.evaluate_routing(
            receipt,
            recent_events,
            current_time_epoch,
            material_contradiction_override=material_contradiction_override,
        )

        cycle_result: Dict[str, Any] = {
            "receipt_id": receipt.receipt_id,
            "session_date": receipt.session_date,
            "cutoff_ist": receipt.decision_cutoff_ist,
            "edge_transitions": decision.edge_transitions,
            "models_selected": [],
            "models_skipped": decision.models_skipped,
            "consumed_challenge_context": decision.consumed_challenge_context,
            "execution_influence": 0.0,
            "broker_submission": False,
        }

        if decision.invoke_luna:
            cycle_result["models_selected"].append({
                "model": PRIMARY_MODEL_ID,
                "role": "PRIMARY_TEMPORAL_ANALYST",
                "reason": decision.luna_reason,
                "is_natural": decision.is_luna_natural,
                "is_immediate_escalation": decision.is_luna_immediate_escalation,
                "consumed_prior_challenges": decision.consumed_challenge_context,
            })

        if decision.invoke_gemini:
            guard_constraints = GeminiEvidenceGuard.prepare_gemini_prompt_constraints(receipt)
            cycle_result["models_selected"].append({
                "model": GEMINI_SCOUT_MODEL_ID,
                "role": "FAST_REFLEXIVITY_SCOUT",
                "reason": decision.gemini_reason,
                "guard_constraints": guard_constraints,
            })

        if decision.invoke_sol:
            cycle_result["models_selected"].append({
                "model": SOL_CHALLENGER_MODEL_ID,
                "role": "OPTION_ECONOMICS_CHALLENGER",
                "reason": decision.sol_reason,
            })

        self.ledger.append(cycle_result)
        return cycle_result
