"""E4A-E Test for Dual-Lane Field Provenance & Reconciliation."""

from datetime import datetime, timezone
import pytest
from src.eye.option_capture.reconciler import FieldReconciler
from src.eye.option_capture.contracts import FeedLane


def test_older_chain_cannot_overwrite_newer_websocket_quote():
    reconciler = FieldReconciler()
    key = "OPTCONTRACT:NSE:NSE_FO:NIFTY:2026-08-13:24500.0:CE"

    # Fast lane WebSocket update at 09:15:10
    rev1 = reconciler.update_field(
        contract_key=key, field_name="best_bid", value=150.0,
        source_lane=FeedLane.FAST_LANE_WEBSOCKET,
        exchange_time_utc="2026-08-07T09:15:10Z",
        received_at_utc="2026-08-07T09:15:10Z",
        available_at_utc="2026-08-07T09:15:10Z",
    )
    assert rev1.field_value == 150.0

    # Older slow lane Option Chain update at 09:15:05 attempts to overwrite
    rev2 = reconciler.update_field(
        contract_key=key, field_name="best_bid", value=145.0,
        source_lane=FeedLane.SLOW_LANE_OPTION_CHAIN,
        exchange_time_utc="2026-08-07T09:15:05Z",
        received_at_utc="2026-08-07T09:15:12Z",
        available_at_utc="2026-08-07T09:15:12Z",
    )

    # Older chain overwrite must be ignored; rev2 returns rev1!
    assert rev2.field_value == 150.0
