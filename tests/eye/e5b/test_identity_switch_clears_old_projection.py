"""E5B Test: Verifies chart context identity switch increments epoch and isolates projections."""

import pytest
from src.eye.oracle_projection.runtime_state import EyeRuntimeState
from src.eye.oracle_projection.projection_service import EyeOracleProjectionService


def test_timeframe_switch_increments_epoch():
    runtime = EyeRuntimeState()
    service = EyeOracleProjectionService(runtime_state=runtime)

    p1 = service.get_projection(symbol="NIFTY", timeframe="5m")
    assert p1.identity.chart_timeframe == "5m"
    epoch1 = p1.identity.identity_epoch

    # Switch to 15m
    p2 = service.get_projection(symbol="NIFTY", timeframe="15m")
    assert p2.identity.chart_timeframe == "15m"
    assert p2.identity.identity_epoch > epoch1

    # Switch to 3m
    p3 = service.get_projection(symbol="NIFTY", timeframe="3m")
    assert p3.identity.chart_timeframe == "3m"
    assert p3.identity.identity_epoch > p2.identity.identity_epoch
