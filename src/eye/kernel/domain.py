"""Domain models for CITADEL EYE Unified Kernel."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime

class MarketEventType(Enum):
    TICK = "TICK"
    BAR_CLOSED = "BAR_CLOSED"
    OPTION_CHAIN_UPDATE = "OPTION_CHAIN_UPDATE"
    SESSION_OPEN = "SESSION_OPEN"
    SESSION_CLOSE = "SESSION_CLOSE"
    SCHEDULED_CLOCK = "SCHEDULED_CLOCK"
    FEATURE_UPDATED = "FEATURE_UPDATED"
    STRATEGY_EVENT = "STRATEGY_EVENT"

@dataclass
class MarketEvent:
    event_id: str
    event_type: MarketEventType
    source_timestamp: float
    ingest_timestamp: float
    security_id: str
    source: str
    payload: Dict[str, Any]
    source_revision: Optional[int] = None

class StrategyLifecycleState(Enum):
    DISABLED = "DISABLED"
    BLOCKED = "BLOCKED"
    WARMUP = "WARMUP"
    SCANNING = "SCANNING"
    PARTIAL = "PARTIAL"
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    MANAGING = "MANAGING"
    EXITED = "EXITED"
    COMPLETED = "COMPLETED"

@dataclass
class StrategyManifest:
    strategy_id: str
    enabled: bool
    authority_state: str
    required_instruments: List[str]
    required_timeframes: List[int]
    required_features: List[str]
    required_market_events: List[MarketEventType]
    required_clock_events: List[str]
    blocker: Optional[str] = None

@dataclass
class StrategyEvent:
    strategy_id: str
    cycle_id: str
    timestamp: float
    contract: str
    transition: StrategyLifecycleState
    reason: str
    source_revision: int
    feature_snapshot: Dict[str, Any]

@dataclass
class ExecutionIntent:
    intent_id: str
    strategy_id: str
    cycle_id: str
    security_id: str
    side: str
    quantity: int
    entry_policy: str
    timestamp: float
    reason: str
    protective_risk: Dict[str, Any] = field(default_factory=dict)
