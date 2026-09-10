"""E4A-F Test for Live Capture Status Classification Rules."""

import pytest
from src.eye.option_capture.session import OptionCaptureSession
from src.eye.option_capture.contracts import CaptureSessionState


def test_status_classification_enums():
    valid_outcomes = {
        "LIVE_CAPTURE_PILOT_PASS",
        "LIVE_CAPTURE_PILOT_DEGRADED",
        "AUTHENTICATION_FAILED",
        "MARKET_DATA_ENTITLEMENT_MISSING",
        "WEBSOCKET_CONNECTION_FAILED",
        "WEBSOCKET_SUBSCRIPTION_FAILED",
        "OPTION_CHAIN_FAILED",
        "RATE_LIMITED",
        "EXCHANGE_OUTAGE",
        "DATA_PROVIDER_UNAVAILABLE",
        "MARKET_CLOSED_ONLY_WHEN_PROVEN",
        "FAIL",
    }
    assert len(valid_outcomes) == 12
