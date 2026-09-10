"""
Versioned Premium Intelligence Contracts (v1.0.0)

Immutability & Governance:
  - execution_influence is strictly ZERO
  - No field is labeled 'confidence' or 'win_probability' (all are indexed 0-100 or state labels)
  - Formula versions explicitly tracked
"""

from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PremiumRegimeSnapshot:
    snapshot_id: str
    instrument: str = "NIFTY"
    expiry: Optional[str] = None
    atm_strike: Optional[float] = None
    source_timestamp: Optional[str] = None
    data_state: str = "NO_DATA"  # LIVE | RESTORED | HISTORICAL | STALE | NO_DATA
    atm_straddle_price: Optional[float] = None
    straddle_bar_change: Optional[float] = None
    straddle_session_change: Optional[float] = None
    straddle_velocity: Optional[float] = None  # pts/min
    straddle_acceleration: Optional[float] = None  # pts/min^2
    premium_expansion_index: float = 0.0  # 0 - 100
    premium_compression_index: float = 0.0  # 0 - 100
    melt_decay_index: float = 0.0  # 0 - 100
    iv_impulse: Optional[float] = None
    movement_efficiency: float = 0.0  # 0 - 100
    chase_exhaustion_state: str = "LOW"  # LOW | MODERATE | HIGH | EXHAUSTED
    regime: str = "NO_DATA"  # EARLY_EXPANSION | ESTABLISHED_EXPANSION | COMPRESSION | PREMIUM_MELT | MIXED | EXHAUSTED_OR_CHASE | NO_DATA | STALE
    premium_layer_state: str = "NO_DATA"  # BUYING_FRIENDLY | WAIT | AVOID | NO_DATA
    blockers: List[str] = field(default_factory=list)
    formula_version: str = "v1.0.0"
    provenance: Dict[str, Any] = field(default_factory=dict)
    execution_influence: str = "ZERO"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PremiumLeadSnapshot:
    snapshot_id: str
    instrument: str = "NIFTY"
    expiry: Optional[str] = None
    atm_strike: Optional[float] = None
    source_timestamp: Optional[str] = None
    atm_ce_symbol: Optional[str] = None
    atm_ce_premium: Optional[float] = None
    atm_pe_symbol: Optional[str] = None
    atm_pe_premium: Optional[float] = None
    atm_straddle_price: Optional[float] = None
    ce_premium_change: Optional[float] = None
    pe_premium_change: Optional[float] = None
    ce_normalized_lead_index: float = 50.0  # 0 - 100
    pe_normalized_lead_index: float = 50.0  # 0 - 100
    lead_side: str = "NO_DATA"  # CALL_LEAD | PUT_LEAD | MIXED | TWO_SIDED_EXPANSION | TWO_SIDED_COMPRESSION | NO_DATA | STALE
    lead_strength: float = 0.0  # 0 - 100
    lead_acceleration: float = 0.0
    expansion_structure: str = "NONE"  # ONE_SIDED | TWO_SIDED | BALANCED | NONE
    session_straddle_range: Dict[str, Optional[float]] = field(
        default_factory=lambda: {"high": None, "low": None, "position_pct": None}
    )
    data_quality: str = "NO_DATA"  # HIGH | DEGRADED | NO_DATA
    blockers: List[str] = field(default_factory=list)
    formula_version: str = "v1.0.0"
    provenance: Dict[str, Any] = field(default_factory=dict)
    execution_influence: str = "ZERO"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PremiumIntelligenceSnapshot:
    snapshot_id: str
    timestamp: str
    pre_snapshot: PremiumRegimeSnapshot
    pli_snapshot: PremiumLeadSnapshot
    premium_layer_state: str = "NO_DATA"  # BUYING_FRIENDLY | WAIT | AVOID | NO_DATA
    engine_alignment: str = "NO_DATA"  # ALIGNED_CALL | ALIGNED_PUT | NEUTRAL | CONFLICTED | NO_DATA
    data_quality: str = "NO_DATA"
    blockers: List[str] = field(default_factory=list)
    why_evidence: Dict[str, Any] = field(default_factory=dict)
    execution_influence: str = "ZERO"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrikeAttentionSnapshot:
    snapshot_id: str
    instrument: str = "NIFTY"
    source_timestamp: Optional[str] = None
    ranked_strikes: List[Dict[str, Any]] = field(default_factory=list)
    top_strike: Optional[int] = None
    top_strike_score: float = 0.0
    rank_stability: float = 100.0
    formula_version: str = "v1.0.0"
    execution_influence: str = "ZERO"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrikeMigrationSnapshot:
    snapshot_id: str
    instrument: str = "NIFTY"
    source_timestamp: Optional[str] = None
    migration_direction: str = "STATIONARY"  # UPWARD, DOWNWARD, STATIONARY, REVERSAL
    migration_velocity_pts_per_5m: float = 0.0
    migration_acceleration: float = 0.0
    migration_persistence: float = 0.0
    migration_state: str = "BALANCED"  # CONTINUATION, REVERSAL, FAILED_MIGRATION, BALANCED
    formula_version: str = "v1.0.0"
    execution_influence: str = "ZERO"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DGPProxySnapshot:
    snapshot_id: str
    instrument: str = "NIFTY"
    source_timestamp: Optional[str] = None
    gamma_pin_strike: Optional[int] = None
    pin_proximity_pts: float = 0.0
    escape_probability_index: float = 50.0
    fragility_index: float = 0.0
    proxy_confidence: str = "INFERRED_PROXY"
    note: str = "Explicitly an inferred gamma proxy; dealer inventory is never directly observed."
    formula_version: str = "v1.0.0"
    execution_influence: str = "ZERO"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

