"""Contracts & Data Models for Eye Engine Oracle Live Structure & Trade-Plan Projection."""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any


class ChartIdentityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNSUPPORTED_INSTRUMENT = "UNSUPPORTED_INSTRUMENT"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"


class EntryGeometryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENTRY_BAND_NOT_ESTABLISHED = "ENTRY_BAND_NOT_ESTABLISHED"


class StructuralStopStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STRUCTURAL_SL_NOT_ESTABLISHED = "STRUCTURAL_SL_NOT_ESTABLISHED"


class NaturalTargetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NATURAL_TARGET_NOT_ESTABLISHED = "NATURAL_TARGET_NOT_ESTABLISHED"


class TradePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RR_NOT_ESTABLISHED = "RR_NOT_ESTABLISHED"


@dataclass(frozen=True)
class EyeChartContext:
    normalized_symbol: str
    exchange: str
    underlying: str
    chart_timeframe: str
    tradingview_identity: str
    identity_epoch: int
    resolved_market_data_identity: str
    resolved_at_utc: str
    source: str
    status: ChartIdentityStatus


@dataclass(frozen=True)
class EyeStructureMap:
    directional_structure: str
    internal_structure: str
    last_bos: Optional[str]
    last_choch: Optional[str]
    nearest_swing_high: Optional[float]
    nearest_swing_low: Optional[float]
    last_liquidity_sweep: Optional[str]
    structural_invalidation_level: Optional[float]
    htf_alignment_state: str
    source_timeframe: str
    is_confirmed: bool


@dataclass(frozen=True)
class EyeEntryGeometry:
    entry_low: Optional[float]
    entry_high: Optional[float]
    entry_reference: Optional[float]
    entry_geometry_type: str
    entry_status: EntryGeometryStatus
    source_event_keys: List[str]
    is_confirmed: bool


@dataclass(frozen=True)
class EyeStructuralStop:
    sl_price: Optional[float]
    sl_type: str
    structural_reference: str
    source_event_key: Optional[str]
    reason: str
    distance_from_entry: Optional[float]
    status: StructuralStopStatus
    is_confirmed: bool


@dataclass(frozen=True)
class EyeNaturalTarget:
    price: float
    target_type: str
    distance: float
    source_event_keys: List[str]
    timeframe: str
    rank: int
    rank_reason: str


@dataclass(frozen=True)
class EyeTradePlan:
    entry_geometry: EyeEntryGeometry
    structural_stop: EyeStructuralStop
    natural_targets: List[EyeNaturalTarget]
    risk_points: Optional[float]
    reward_to_t1: Optional[float]
    reward_to_t2: Optional[float]
    reward_to_t3: Optional[float]
    rr_mid: Optional[float]
    rr_conservative: Optional[float]
    status: TradePlanStatus


@dataclass(frozen=True)
class EyeMarketThesis:
    headline: str
    structural_thesis: str
    why: str
    why_proof: Dict[str, Any]
    options_context: str


@dataclass(frozen=True)
class EyeFreshnessInfo:
    market_data_last_seen_utc: str
    projection_computed_at_utc: str
    latest_closed_bar_at_utc: str
    latest_event_at_utc: str
    source_age_ms: float
    semantic_event_age_seconds: float
    freshness_status: str


@dataclass(frozen=True)
class EyeOracleProjection:
    identity: EyeChartContext
    freshness: EyeFreshnessInfo
    structure: EyeStructureMap
    price_action_summary: str
    liquidity_state: Dict[str, Any]
    setup_projection: Dict[str, Any]
    trade_plan: EyeTradePlan
    market_thesis: EyeMarketThesis
    why: str
    provenance: Dict[str, Any]
    diagnostics: Dict[str, Any]
    authority: str = "OBSERVATION_ONLY"
    execution_authority: bool = False
    probability_status: str = "NOT_ESTABLISHED"
    position_state: Optional[Dict[str, Any]] = None
    risk_state: Optional[Dict[str, Any]] = None
    personal_strategy_signal: Optional[Dict[str, Any]] = None
    personal_strategy_bus: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["identity"]["status"] = self.identity.status.value
        res["trade_plan"]["entry_geometry"]["entry_status"] = self.trade_plan.entry_geometry.entry_status.value
        res["trade_plan"]["structural_stop"]["status"] = self.trade_plan.structural_stop.status.value
        res["trade_plan"]["status"] = self.trade_plan.status.value
        return res
