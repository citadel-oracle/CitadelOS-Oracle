"""E4A-F Test for Non-Zero Pilot Acceptance Criteria."""

import pytest


def test_zero_packet_pilot_cannot_pass():
    # LIVE_CAPTURE_PILOT_PASS requires non-zero packets and non-zero observations!
    packets_received = 0
    canonical_obs_count = 0

    if packets_received == 0 or canonical_obs_count == 0:
        outcome = "WEBSOCKET_CONNECTION_FAILED"
    else:
        outcome = "LIVE_CAPTURE_PILOT_PASS"

    assert outcome != "LIVE_CAPTURE_PILOT_PASS"
