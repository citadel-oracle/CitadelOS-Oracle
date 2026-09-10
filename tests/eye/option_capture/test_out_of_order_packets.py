"""E4A-E Test for Out-of-Order Packet Diagnostics."""

import pytest
from src.eye.option_capture.diagnostics import CaptureDiagnostics


def test_out_of_order_packet_logging(tmp_path):
    diag = CaptureDiagnostics(tmp_path)
    evt = diag.log_event("OUT_OF_ORDER_PACKET", "WARNING", {"expected_seq": 101, "received_seq": 103})

    assert evt["event_type"] == "OUT_OF_ORDER_PACKET"
    assert diag.event_count == 1
