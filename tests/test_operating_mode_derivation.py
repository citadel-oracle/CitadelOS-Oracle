"""Focused unit tests for NSE operating mode derivation in CanonicalStatusEngine."""

import pytest
from datetime import datetime, time
from zoneinfo import ZoneInfo

from src.system_status import CanonicalStatusEngine, IST

pytestmark = pytest.mark.unit


def _ist_datetime(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


def test_trading_weekday_before_pre_open_0859_ist():
    # Tuesday 2026-07-21 at 08:59 IST
    dt = _ist_datetime(2026, 7, 21, 8, 59)
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt)
    assert res["operating_mode"] == "MARKET_CLOSED"
    assert res["reason_code"] == "BEFORE_PRE_OPEN"
    assert res["trading_date"] == "2026-07-21"


def test_trading_weekday_pre_open_0900_to_0914_ist():
    # Tuesday 2026-07-21 at 09:05 IST
    dt = _ist_datetime(2026, 7, 21, 9, 5)
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt)
    assert res["operating_mode"] == "PRE_MARKET"
    assert res["reason_code"] == "NSE_PRE_OPEN"


def test_trading_weekday_market_open_0915_ist():
    # Tuesday 2026-07-21 at 09:15 IST
    dt = _ist_datetime(2026, 7, 21, 9, 15)
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt)
    assert res["operating_mode"] == "MARKET_OPEN"
    assert res["reason_code"] == "NSE_REGULAR_SESSION"


def test_trading_weekday_market_open_1400_ist():
    # Tuesday 2026-07-21 at 14:00 IST (Active market)
    dt = _ist_datetime(2026, 7, 21, 14, 0)
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt)
    assert res["operating_mode"] == "MARKET_OPEN"
    assert res["reason_code"] == "NSE_REGULAR_SESSION"


def test_trading_weekday_market_close_boundary_1530_ist():
    # Tuesday 2026-07-21 at 15:30 IST
    dt = _ist_datetime(2026, 7, 21, 15, 30)
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt)
    assert res["operating_mode"] == "POST_MARKET"
    assert res["reason_code"] == "NSE_POST_MARKET_SESSION"


def test_trading_weekday_post_market():
    # Tuesday 2026-07-21 at 16:00 IST
    dt = _ist_datetime(2026, 7, 21, 16, 0)
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt)
    assert res["operating_mode"] == "POST_MARKET"
    assert res["reason_code"] == "NSE_POST_MARKET_SESSION"


def test_weekend_closed():
    # Saturday 2026-07-25 at 11:00 IST
    dt = _ist_datetime(2026, 7, 25, 11, 0)
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt)
    assert res["operating_mode"] == "MARKET_CLOSED"
    assert res["reason_code"] == "NSE_WEEKEND_CLOSED"


def test_configured_exchange_holiday():
    # Republic Day 2026-01-26 (Monday) at 10:00 IST
    dt = _ist_datetime(2026, 1, 26, 10, 0)
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt)
    assert res["operating_mode"] == "MARKET_CLOSED"
    assert "HOLIDAY" in res["reason_code"]


def test_utc_and_ist_conversion_exposed():
    # UTC input: 2026-07-21 08:30:00 UTC = 2026-07-21 14:00:00 IST
    dt_utc = datetime(2026, 7, 21, 8, 30, tzinfo=ZoneInfo("UTC"))
    res = CanonicalStatusEngine.evaluate(now_provider=lambda: dt_utc)
    assert res["operating_mode"] == "MARKET_OPEN"
    assert "2026-07-21T08:30:00+00:00" in res["server_time_utc"]
    assert "2026-07-21T14:00:00+05:30" in res["exchange_time_ist"]
    assert res["trading_date"] == "2026-07-21"
