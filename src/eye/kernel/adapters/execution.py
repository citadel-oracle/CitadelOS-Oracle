"""Execution Adapter and Ledger."""
from typing import List, Dict, Any
from src.eye.kernel.domain import MarketEvent, MarketEventType, ExecutionIntent, StrategyEvent, StrategyLifecycleState

class OpenAlgoExecutionAdapter:
    """Mock execution adapter for E9. Must not submit live orders."""
    
    def __init__(self, kernel):
        self.kernel = kernel
        self.intents: List[ExecutionIntent] = []
        self.live_submission_enabled = False
        self.orders_created = 0
        
    def submit_intent(self, intent: ExecutionIntent):
        self.intents.append(intent)
        if self.live_submission_enabled:
            # E9 explicitly disables this
            self.orders_created += 1

class ReplayLedger:
    """Captures StrategyEvents to build the E8D parity ledger."""
    
    def __init__(self, bus):
        self.bus = bus
        self.trades = []
        self.traces = []
        
        # Subscribe to strategy events if they were emitted
        # In this minimal implementation, the caller can just read the events.
