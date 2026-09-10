"""E4A Time to Expiry Calculation Tests."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.option_evidence.time_to_expiry import calculate_time_to_expiry


def test_time_to_expiry_conventions_and_states():
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    expiry = now + timedelta(days=7)

    res = calculate_time_to_expiry(now, expiry)
    assert res.calendar_days == 7.0
    assert res.expiry_state == "ACTIVE"
    assert res.years_act_365 > 0

    # Same day expiry
    same_day_exp = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    res_same = calculate_time_to_expiry(now, same_day_exp)
    assert res_same.expiry_state == "EXPIRY_DAY"

    # Expired timestamp
    past_now = now + timedelta(days=10)
    res_exp = calculate_time_to_expiry(past_now, expiry)
    assert res_exp.expiry_state == "EXPIRED"
    assert res_exp.calendar_seconds == 0.0
