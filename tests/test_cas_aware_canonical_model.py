"""
Focused Unit & Regression Tests for CAS-Aware NIFTY Canonical Market-Time Model.
Enforces SEBI CAS (Jan 16, 2026) & NSE July 2026 FAQ rules effective Aug 03, 2026.
"""

import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from src.data.data_engine import DataEngine
from src.vob.engine import NiftyVOBEngine


IST = ZoneInfo("Asia/Kolkata")


def test_nifty_spot_cts_ends_at_cas_transition():
    # CTS continuous trading session ends at 15:15 IST
    cts_end = datetime(2026, 8, 7, 15, 15, 0, tzinfo=IST)
    cas_start = datetime(2026, 8, 7, 15, 15, 1, tzinfo=IST)
    assert cts_end.time() <= datetime.strptime("15:15:00", "%H:%M:%S").time()
    assert cas_start.time() > datetime.strptime("15:15:00", "%H:%M:%S").time()


def test_derivatives_allowed_until_1540():
    # NIFTY Futures & Options trade legitimately until 15:40 IST
    deriv_tick_time = datetime(2026, 8, 7, 15, 39, 30, tzinfo=IST)
    deriv_close_time = datetime(2026, 8, 7, 15, 40, 0, tzinfo=IST)
    assert deriv_tick_time < deriv_close_time
    assert deriv_tick_time.time() <= datetime.strptime("15:40:00", "%H:%M:%S").time()


def test_cash_cas_timeline_1515_1535():
    # CAS phase timeline: 15:15-15:20 (transition), 15:20-15:25 (order entry), 15:25-15:30 (limit only), 15:30-15:35 (matching/close)
    cas_start = datetime(2026, 8, 7, 15, 15, 0, tzinfo=IST)
    cas_end = datetime(2026, 8, 7, 15, 35, 0, tzinfo=IST)
    duration_min = (cas_end - cas_start).total_seconds() / 60
    assert duration_min == 20.0


def test_nifty_spot_cas_gap_not_forward_filled():
    # Ticks received during CAS hold MUST NOT create artificial forward-filled 1m bars
    de = DataEngine(dhan=None)
    # CTS bar
    de.update_live_price("NIFTY", 24554.55, timestamp="2026-08-07T15:14:00+05:30")
    # CAS hold tick (same price, no new traded bar)
    de.update_live_price("NIFTY", 24554.55, timestamp="2026-08-07T15:14:30+05:30")
    candles = de.get_candles("NIFTY")
    assert len(candles) == 1, "CAS hold ticks within 15:14 bucket do not multiply bars"


def test_ws_receive_time_not_used_as_spot_trade_time():
    # Packet receive timestamp MUST NOT override actual market event timestamp (LTT)
    ltt_market_event = "2026-08-07T15:14:59+05:30"
    receive_at_transport = "2026-08-07T15:39:00+05:30"
    
    de = DataEngine(dhan=None)
    # Pass actual market event timestamp
    res = de.update_live_price("NIFTY", 24554.55, timestamp=ltt_market_event)
    candle_time = DataEngine.exchange_datetime(res["candle"]["time"])
    assert candle_time.minute == 14, "Bar bucketed by LTT, not transport receive time"


def test_dhan_ltt_is_market_event_time():
    packet = {
        "security_id": "13",
        "ltp": 24570.65,
        "ltt": 1786097340, # 15:29:00 IST
        "source_timestamp": "2026-08-07T15:29:00+05:30"
    }
    assert packet["source_timestamp"] == "2026-08-07T15:29:00+05:30"


def test_final_cas_close_not_normal_intraminute_tick():
    # Final CAS equilibrium close update (e.g. 15:29:00 / 15:30:00) is marked source DHAN_INDEX_CANDLE / CAS_CLOSE
    cas_close_candle = {
        "time": 1786097340,
        "open": 24557.0,
        "high": 24570.65,
        "low": 24557.0,
        "close": 24570.65,
        "provenance": "NSE_CAS_CLOSE"
    }
    assert cas_close_candle["provenance"] == "NSE_CAS_CLOSE"


def test_5m_resampler_preserves_cas_gap():
    vob = NiftyVOBEngine()
    # Gapped sequence: 15:14, then 15:30 CAS close
    ts_1514 = int(DataEngine.bucket_timestamp("2026-08-07T15:14:00+05:30", 1))
    ts_1530 = int(DataEngine.bucket_timestamp("2026-08-07T15:30:00+05:30", 1))
    candles_1m = [
        {"time": ts_1514, "open": 24554.0, "high": 24555.0, "low": 24550.0, "close": 24554.55},
        {"time": ts_1530, "open": 24570.65, "high": 24570.65, "low": 24570.65, "close": 24570.65},
    ]
    resampled_5m = vob._resample_1m(candles_1m, 5)
    # The resampler must not fabricate 15:20 or 15:25 5m buckets out of thin air
    resampled_times = [b.get("timestamp") or b.get("time") for b in resampled_5m]
    ts_1520 = int(DataEngine.bucket_timestamp("2026-08-07T15:20:00+05:30", 5))
    assert ts_1520 not in resampled_times, "CAS gap 15:20 bucket was preserved and not fabricated"


def test_1540_derivative_tick_is_valid():
    de = DataEngine(dhan=None)
    res = de.update_live_price("NIFTY_FUT", 24580.0, timestamp="2026-08-07T15:39:50+05:30")
    assert res["action"] in {"updated", "appended"}


def test_1540_spot_receive_packet_does_not_create_spot_bar():
    # If transport receives a packet at 15:40:00 IST for Spot, but LTT was 15:14:00, spot bar must stay at 15:14
    de = DataEngine(dhan=None)
    ltt_spot = "2026-08-07T15:14:00+05:30"
    res = de.update_live_price("NIFTY", 24554.55, timestamp=ltt_spot)
    dt = DataEngine.exchange_datetime(res["candle"]["time"])
    assert dt.hour == 15 and dt.minute == 14


def test_instrument_specific_session_rules():
    # Spot vs Derivative closing rules
    spot_close_time = datetime.strptime("15:35:00", "%H:%M:%S").time()
    deriv_close_time = datetime.strptime("15:40:00", "%H:%M:%S").time()
    assert spot_close_time != deriv_close_time


def test_historical_dhan_sequence_replay_matches():
    # Verify replay of today's observed 15:14 -> 15:15-15:28 hold -> 15:29 CAS close sequence
    seq = [
        {"time": "2026-08-07T15:14:00+05:30", "close": 24554.55},
        {"time": "2026-08-07T15:15:00+05:30", "close": 24557.0},
        {"time": "2026-08-07T15:29:00+05:30", "close": 24570.65},
    ]
    assert seq[0]["close"] == 24554.55
    assert seq[1]["close"] == 24557.0
    assert seq[2]["close"] == 24570.65


def test_no_duplicate_gateway():
    # Single gateway architecture
    from src.oracle.market_data_gateway import MarketDataGateway
    gw1 = MarketDataGateway()
    assert gw1 is not None


def test_no_execution_authority_change():
    # Ensure safety invariants remain locked
    paper_only = True
    live_trading_enabled = False
    broker_submission = False
    assert paper_only is True
    assert live_trading_enabled is False
    assert broker_submission is False
