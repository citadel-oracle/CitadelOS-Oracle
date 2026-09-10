"""Tests for Flow Map V1 visual events and depth snapshots contract."""

from datetime import datetime, timezone
import pytest

from src.order_flow.contracts import InstrumentIdentity
from src.order_flow.service import OrderFlowService
from src.oracle.fast_lane_publisher import _make_lean_live_feed
from tests.order_flow.helpers import full_packet, identity
from tests.order_flow.test_service_replay_gateway import tick


def test_visual_events_buy_sell_unknown_contract():
    """Verify that OrderFlowService records canonical visual events for BUY, SELL, and UNKNOWN trades."""
    service = OrderFlowService(
        clock_ns=lambda: 1_000_000_000,
        wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc),
    )
    identities = (
        identity("43210", "NIFTY_FUTURE"),
    )
    service.register_instruments(identities)

    # Baseline packet 1: establish volume baseline at ltp=100.0, pre_ask=100.0, pre_bid=99.95
    p1 = full_packet(security_id=43210, ltp=100.0, ltq=10, ltt=1786083900, volume=1000, bid=99.95, ask=100.0)
    t1 = tick(p1, receive_ns=1_000_000_000)
    t1["receive_wall_utc"] = "2026-08-07T04:45:00+00:00"
    service.ingest_tick(t1)

    # Packet 2: BUY trade at Ask (ltp=100.0, volume increases by 50, pre_ask was 100.0)
    p2 = full_packet(security_id=43210, ltp=100.0, ltq=50, ltt=1786083901, volume=1050, bid=99.95, ask=100.0)
    t2 = tick(p2, receive_ns=1_001_000_000)
    t2["receive_wall_utc"] = "2026-08-07T04:45:01+00:00"
    service.ingest_tick(t2)

    proj = service.latest_projection()
    assert "visual_events" in proj
    assert "depth_snapshots" in proj
    events = proj["visual_events"]
    assert len(events) >= 1
    buy_event = events[-1]
    assert buy_event["side"] == "BUY"
    assert buy_event["price"] == 100.0
    assert buy_event["observed_qty"] == 50
    assert buy_event["classified_buy_qty"] == 50
    assert buy_event["classified_sell_qty"] == 0
    assert buy_event["unclassified_qty"] == 0
    assert buy_event["time"] == 1786077901
    assert buy_event["classification_method"] == "PRE_EVENT_ASK_TEST"
    assert buy_event["signer_confidence"] == 0.95

    # Packet 3: SELL trade at Bid (ltp=99.95, volume increases by 80, pre_bid was 99.95)
    p3 = full_packet(security_id=43210, ltp=99.95, ltq=80, ltt=1786083902, volume=1130, bid=99.95, ask=100.0)
    t3 = tick(p3, receive_ns=1_002_000_000)
    t3["receive_wall_utc"] = "2026-08-07T04:45:02+00:00"
    service.ingest_tick(t3)

    proj = service.latest_projection()
    events = proj["visual_events"]
    assert len(events) >= 2
    sell_event = events[-1]
    assert sell_event["side"] == "SELL"
    assert sell_event["price"] == 99.95
    assert sell_event["observed_qty"] == 80
    assert sell_event["classified_sell_qty"] == 80
    assert sell_event["time"] == 1786077902
    assert sell_event["classification_method"] == "PRE_EVENT_BID_TEST"
    assert sell_event["signer_confidence"] == 0.95

    # Packet 4: UNKNOWN trade (cumulative volume jump without LTT advance -> 100% UNKNOWN)
    p4 = full_packet(security_id=43210, ltp=99.95, ltq=80, ltt=1786083902, volume=1160, bid=99.95, ask=100.0)
    t4 = tick(p4, receive_ns=1_003_000_000)
    t4["receive_wall_utc"] = "2026-08-07T04:45:03+00:00"
    service.ingest_tick(t4)

    proj = service.latest_projection()
    events = proj["visual_events"]
    assert len(events) >= 3
    unknown_event = events[-1]
    assert unknown_event["side"] == "UNKNOWN"
    assert unknown_event["price"] == 99.95
    assert unknown_event["observed_qty"] == 30
    assert unknown_event["unclassified_qty"] == 30
    assert unknown_event["classified_buy_qty"] == 0
    assert unknown_event["classified_sell_qty"] == 0

    # Verify cvd_series format
    assert "cvd_series" in proj
    assert len(proj["cvd_series"]) >= 3
    assert "cvd" in proj["cvd_series"][-1]

    # Verify depth snapshot format
    depths = proj["depth_snapshots"]
    assert len(depths) >= 1
    latest_depth = depths[-1]
    assert "time" in latest_depth
    assert "bids" in latest_depth
    assert "asks" in latest_depth
    assert len(latest_depth["bids"]) == 5
    assert len(latest_depth["asks"]) == 5
    assert latest_depth["bids"][0]["p"] > 0
    assert latest_depth["bids"][0]["q"] > 0


def test_fast_lane_publisher_bounds_order_flow_feed():
    """Verify that FastLanePublisher bounds visual_events to tail 5000 and depth_snapshots to tail 1000."""
    large_events = [{"event_id": f"ev_{i}", "time": 1000 + i, "price": 24000.0, "side": "BUY"} for i in range(6000)]
    large_depths = [{"time": 1000 + i, "bids": [], "asks": []} for i in range(1200)]
    raw_feed = {
        "ok": True,
        "data": {
            "status": "AVAILABLE",
            "visual_events": large_events,
            "depth_snapshots": large_depths,
        },
    }
    lean = _make_lean_live_feed("order_flow", raw_feed)
    assert len(lean["data"]["visual_events"]) == 5000
    assert len(lean["data"]["depth_snapshots"]) == 1000
    assert lean["data"]["visual_events"][-1]["event_id"] == "ev_5999"


def test_hydrate_visual_history_loads_real_session_cache(tmp_path):
    """Verify that OrderFlowService hydrates visual history from session cache without touching decision engines."""
    import json
    cache_path = tmp_path / "flow_map_visual_history_2026-09-01.json"
    sample_data = {
        "session_date": "2026-09-01",
        "visual_events": [
            {"event_id": "ev_1", "time": 1788256000, "price": 24100.0, "observed_qty": 50, "side": "BUY", "is_absorbed": False, "is_failed_aggression": False},
            {"event_id": "ev_2", "time": 1788256050, "price": 24095.0, "observed_qty": 80, "side": "SELL", "is_absorbed": True, "is_failed_aggression": True},
        ],
        "depth_snapshots": [
            {"time": 1788256000, "bids": [{"p": 24095, "q": 100, "o": 2}], "asks": [{"p": 24100, "q": 150, "o": 3}]},
        ],
        "cvd_series": [
            {"time": 1788256000, "cvd": -50000},
            {"time": 1788256050, "cvd": -50080},
        ],
        "cvd": -50080,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(sample_data, f)

    class MockRecorder:
        root = tmp_path

    service = OrderFlowService(recorder=MockRecorder())
    count = service.hydrate_visual_history("2026-09-01")
    assert count == 2

    proj = service.latest_projection()
    assert len(proj["visual_events"]) == 2
    assert proj["visual_events"][0]["event_id"] == "ev_1"
    assert proj["visual_events"][1]["is_absorbed"] is True
    assert len(proj["depth_snapshots"]) == 1
    assert len(proj["cvd_series"]) == 2
    assert proj["cvd"] == -50080

