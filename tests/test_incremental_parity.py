from datetime import datetime, timedelta
import pytest
from zoneinfo import ZoneInfo
from copy import deepcopy

from src.ose.engine import OptionsStructureEngine

IST = ZoneInfo("Asia/Kolkata")

def generate_candles(start_dt, num, close_start=100.0):
    candles = []
    for i in range(num):
        candles.append({
            "symbol": "NIFTY",
            "timeframe": "1m",
            "timestamp": (start_dt + timedelta(minutes=i)).isoformat(),
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": close_start + i,
            "volume": 1000
        })
    return candles

@pytest.fixture
def engine():
    return OptionsStructureEngine(dhan=None)

def assert_parity(engine, rows, minutes=5, security_id="TEST"):
    orig = OptionsStructureEngine._resample(rows, minutes)
    incr = engine._incremental_resample(rows, minutes, security_id)
    assert orig == incr
    return incr

def test_normal_append(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start, 4)
    assert_parity(engine, rows)
    # append 1
    rows.append(generate_candles(start + timedelta(minutes=4), 1, 104.0)[0])
    assert_parity(engine, rows)

def test_forming_bucket(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start, 3)
    assert_parity(engine, rows)
    # bucket is 9:15-9:20. forming. update it with another forming candle
    rows.append(generate_candles(start + timedelta(minutes=3), 1, 103.0)[0])
    assert_parity(engine, rows)
    # complete it
    rows.append(generate_candles(start + timedelta(minutes=4), 1, 104.0)[0])
    assert_parity(engine, rows)
    # start next forming
    rows.append(generate_candles(start + timedelta(minutes=5), 1, 105.0)[0])
    assert_parity(engine, rows)

def test_delayed_candle(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start, 6)
    assert_parity(engine, rows)
    
    # simulate a delayed candle arriving out of order for 9:18
    delayed = generate_candles(start + timedelta(minutes=3), 1, 999.0)[0]
    delayed["timestamp"] = (start + timedelta(minutes=3)).isoformat()
    rows.insert(3, delayed) # 9:15, 16, 17, 18(delayed), 18(orig), 19, 20
    assert_parity(engine, rows)

def test_old_ohlc_correction(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start, 15)
    assert_parity(engine, rows)
    
    # modify candle at 9:16 (in first bucket)
    rows[1] = deepcopy(rows[1])
    rows[1]["close"] = 9999.0
    assert_parity(engine, rows)

def test_inserted_historical_candle(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start, 10) # 9:15 to 9:24
    assert_parity(engine, rows)
    
    # insert a missing candle at 9:25
    rows.append(generate_candles(start + timedelta(minutes=10), 1)[0])
    # insert a missing candle in the PAST
    rows_gap = rows[:2] + rows[3:]
    engine._resample_cache.clear()
    assert_parity(engine, rows_gap)
    # now insert it back
    rows_gap.append(rows[2])
    assert_parity(engine, rows_gap)

def test_out_of_order(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start, 10)
    # reverse the rows entirely
    reversed_rows = list(reversed(rows))
    assert_parity(engine, reversed_rows)

def test_duplicate_timestamp(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start, 10)
    # add duplicate
    rows.append(rows[5])
    assert_parity(engine, rows)

def test_session_rollover(engine):
    start1 = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start1, 375) # full day
    assert_parity(engine, rows)
    
    start2 = datetime(2026, 7, 2, 9, 15, tzinfo=IST)
    rows.extend(generate_candles(start2, 10))
    assert_parity(engine, rows)
    
def test_contract_rollover(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows1 = generate_candles(start, 10)
    rows2 = generate_candles(start, 10)
    
    assert_parity(engine, rows1, security_id="CONT_A")
    assert_parity(engine, rows2, security_id="CONT_B")
    
def test_restart_empty_cache(engine):
    start = datetime(2026, 7, 1, 9, 15, tzinfo=IST)
    rows = generate_candles(start, 10)
    assert_parity(engine, rows)
    
    # Restart
    engine._resample_cache.clear()
    assert_parity(engine, rows)
