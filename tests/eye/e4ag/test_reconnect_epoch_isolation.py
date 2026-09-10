"""E4A-G Test for Controlled Reconnect & Epoch Isolation."""

import pytest
from src.eye.option_capture.reconciler import FieldReconciler
from src.eye.option_capture.contracts import FeedLane


def test_reconnect_epoch_precedence_and_older_data_rejection():
    reconciler = FieldReconciler()
    key = "OPTCONTRACT:NSE:NSE_FO:43210:NSE:NIFTY:UNDERLYING_INDEX:2026-08-11:2460000:CE:OPTIDX"

    # Connection Epoch 1 update at 10:20:00
    rev1 = reconciler.update_field(
        contract_key=key, field_name="last_price", value=150.0,
        source_lane=FeedLane.FAST_LANE_WEBSOCKET,
        exchange_time_utc="2026-08-07T10:20:00Z",
        received_at_utc="2026-08-07T10:20:00Z",
        available_at_utc="2026-08-07T10:20:00Z",
        connection_epoch=1,
    )
    assert rev1.field_value == 150.0

    # Connection Epoch 2 update at 10:20:10 (clean reconnect)
    rev2 = reconciler.update_field(
        contract_key=key, field_name="last_price", value=152.5,
        source_lane=FeedLane.FAST_LANE_WEBSOCKET,
        exchange_time_utc="2026-08-07T10:20:10Z",
        received_at_utc="2026-08-07T10:20:10Z",
        available_at_utc="2026-08-07T10:20:10Z",
        connection_epoch=2,
    )
    assert rev2.field_value == 152.5

    # Out-of-order delayed packet from Connection Epoch 1 (older timestamp) arriving late
    rev_stale = reconciler.update_field(
        contract_key=key, field_name="last_price", value=148.0,
        source_lane=FeedLane.FAST_LANE_WEBSOCKET,
        exchange_time_utc="2026-08-07T10:20:05Z", # Older than 10:20:10!
        received_at_utc="2026-08-07T10:20:12Z",
        available_at_utc="2026-08-07T10:20:12Z",
        connection_epoch=1,
    )
    # Proven: Older packet from prior epoch cannot overwrite newer state!
    assert rev_stale.field_value == 152.5
