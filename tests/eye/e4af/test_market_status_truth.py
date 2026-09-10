"""E4A-F Test for Market Status Truth Evaluation Engine."""

from datetime import datetime
import dateutil.tz
import pytest
from src.eye.option_capture.market_status import evaluate_market_status, MarketStatus


def test_august_7_2026_10am_is_open():
    tz_ist = dateutil.tz.gettz("Asia/Kolkata")
    dt = datetime(2026, 8, 7, 10, 10, tzinfo=tz_ist)
    status = evaluate_market_status(dt)
    assert status == MarketStatus.OPEN


def test_pre_open_status():
    tz_ist = dateutil.tz.gettz("Asia/Kolkata")
    dt = datetime(2026, 8, 7, 9, 5, tzinfo=tz_ist)
    status = evaluate_market_status(dt)
    assert status == MarketStatus.PRE_OPEN


def test_closed_after_session_status():
    tz_ist = dateutil.tz.gettz("Asia/Kolkata")
    dt = datetime(2026, 8, 7, 16, 0, tzinfo=tz_ist)
    status = evaluate_market_status(dt)
    assert status == MarketStatus.CLOSED_AFTER_SESSION


def test_weekend_status():
    tz_ist = dateutil.tz.gettz("Asia/Kolkata")
    dt = datetime(2026, 8, 8, 11, 0, tzinfo=tz_ist) # Saturday
    status = evaluate_market_status(dt)
    assert status == MarketStatus.WEEKEND


def test_official_holiday_status():
    tz_ist = dateutil.tz.gettz("Asia/Kolkata")
    dt = datetime(2026, 8, 15, 11, 0, tzinfo=tz_ist) # Independence Day
    status = evaluate_market_status(dt)
    assert status == MarketStatus.OFFICIAL_HOLIDAY
