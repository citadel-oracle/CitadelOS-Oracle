import pytest
from src.oracle.tradingview_sync import TradingViewAutoSyncService
from src.oracle.async_lanes import IdentityEpoch, CanonicalLiveState

def test_sse_event_monotonic_ids():
    state = CanonicalLiveState()
    
    # Simulate first event
    epoch1 = IdentityEpoch(identity_epoch=1, input_version=1, output_version=1, source_ts=100.0, gateway_received_ts=101.0, calculated_at=102.0, payload={"a": 1})
    state.update_fast(epoch1)
    snap1 = state.snapshot()
    
    # The SSE event ID should be deterministic and monotonically increasing
    # We will test this by ensuring the snapshot exposes a strict revision number
    if "event_revision" not in snap1:
        pytest.fail("CanonicalLiveState must track a monotonic event revision for SSE ordering")
    
    # Simulate a delayed event from an older epoch
    epoch0 = IdentityEpoch(identity_epoch=0, input_version=1, output_version=1, source_ts=90.0, gateway_received_ts=91.0, calculated_at=92.0, payload={"a": 2})
    state.update_fast(epoch0)
    snap2 = state.snapshot()
    
    # Older epoch should be strictly rejected
    assert snap2["fast_state"].get("a") == 1
    assert snap2["event_revision"] == snap1["event_revision"]
