"""Data contracts for CITADEL Eye Phase E7 Personal Strategy Layer."""

from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone


class PersonalStrategyId(str, Enum):
    S01 = "S01_BB_RSI_MOMENTUM"
    S02 = "S02_NIFTY_VOLATILE"
    S03 = "S03_TREND_CATCHER"
    S04 = "S04_BULL_PULSE"
    S05 = "S05_BB_CPR_BREAKOUT"
    S06 = "S06_OPENING_MOMENTUM_RECOVERY"
    S07 = "S07_VWAP_INITIATIVE_PARKED"


class StrategyLifecycleState(str, Enum):
    DISABLED = "DISABLED"
    SCANNING = "SCANNING"
    PARTIAL = "PARTIAL"
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    BLOCKED = "BLOCKED"
    DEPLOYED = "DEPLOYED"
    MANAGING = "MANAGING"
    EXITED = "EXITED"
    REARMING = "REARMING"
    EXHAUSTED = "EXHAUSTED"
    MISSING_DATA = "MISSING_DATA"
    MISSING_RULE = "MISSING_RULE"


class ValidationStatus(str, Enum):
    BACKTEST_REQUIRED = "BACKTEST_REQUIRED"
    RESEARCH_ENRICHMENT = "RESEARCH_ENRICHMENT"
    VALIDATED = "VALIDATED"


class DeploymentStatus(str, Enum):
    DETECTION_ONLY = "DETECTION_ONLY"
    PARKED_NOT_AUTHORIZED = "PARKED_NOT_AUTHORIZED"
    ANALYZER_READY = "ANALYZER_READY"


@dataclass
class PersonalStrategyMetadata:
    strategy_id: str
    canonical_name: str
    short_label: str
    version: str
    status: str  # ACTIVE or PARKED_NOT_AUTHORIZED
    validation_status: ValidationStatus = ValidationStatus.BACKTEST_REQUIRED
    deployment_status: DeploymentStatus = DeploymentStatus.DETECTION_ONLY
    direction: str = "BULLISH"  # BULLISH, BEARISH, BOTH
    underlying: str = "NIFTY"
    instrument: str = "OPT"
    expiry_rule: str = "CURRENT_WEEK"
    contract_rule: str = "OTM1"
    quantity_rule: str = "1_LOT"
    required_timeframes: List[str] = field(default_factory=lambda: ["3m"])
    user_strategy_hash: str = ""
    implementation_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "canonical_name": self.canonical_name,
            "short_label": self.short_label,
            "version": self.version,
            "status": self.status,
            "validation_status": self.validation_status.value,
            "deployment_status": self.deployment_status.value,
            "direction": self.direction,
            "underlying": self.underlying,
            "instrument": self.instrument,
            "expiry_rule": self.expiry_rule,
            "contract_rule": self.contract_rule,
            "quantity_rule": self.quantity_rule,
            "required_timeframes": self.required_timeframes,
            "implementation_version": self.implementation_version,
        }


@dataclass
class PersonalStrategySignal:
    signal_id: str
    strategy_id: str
    strategy_name: str
    short_label: str
    strategy_version: str
    state: StrategyLifecycleState
    direction: str  # BUY_CE or BUY_PE
    match_count: int
    match_total: int
    satisfied_conditions: List[str]
    missing_conditions: List[str]
    next_required_event: str
    contract_status: str  # RESOLVED, UNRESOLVED, LOCKED
    preferred_contract: Optional[str]
    geometry_status: str
    entry_band: Optional[Dict[str, float]]
    structural_sl: Optional[float]
    informational_targets: Dict[str, float]
    risk_status: str
    blocker: Optional[str]
    execution_status: str
    event_timestamp: str
    source_timestamp: str
    freshness: float
    cycle_id: str
    flash_epoch: int = 0
    raw_reason: Optional[str] = None
    execution_exit_authority: bool = False

    @property
    def display_text(self) -> str:
        label = self.short_label or self.strategy_name or "STRATEGY"
        st = self.state.value if hasattr(self.state, "value") else str(self.state)
        if st == "SCANNING":
            return "SCANNING PERSONAL STRATEGIES"
        elif st == "PARTIAL":
            req = self.next_required_event or "WAIT FOR CONDITIONS"
            return f"{label} • {self.match_count}/{self.match_total} CONDITIONS • {req}"
        elif st in ("DETECTED", "CONFIRMED"):
            return f"{label} DETECTED"
        elif st == "BLOCKED":
            reason = self.blocker or "DATA BLOCKED"
            return f"{label} • {reason}"
        elif st == "MISSING_RULE":
            return f"{label} • RULE INCOMPLETE"
        elif st == "DEPLOYED":
            return f"{label} • DEPLOYED"
        elif st == "MANAGING":
            return f"{label} • GUARDIAN MANAGING"
        elif st == "EXITED":
            return f"{label} • EXITED"
        return f"{label} • {st}"

    @property
    def display_tone(self) -> str:
        st = self.state.value if hasattr(self.state, "value") else str(self.state)
        if st in ("DETECTED", "CONFIRMED", "DEPLOYED", "MANAGING"):
            return "positive"
        elif st in ("BLOCKED", "INVALIDATED", "MISSING_DATA", "MISSING_RULE"):
            return "negative"
        elif st in ("PARTIAL", "WAIT", "SCANNING"):
            return "neutral"
        return "empty"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "short_label": self.short_label,
            "strategy_version": self.strategy_version,
            "state": self.state.value,
            "direction": self.direction,
            "match_count": self.match_count,
            "match_total": self.match_total,
            "satisfied_conditions": self.satisfied_conditions,
            "missing_conditions": self.missing_conditions,
            "next_required_event": self.next_required_event,
            "contract_status": self.contract_status,
            "preferred_contract": self.preferred_contract,
            "geometry_status": self.geometry_status,
            "entry_band": self.entry_band,
            "structural_sl": self.structural_sl,
            "informational_targets": self.informational_targets,
            "risk_status": self.risk_status,
            "blocker": self.blocker,
            "execution_status": self.execution_status,
            "event_timestamp": self.event_timestamp,
            "source_timestamp": self.source_timestamp,
            "freshness": self.freshness,
            "cycle_id": self.cycle_id,
            "flash_epoch": self.flash_epoch,
            "raw_reason": self.raw_reason,
            "execution_exit_authority": self.execution_exit_authority,
            "display_text": self.display_text,
            "display_tone": self.display_tone,
        }
