import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock

from src.kronos_alpha.candle_source import RealNiftyCandleSource

def test_final_5m_candle_not_dropped():
    source = RealNiftyCandleSource()
    # Market close is 15:30 IST, which corresponds to 10:00 UTC
    market_close = datetime(2026, 8, 5, 15, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    # Reference is slightly before market close (latency condition)
    reference = market_close - timedelta(seconds=15)
    
    fetched_candles = []
    # Generate 64 candles ending at 15:30 IST
    for i in range(64):
        candle_time = market_close - timedelta(minutes=5 * (64 - i))
        fetched_candles.append({
            "time": int(candle_time.timestamp()),
            "open": 100, "high": 105, "low": 95, "close": 102
        })
    
    mock_result = {"success": True, "candles": fetched_candles, "raw": {"volume": [1000] * 64}}
    
    with patch.object(source.provider, 'get_intraday_candles', return_value=mock_result):
        with patch.object(source.calendar, 'session_for_date', return_value={"session_state": "OPEN", "scheduled_close": "2026-08-05T15:30:00+05:30"}):
            source.canonical_store = None
            candles = source.backfill(limit=64, now=reference)
            assert len(candles) == 64, f"Expected 64 candles, got {len(candles)}. The final candle was likely dropped."
            assert candles[-1]["timestamp"] == (market_close - timedelta(minutes=5)).isoformat()
