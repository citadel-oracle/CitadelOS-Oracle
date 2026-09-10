"""Shared, strategy-neutral Strategy Lab engines."""

from types import MappingProxyType

from .fair_value_gaps import (
    FairValueGap,
    FairValueGapBar,
    FairValueGapConfig,
    FairValueGapEngine,
)
from .liquidity_zones import LiquidityBar, LiquidityZone, LiquidityZoneConfig, LiquidityZoneEngine
from .order_blocks import OrderBlock, OrderBlockBar, OrderBlockConfig, SharedOrderBlockEngine
from .risk import SharedRiskEngine, SharedRiskPolicy
from .sessions import SessionConfig, SharedSessionManager
from .supertrend import SupertrendEngine
from .volume import VolumeFilter
from .vwap import VWAPEngine

SHARED_TRADING_CORE_TYPES = MappingProxyType(
    {
        "fair_value_gaps": FairValueGapEngine,
        "liquidity_zones": LiquidityZoneEngine,
        "order_blocks": SharedOrderBlockEngine,
        "risk": SharedRiskEngine,
        "sessions": SharedSessionManager,
        "supertrend": SupertrendEngine,
        "volume_filter": VolumeFilter,
        "vwap": VWAPEngine,
    }
)

__all__ = [
    "FairValueGap",
    "FairValueGapBar",
    "FairValueGapConfig",
    "FairValueGapEngine",
    "LiquidityBar",
    "LiquidityZone",
    "LiquidityZoneConfig",
    "LiquidityZoneEngine",
    "OrderBlock",
    "OrderBlockBar",
    "OrderBlockConfig",
    "SHARED_TRADING_CORE_TYPES",
    "SessionConfig",
    "SharedOrderBlockEngine",
    "SharedRiskEngine",
    "SharedRiskPolicy",
    "SharedSessionManager",
    "SupertrendEngine",
    "VolumeFilter",
    "VWAPEngine",
]
