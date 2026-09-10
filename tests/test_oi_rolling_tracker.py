"""Unit tests for discrete closed-window OI tracking in OptionBuyerIntelligenceWorker."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest

from src.oracle.option_buyer_intelligence import _OiRollingTracker

IST = ZoneInfo("Asia/Kolkata")
BASE_SESSION = datetime(2026, 8, 21, 9, 15, 0, tzinfo=IST)


def _time(minutes: int, seconds: int = 0) -> datetime:
    """Helper to generate session datetimes starting at 09:15:00."""
    return BASE_SESSION + timedelta(minutes=minutes, seconds=seconds)


class TestOiClosedWindowTracker:
    def test_strict_asof_boundary_no_future_data(self):
        t = _OiRollingTracker()
        # Boundary 15:00:00 (345 min after 09:15)
        b_1500 = BASE_SESSION + timedelta(minutes=345)
        # Previous boundary 14:55:00 (340 min after 09:15)
        b_1455 = BASE_SESSION + timedelta(minutes=340)

        # Snapshot for 14:55
        t.record("TEST", 500000, 100.0, b_1455)

        # Observations around 15:00:00:
        # 14:59:58 (2s before boundary) -> OI=510000, LTP=105.0
        # 15:00:02 (2s after boundary) -> OI=999999, LTP=999.0 (future data)
        obs_past = b_1500 - timedelta(seconds=2)
        obs_future = b_1500 + timedelta(seconds=2)

        t.record("TEST", 510000, 105.0, obs_past)
        t.record("TEST", 999999, 999.0, obs_future)

        # Verify _find_snapshot_at_or_before strictly chooses 14:59:58
        buf = t._series["TEST"]
        snap = t._find_snapshot_at_or_before(buf, b_1500.timestamp(), max_staleness_seconds=20.0)
        assert snap is not None
        assert snap[1] == 510000  # Must be 14:59:58 OI, NOT 15:00:02
        assert snap[2] == 105.0   # Must be 14:59:58 LTP, NOT 15:00:02
        assert snap[0] <= b_1500.timestamp()  # Strict AS-OF <= boundary

        # Closed window metrics must reflect 14:59:58 vs 14:55:00
        res = t.closed_window_metrics("TEST", 5, b_1500)
        assert res is not None
        assert res["oi_delta"] == 10000  # 510000 - 500000, NOT 999999 - 500000
        assert res["price_delta"] == 5.0  # 105.0 - 100.0, NOT 999.0 - 100.0

    def test_closed_5m_window_boundary_and_stability(self):
        t = _OiRollingTracker()
        # Feed ticks every 30s from 09:15 to 09:26
        for s in range(0, 26 * 60, 30):
            dt = BASE_SESSION + timedelta(seconds=s)
            oi = 500000 + (s // 60) * 1000
            ltp = 100.0 - (s // 60) * 0.5
            t.record("61647", oi, ltp, dt)

        # Before 09:20 boundary finalizes -> explicit warming status
        assert t.closed_window_metrics("61647", 5, _time(4, 59))["status"] == "WAITING_FIRST_CLOSED_BOUNDARY"

        # At 09:20:00 -> 09:20 vs 09:15 finalized
        r_0920 = t.closed_window_metrics("61647", 5, _time(5, 0))
        assert r_0920 is not None
        assert r_0920["oi_delta"] == 5000  # 505000 - 500000
        assert r_0920["price_delta"] == -2.5  # 97.5 - 100.0
        assert r_0920["structure"] == "SHORT BUILDUP"
        assert r_0920["window_closed_at"] == "09:20"
        assert r_0920["window_prev_at"] == "09:15"

        # Throughout 09:20:01 to 09:24:59 -> MUST REMAIN IDENTICAL (forming window does not change display)
        r_0922 = t.closed_window_metrics("61647", 5, _time(7, 30))
        r_0924 = t.closed_window_metrics("61647", 5, _time(9, 59))
        assert r_0920 == r_0922 == r_0924

        # At 09:25:00 -> advances to 09:25 vs 09:20
        r_0925 = t.closed_window_metrics("61647", 5, _time(10, 0))
        assert r_0925 is not None
        assert r_0925["window_closed_at"] == "09:25"
        assert r_0925["window_prev_at"] == "09:20"
        assert r_0925["oi_delta"] == 5000

    def test_closed_15m_window_boundary_and_stability(self):
        t = _OiRollingTracker()
        # Feed ticks every 60s from 09:15 to 09:46
        for m in range(0, 32):
            dt = _time(m, 0)
            oi = 500000 + m * 2000
            ltp = 100.0 + m * 0.2
            t.record("61647", oi, ltp, dt)

        # Before 09:30 boundary -> explicit warming status
        assert t.closed_window_metrics("61647", 15, _time(14, 59))["status"] == "WAITING_FIRST_CLOSED_BOUNDARY"

        # At 09:30:00 -> 09:30 vs 09:15
        r_0930 = t.closed_window_metrics("61647", 15, _time(15, 0))
        assert r_0930 is not None
        assert r_0930["oi_delta"] == 30000  # 15 * 2000
        assert r_0930["price_delta"] == 3.0  # 15 * 0.2
        assert r_0930["structure"] == "LONG BUILDUP"
        assert r_0930["window_closed_at"] == "09:30"
        assert r_0930["window_prev_at"] == "09:15"

        # Throughout 09:30:01 to 09:44:59 -> MUST REMAIN FIXED
        r_0940 = t.closed_window_metrics("61647", 15, _time(25, 0))
        r_0944 = t.closed_window_metrics("61647", 15, _time(29, 59))
        assert r_0930 == r_0940 == r_0944

        # At 09:45:00 -> advances to 09:45 vs 09:30
        r_0945 = t.closed_window_metrics("61647", 15, _time(30, 0))
        assert r_0945 is not None
        assert r_0945["window_closed_at"] == "09:45"
        assert r_0945["window_prev_at"] == "09:30"

    def test_contract_isolation_and_zero_contamination(self):
        t = _OiRollingTracker()
        for m in range(0, 16):
            t.record("CE_61647", 500000 + m * 1000, 100.0 + m * 0.5, _time(m))
            t.record("PE_61703", 300000 - m * 1000, 80.0 + m * 0.5, _time(m))

        ce = t.closed_window_metrics("CE_61647", 5, _time(10))
        pe = t.closed_window_metrics("PE_61703", 5, _time(10))
        assert ce is not None
        assert pe is not None
        assert ce["oi_delta"] == 5000
        assert ce["structure"] == "LONG BUILDUP"
        assert pe["oi_delta"] == -5000
        assert pe["structure"] == "SHORT COVERING"

        # Roll to new contract at t=15m
        t.record("NEW_CE_61648", 200000, 50.0, _time(15))
        assert t.closed_window_metrics("NEW_CE_61648", 5, _time(15))["status"] == "WAITING_BOUNDARY_SYNC"
        assert t.closed_window_metrics("NEW_CE_61648", 15, _time(15))["status"] == "WAITING_BOUNDARY_SYNC"

    def test_overnight_session_boundary_rejection(self):
        t = _OiRollingTracker()
        yesterday_dt = datetime(2026, 8, 20, 15, 30, 0, tzinfo=IST)
        t.record("61647", 500000, 120.0, yesterday_dt)
        today_0915 = datetime(2026, 8, 21, 9, 15, 0, tzinfo=IST)
        t.record("61647", 505000, 122.0, today_0915)

        # Before today's 09:20 boundary closes, cannot use yesterday's tick
        assert t.closed_window_metrics("61647", 5, today_0915 + timedelta(minutes=3))["status"] == "WAITING_FIRST_CLOSED_BOUNDARY"

    def test_four_quadrant_classification(self):
        t = _OiRollingTracker()
        base_dt = BASE_SESSION
        b_prev = base_dt  # 09:15
        b_curr = base_dt + timedelta(minutes=5)  # 09:20

        # LONG BUILDUP: OI up + Price up
        t.record("T1", 500000, 100.0, b_prev)
        t.record("T1", 510000, 105.0, b_curr)
        assert t.closed_window_metrics("T1", 5, b_curr)["structure"] == "LONG BUILDUP"

        # SHORT BUILDUP: OI up + Price down
        t.record("T2", 500000, 100.0, b_prev)
        t.record("T2", 510000, 95.0, b_curr)
        assert t.closed_window_metrics("T2", 5, b_curr)["structure"] == "SHORT BUILDUP"

        # SHORT COVERING: OI down + Price up
        t.record("T3", 500000, 100.0, b_prev)
        t.record("T3", 490000, 105.0, b_curr)
        assert t.closed_window_metrics("T3", 5, b_curr)["structure"] == "SHORT COVERING"

        # LONG UNWINDING: OI down + Price down
        t.record("T4", 500000, 100.0, b_prev)
        t.record("T4", 490000, 95.0, b_curr)
        assert t.closed_window_metrics("T4", 5, b_curr)["structure"] == "LONG UNWINDING"

        # FLAT / NEUTRAL
        t.record("T5", 500000, 100.0, b_prev)
        t.record("T5", 500000, 100.0, b_curr)
        assert t.closed_window_metrics("T5", 5, b_curr)["structure"] == "FLAT / NEUTRAL"

    def test_clear_all(self):
        t = _OiRollingTracker()
        t.record("61647", 500000, 120.0, _time(0))
        t.record("61647", 505000, 122.0, _time(5))
        t.clear_all()
        assert t.closed_window_metrics("61647", 5, _time(5))["status"] == "NO_HISTORY"
