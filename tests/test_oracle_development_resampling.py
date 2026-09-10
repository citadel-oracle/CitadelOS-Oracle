"""Focused unit tests for Oracle Development session-anchored resampling logic."""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest

from src.oracle_development.data_stream_aggregator import OracleDevDataStreamAggregator

IST = ZoneInfo("Asia/Kolkata")


def test_session_open_anchoring():
    """Asserts that resampled candle buckets anchor strictly to 09:15:00 IST."""
    resampler = OracleDevDataStreamAggregator()
    
    # Define a date and exchange open time (09:15 IST)
    test_date = datetime(2026, 7, 27).date()
    session_open = resampler.session_open_time(test_date)
    
    assert session_open.hour == 9
    assert session_open.minute == 15
    assert session_open.tzinfo == IST
    
    # 1. Candle exactly at 09:15:00 IST -> belongs to [09:15 - 09:18] for 3m interval
    c_time = session_open
    b_start = resampler.get_bucket_start(c_time, 3)
    assert b_start == session_open
    
    # 2. Candle at 09:17:59 IST -> still belongs to [09:15 - 09:18]
    c_time = session_open + timedelta(minutes=2, seconds=59)
    b_start = resampler.get_bucket_start(c_time, 3)
    assert b_start == session_open
    
    # 3. Candle at 09:18:00 IST -> belongs to the next bucket [09:18 - 09:21]
    c_time = session_open + timedelta(minutes=3)
    b_start = resampler.get_bucket_start(c_time, 3)
    assert b_start == session_open + timedelta(minutes=3)


def test_resample_completed_candles_only():
    """Asserts that candles are only aggregated once they are fully completed."""
    resampler = OracleDevDataStreamAggregator()
    
    # Establish a reference clock time at 09:20:00 IST
    session_open = datetime(2026, 7, 27, 9, 15, tzinfo=IST)
    now_ref = session_open + timedelta(minutes=5) # 09:20:00 IST
    
    # Provide 1m candles for 09:15, 09:16, 09:17, 09:18, 09:19, 09:20
    candles = [
        {"time": int((session_open + timedelta(minutes=i)).timestamp()), "open": 10.0 + i, "high": 12.0 + i, "low": 9.0 + i, "close": 11.0 + i, "volume": 100}
        for i in range(6)
    ]
    
    # Resample 3m interval
    resampled_3m = resampler.resample(candles, 3, now_ref)
    
    # Since now is 09:20:00:
    # Bucket 1 [09:15 - 09:18] is completed (reference 09:20 >= 09:18).
    # Bucket 2 [09:18 - 09:21] is NOT completed yet (reference 09:20 < 09:21).
    # So we must get exactly 1 completed candle in resampled output!
    assert len(resampled_3m) == 1
    assert resampled_3m[0]["time"] == int(session_open.timestamp())
    assert resampled_3m[0]["open"] == 10.0
    assert resampled_3m[0]["close"] == 13.0 # close of 09:17:00 candle
    assert resampled_3m[0]["volume"] == 300


def test_no_manufactured_option_candles():
    """Asserts that option candles are resampled from actual ticks/candles, not manufactured from option chains."""
    class MockDhan:
        def get_intraday_candles(self, segment, security_id=None, *args, **kwargs):
            return {
                "success": True,
                "candles": [
                    {"time": 1785148800, "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 500}
                ]
            }
            
        def get_quote(self, segment, security_id):
            return {"ltp": 24000.0}

    # Verify that the dev service queries individual option candles directly from get_intraday_candles
    # and does not parse them from an option chain snapshot.
    from src.oracle_development.oracle_dev_service import OracleDevService
    import tempfile
    
    dhan = MockDhan()
    with tempfile.TemporaryDirectory() as tmpdir:
        service = OracleDevService(
            dhan=dhan,
            argus_api=None,
            options_structure_engine=None,
            vob_engine=None,
            state_root=tmpdir
        )
        
        # Override active expiries to return a constant
        service.resolver.active_expiries = lambda *a, **k: ["2026-07-29"]
        
        # Trigger assessment
        res = service.assess_and_execute()
        lane = res["3m"]
        
        # Verify candles exist for option contracts (resampled from MockDhan's actual option candles)
        assert lane["lane_status"]["last_option"] is not None
        assert "ATM_CE" in lane["lane_status"]["last_option"]
        # The value must equal our mock close
        assert lane["lane_status"]["last_option"]["ATM_CE"]["close"] == 102.0
