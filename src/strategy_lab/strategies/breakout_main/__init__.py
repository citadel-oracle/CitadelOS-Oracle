"""BREAKOUT MAIN Phase 2 Strategy Lab registration."""

from .adapters import BreakoutMainOrderBlockAdapter
from .deployment import STRATEGY_ID, build_deployment_request
from .market_structure import MarketStructureConfig, MarketStructureEngine, StructureState
from .parity import (
    BreakoutMainParityValidator,
    ParityMismatch,
    ParityReport,
    TradingViewFixture,
    TradingViewFixtureImporter,
    capture_runtime_transition,
)
from .strategy import (
    BreakoutMainConfig,
    BreakoutMainState,
    BreakoutMainStrategyEngine,
    LongPosition,
    PendingSignal,
)

__all__ = [
    "STRATEGY_ID",
    "BreakoutMainOrderBlockAdapter",
    "BreakoutMainParityValidator",
    "BreakoutMainConfig",
    "BreakoutMainState",
    "BreakoutMainStrategyEngine",
    "LongPosition",
    "MarketStructureConfig",
    "MarketStructureEngine",
    "StructureState",
    "PendingSignal",
    "ParityMismatch",
    "ParityReport",
    "TradingViewFixture",
    "TradingViewFixtureImporter",
    "capture_runtime_transition",
    "build_deployment_request",
]
