"""
PRE & PLI Threshold Governance Registry (Demoted to UNVALIDATED_DEFAULT)

Governance Statuses:
  UNVALIDATED_DEFAULT  — default thresholds for telemetry research, NON-AUTHORITATIVE
  DISABLED             — disabled features
  NOT_AVAILABLE        — feature unavailable due to missing feed
"""

from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ThresholdEntry:
    name: str
    value: Optional[float]
    unit: str
    governance: str  # UNVALIDATED_DEFAULT | DISABLED | NOT_AVAILABLE
    formula_version: str
    source_fields: List[str]
    cadence: str  # COMPLETED_BAR | FORMING_BAR | TICK
    calibration_note: str
    fallback_behavior: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_REGISTRY: List[ThresholdEntry] = [
    ThresholdEntry(
        name="STRADDLE_MIN_FLOOR",
        value=5.0,
        unit="points",
        governance="UNVALIDATED_DEFAULT",
        formula_version="v1.0.0",
        source_fields=["ce_ltp", "pe_ltp"],
        cadence="COMPLETED_BAR",
        calibration_note="Minimum combined straddle floor threshold for research telemetry",
        fallback_behavior="Produce NO_DATA if total straddle < 5.0 pts",
    ),
    ThresholdEntry(
        name="FRESHNESS_MAX_AGE_SECONDS",
        value=60.0,
        unit="seconds",
        governance="UNVALIDATED_DEFAULT",
        formula_version="v1.0.0",
        source_fields=["source_timestamp"],
        cadence="COMPLETED_BAR",
        calibration_note="Maximum age threshold for option leg freshness qualification",
        fallback_behavior="Flag as STALE if age > 60s",
    ),
    ThresholdEntry(
        name="EXPANSION_THRESHOLD",
        value=1.5,
        unit="pts/min",
        governance="UNVALIDATED_DEFAULT",
        formula_version="v1.0.0",
        source_fields=["straddle_velocity"],
        cadence="COMPLETED_BAR",
        calibration_note="Velocity threshold for early expansion classification",
        fallback_behavior="Telemetry only, never blocks strategy decisions",
    ),
    ThresholdEntry(
        name="MELT_RISK_THRESHOLD",
        value=2.0,
        unit="pts/bar",
        governance="UNVALIDATED_DEFAULT",
        formula_version="v1.0.0",
        source_fields=["theta", "straddle_bar_change"],
        cadence="COMPLETED_BAR",
        calibration_note="Decay rate threshold for premium melt risk",
        fallback_behavior="Telemetry only, never blocks strategy decisions",
    ),
    ThresholdEntry(
        name="CHASE_EXHAUSTION_STD",
        value=2.5,
        unit="std_dev",
        governance="UNVALIDATED_DEFAULT",
        formula_version="v1.0.0",
        source_fields=["straddle_price_zscore"],
        cadence="COMPLETED_BAR",
        calibration_note="Z-score threshold for straddle expansion exhaustion",
        fallback_behavior="Telemetry only, never blocks strategy decisions",
    ),
    ThresholdEntry(
        name="LEAD_DIFFERENTIAL_MIN",
        value=15.0,
        unit="index_pts",
        governance="UNVALIDATED_DEFAULT",
        formula_version="v1.0.0",
        source_fields=["ce_normalized_lead_index", "pe_normalized_lead_index"],
        cadence="COMPLETED_BAR",
        calibration_note="Minimum differential for single-sided CALL/PUT lead classification",
        fallback_behavior="Classify as MIXED if lead differential < 15.0 pts",
    ),
    ThresholdEntry(
        name="GREEKS_DELTA_WEIGHT",
        value=0.5,
        unit="weight",
        governance="UNVALIDATED_DEFAULT",
        formula_version="v1.0.0",
        source_fields=["ce_delta", "pe_delta"],
        cadence="COMPLETED_BAR",
        calibration_note="Delta weighting in lead index when valid Greeks are present",
        fallback_behavior="Omit delta weight if Greeks delta is missing",
    ),
    ThresholdEntry(
        name="IV_IMPULSE_MIN",
        value=0.5,
        unit="iv_pts",
        governance="UNVALIDATED_DEFAULT",
        formula_version="v1.0.0",
        source_fields=["ce_iv", "pe_iv"],
        cadence="COMPLETED_BAR",
        calibration_note="Minimum IV impulse change threshold",
        fallback_behavior="Report NOT_AVAILABLE if IV series missing",
    ),
    ThresholdEntry(
        name="DEALER_OI_DIRECTIONAL_INFERENCE",
        value=None,
        unit="none",
        governance="DISABLED",
        formula_version="v1.0.0",
        source_fields=["oi", "change_oi"],
        cadence="COMPLETED_BAR",
        calibration_note="Public OI is uncalibrated for dealer directional positioning",
        fallback_behavior="OI used as supporting volume context only",
    ),
]


def get_governance_registry() -> List[ThresholdEntry]:
    return list(_REGISTRY)


def get_governance_dict() -> Dict[str, Any]:
    return {
        "formula_version": "v1.0.0",
        "total_thresholds": len(_REGISTRY),
        "execution_influence": "ZERO",
        "disclaimer": "UNVALIDATED thresholds are telemetry only and cannot block strategy trades.",
        "thresholds": [t.to_dict() for t in _REGISTRY],
    }
