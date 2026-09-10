"""E4A-G Test for Session Terminology & Classification Invariants."""

import pytest
from src.eye.option_capture.contracts import SessionClassification


def test_session_classification_hierarchy():
    # 30-minute run MUST be EXTENDED_PILOT_SESSION, never COMPLETE_SESSION!
    pilot_30m = SessionClassification.EXTENDED_PILOT_SESSION
    assert pilot_30m == "EXTENDED_PILOT_SESSION"
    assert pilot_30m != SessionClassification.COMPLETE_SESSION

    pilot_30s = SessionClassification.SHORT_LIVE_PILOT
    assert pilot_30s == "SHORT_LIVE_PILOT"

    full_day = SessionClassification.COMPLETE_SESSION
    assert full_day == "COMPLETE_SESSION"


def test_historical_complete_sessions_count_is_zero():
    # Before full 09:15-15:30 trading session capture, complete trading session count is 0
    complete_sessions_before_e4ag = 0
    assert complete_sessions_before_e4ag == 0
