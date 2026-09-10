"""Position, Guardian, and Risk Domain Contracts for Phase E6A."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any


class GuardianState(str, Enum):
    STANDBY = "STANDBY"
    ARMED = "ARMED"
    PROTECTING = "PROTECTING"
    TARGET_PROGRESS = "TARGET_PROGRESS"
    THESIS_WEAKENING = "THESIS_WEAKENING"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    FAULT = "FAULT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ExitReason(str, Enum):
    STRUCTURAL_SL = "STRUCTURAL_SL"
    TARGET_T1 = "TARGET_T1"
    TARGET_T2 = "TARGET_T2"
    TARGET_T3 = "TARGET_T3"
    STRUCTURAL_INVALIDATION = "STRUCTURAL_INVALIDATION"
    THESIS_INVALIDATION = "THESIS_INVALIDATION"
    SESSION_EXIT = "SESSION_EXIT"
    MANUAL_SANDBOX_CLOSE = "MANUAL_SANDBOX_CLOSE"
    RECONCILIATION_CLOSE = "RECONCILIATION_CLOSE"
    ANALYZER_REJECTION = "ANALYZER_REJECTION"
    OTHER_EXACT_REASON = "OTHER_EXACT_REASON"


class RiskDecisionType(str, Enum):
    ALLOW = "ALLOW"
    REDUCE_SIZE = "REDUCE_SIZE"
    BLOCK = "BLOCK"


@dataclass
class RiskPreTradeResult:
    decision: RiskDecisionType
    allowed_quantity: int
    estimated_risk_amount: float
    risk_percentage: float
    reason_code: str
    message: str


@dataclass
class PositionState:
    position_id: str
    decision_id: str
    setup_key: str
    setup_record_id: str
    
    underlying: str
    exact_contract: str
    exchange: str
    expiry: str
    strike: float
    option_type: str
    
    side: str
    quantity: int
    product: str
    
    expected_entry: float
    actual_fill: float
    fill_time: str
    
    structural_sl: float
    invalidation_level: float
    
    t1: float
    t2: Optional[float] = None
    t3: Optional[float] = None
    
    initial_risk_points: float = 0.0
    initial_rr: float = 0.0
    
    current_premium: float = 0.0
    # The option fill does not prove an underlying price.  Keep this nullable
    # until the Guardian receives a canonical underlying bar.
    current_underlying: Optional[float] = None
    
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    current_r: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0
    
    guardian_state: GuardianState = GuardianState.STANDBY
    thesis_state: str = "VALID"
    
    openalgo_order_id: Optional[str] = None
    close_openalgo_order_id: Optional[str] = None
    openalgo_mode: str = "analyze"
    
    opened_at: str = ""
    closed_at: Optional[str] = None
    exit_reason: Optional[str] = None
    
    source: str = "CITADEL_E5_ORACLE_OPENALGO_ANALYZER"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "decision_id": self.decision_id,
            "setup_key": self.setup_key,
            "setup_record_id": self.setup_record_id,
            "underlying": self.underlying,
            "exact_contract": self.exact_contract,
            "exchange": self.exchange,
            "expiry": self.expiry,
            "strike": self.strike,
            "option_type": self.option_type,
            "side": self.side,
            "quantity": self.quantity,
            "product": self.product,
            "expected_entry": self.expected_entry,
            "actual_fill": self.actual_fill,
            "fill_time": self.fill_time,
            "structural_sl": self.structural_sl,
            "invalidation_level": self.invalidation_level,
            "t1": self.t1,
            "t2": self.t2,
            "t3": self.t3,
            "initial_risk_points": self.initial_risk_points,
            "initial_rr": self.initial_rr,
            "current_premium": self.current_premium,
            "current_underlying": self.current_underlying,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "current_r": self.current_r,
            "mfe": self.mfe,
            "mae": self.mae,
            "guardian_state": self.guardian_state.value if hasattr(self.guardian_state, "value") else str(self.guardian_state),
            "thesis_state": self.thesis_state,
            "openalgo_order_id": self.openalgo_order_id,
            "close_openalgo_order_id": self.close_openalgo_order_id,
            "openalgo_mode": self.openalgo_mode,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "exit_reason": self.exit_reason.value if hasattr(self.exit_reason, "value") else (self.exit_reason if self.exit_reason else None),
            "source": self.source,
        }
