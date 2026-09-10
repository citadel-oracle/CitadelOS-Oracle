"""E4A-F Test for Option Chain REST and WebSocket Cross-Check."""

import pytest
from src.eye.option_capture.reconciler import FieldReconciler
from src.eye.option_capture.contracts import FeedLane


def test_chain_ws_reconciliation_crosscheck():
    reconciler = FieldReconciler()
    key = "OPTCONTRACT:NSE:NSE_FO:43210:NSE:NIFTY:UNDERLYING_INDEX:2026-08-13:2450000:CE:OPTIDX"

    # Fast-lane WebSocket quote at 10:10:05
    rev_ws = reconciler.update_field(
        contract_key=key, field_name="last_price", value=150.25,
        source_lane=FeedLane.FAST_LANE_WEBSOCKET,
        exchange_time_utc="2026-08-07T10:10:05Z",
        received_at_utc="2026-08-07T10:10:05Z",
        available_at_utc="2026-08-07T10:10:05Z",
    )
    assert rev_ws.field_value == 150.25

    # Slow-lane Option Chain update at 10:10:03 (older timestamp)
    rev_oc = reconciler.update_field(
        contract_key=key, field_name="last_price", value=149.80,
        source_lane=FeedLane.SLOW_LANE_OPTION_CHAIN,
        exchange_time_utc="2026-08-07T10:10:03Z",
        received_at_utc="2026-08-07T10:10:06Z",
        available_at_utc="2026-08-07T10:10:06Z",
    )
    # Reconciler enforces precedence: older slow-lane update rejected!
    assert rev_oc.field_value == 150.25
