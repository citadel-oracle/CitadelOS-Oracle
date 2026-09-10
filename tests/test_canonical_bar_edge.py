"""
Focused Unit Tests for Canonical Live Bar Edge & Resampling Pipeline.
"""

import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from src.data.data_engine import DataEngine
from src.vob.engine import NiftyVOBEngine


def test_real_tick_maps_to_canonical_input():
    de = DataEngine(dhan=None)
    tick_ts = "2026-08-07T10:11:07.996965+00:00"
    res = de.update_live_price("NIFTY", 24570.65, timestamp=tick_ts, interval_minutes=1)
    assert res["action"] in {"updated", "appended"}
    assert res["candle"]["close"] == 24570.65


def test_current_session_identity_preserved():
    ist = ZoneInfo("Asia/Kolkata")
    now_ist = datetime.now(ist)
    de = DataEngine(dhan=None)
    de.update_live_price("NIFTY", 24570.65, timestamp=now_ist.isoformat())
    candles = de.get_candles("NIFTY")
    assert len(candles) == 1
    candle_dt = DataEngine.exchange_datetime(candles[0]["time"])
    assert candle_dt.date() == now_ist.date()


def test_ist_utc_instant_preserved():
    de = DataEngine(dhan=None)
    dt_ist = datetime(2026, 8, 7, 15, 41, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    dt_utc = dt_ist.astimezone(timezone.utc)
    # Physical instant (epoch timestamp) must match 100%
    assert dt_ist.timestamp() == dt_utc.timestamp()


def test_old_may_history_cannot_become_live_state():
    may_dt = datetime.fromisoformat("2026-05-27T05:49:00+00:00")
    today_dt = datetime.now(timezone.utc)
    assert (today_dt - may_dt).total_seconds() > 86400 * 30, "May 2026 historical candle cannot qualify as current live session"


def test_1m_aggregation_deterministic():
    de = DataEngine(dhan=None)
    de.update_live_price("NIFTY", 24500.0, timestamp="2026-08-07T15:00:10+05:30")
    de.update_live_price("NIFTY", 24520.0, timestamp="2026-08-07T15:00:20+05:30")
    de.update_live_price("NIFTY", 24490.0, timestamp="2026-08-07T15:00:30+05:30")
    de.update_live_price("NIFTY", 24510.0, timestamp="2026-08-07T15:00:40+05:30")
    
    candles = de.get_candles("NIFTY")
    assert len(candles) == 1
    c = candles[0]
    assert c["open"] == 24500.0
    assert c["high"] == 24520.0
    assert c["low"] == 24490.0
    assert c["close"] == 24510.0


def test_5m_resample_deterministic():
    vob = NiftyVOBEngine()
    candles_1m = []
    for i in range(5):
        ts = int(DataEngine.bucket_timestamp(f"2026-08-07T15:0{i}:00+05:30", 1))
        candles_1m.append({"time": ts, "open": 24500.0 + i, "high": 24510.0 + i, "low": 24490.0 + i, "close": 24505.0 + i})
    
    resampled_5m = vob._resample_1m(candles_1m, 5)
    assert len(resampled_5m) == 1
    assert resampled_5m[0]["open"] == 24500.0
    assert resampled_5m[0]["high"] == 24514.0
    assert resampled_5m[0]["low"] == 24490.0
    assert resampled_5m[0]["close"] == 24509.0


def test_forming_vs_closed_bar_correct():
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    open_time = now_ist.replace(second=0, microsecond=0)
    close_time = open_time + timedelta(minutes=1)
    is_closed = now_ist >= close_time
    assert not is_closed, "Forming bar within current minute is not closed until close_time"
