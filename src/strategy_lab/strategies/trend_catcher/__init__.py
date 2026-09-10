"""Trend Catcher strategy onboarding package."""

from .strategy import (
    TrendCatcherConfig,
    TrendCatcherState,
    TrendCatcherStrategyEngine,
)
from .deployment import build_deployment_request

__all__ = [
    "TrendCatcherConfig",
    "TrendCatcherState",
    "TrendCatcherStrategyEngine",
    "build_deployment_request",
]

