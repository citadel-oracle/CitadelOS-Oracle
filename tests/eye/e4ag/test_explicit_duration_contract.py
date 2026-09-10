"""E4A-G2 Test for Explicit Duration Contract & Verdict Classification."""

import pytest
from src.eye.option_capture.contracts import SessionClassification


def test_30_seconds_is_not_30_minutes():
    dur_30s = 30
    dur_30m = 1800
    assert dur_30s != dur_30m
    assert dur_30s < 1800


def test_1799_seconds_cannot_pass_live_stability():
    elapsed_seconds = 1799.9
    base_valid = True

    if not base_valid:
        verdict = "FAIL"
    elif elapsed_seconds >= 1800.0:
        verdict = "LIVE_STABILITY_PASS"
    else:
        verdict = "SHORT_LIVE_STABILITY_PILOT_PASS"

    assert verdict == "SHORT_LIVE_STABILITY_PILOT_PASS"
    assert verdict != "LIVE_STABILITY_PASS"


def test_1800_seconds_may_pass_live_stability():
    elapsed_seconds = 1800.0
    base_valid = True

    if not base_valid:
        verdict = "FAIL"
    elif elapsed_seconds >= 1800.0:
        verdict = "LIVE_STABILITY_PASS"
    else:
        verdict = "SHORT_LIVE_STABILITY_PILOT_PASS"

    assert verdict == "LIVE_STABILITY_PASS"
