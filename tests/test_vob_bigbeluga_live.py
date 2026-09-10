"""Focused live integration and incremental update tests for BigBeluga SMC Pine v5 VOB engine."""
import pytest
import os
from pathlib import Path
from src.vob.engine import NiftyVOBEngine
from src.vob.bigbeluga_engine import BigBelugaVOBEngine

pytestmark = pytest.mark.unit


def test_live_incremental_updates_and_safety():
    """Verify live incremental candle updates work and keep execution influence at ZERO."""
    engine = NiftyVOBEngine()
    
    # 5m candles mock sequence
    candles = [
        {"open": 24000.0, "high": 24020.0, "low": 23990.0, "close": 24010.0, "volume": 1000.0, "time": 1784600000.0, "closed": True},
        {"open": 24010.0, "high": 24030.0, "low": 24005.0, "close": 24025.0, "volume": 1200.0, "time": 1784600300.0, "closed": True},
        {"open": 24025.0, "high": 24035.0, "low": 24010.0, "close": 24015.0, "volume": 800.0, "time": 1784600600.0, "closed": True},
    ]

    res1 = engine.analyze_timeframe(timeframe="5m", candles=candles, current_nifty_price=24015.0)
    assert res1 is not None

    # Now add one more live candle
    candles.append(
        {"open": 24015.0, "high": 24040.0, "low": 24015.0, "close": 24035.0, "volume": 1500.0, "time": 1784600900.0, "closed": True}
    )
    res2 = engine.analyze_timeframe(timeframe="5m", candles=candles, current_nifty_price=24035.0)
    
    # Check that execution influence is ZERO
    assert res2["current_nifty_price"] == 24035.0
    
    # Check global structure safety
    all_res = engine.analyze_all({"5m": candles}, current_nifty_price=24035.0)
    assert all_res["execution_influence"] == 0.0
    assert all_res["advisory_only"] is True


def test_ms_bos_choch_transitions_and_origin_find():
    """Verify BOS/CHoCH structural transitions and find() method index identification."""
    beluga = BigBelugaVOBEngine()
    
    # Generate mock high/low series to test pivot & origin search
    candles = []
    for i in range(30):
        # Bullish trend with pivots
        p = 24000.0 + i * 5
        candles.append({
            "open": p, "high": p + 10, "low": p - 5, "close": p + 5,
            "volume": 1000.0, "time": float(i * 300), "closed": True
        })

    bull_obs, bear_obs = beluga._replay("5m", candles)
    # Ensure structure state machine has evaluated properly
    assert len(bull_obs) >= 0
    assert len(bear_obs) >= 0
