"""R2 delivery-semantics tests: lossless calculation, coalesced presentation."""

from __future__ import annotations

import time

import pytest

from src.broker.dhan_full_packet import DhanFullPacketDecoder
from src.oracle.isolated_market_data_gateway import IsolatedMarketDataGateway, _segment_key
from src.oracle.latest_state_lane import FlowPublicationLane
from src.oracle.market_data_gateway import MarketDataGateway
from src.order_flow.recorder import OrderFlowEvidenceRecorder

from tests.order_flow.helpers import full_packet, identity


def _tick(index: int, *, security_id: int = 58072) -> dict:
    now = time.perf_counter_ns()
    return {
        "exchange_segment": "NSE_FNO",
        "security_id": str(security_id),
        "response_code": 8,
        "cumulative_volume": index,
        "decode_done_ns": now,
        "feed_receive_ns": now,
    }


def _full_tick(index: int) -> dict:
    tick = DhanFullPacketDecoder.decode_packet(
        full_packet(security_id=43210, volume=1_000 + index, ltt=1786083900 + index)
    ).to_dict()
    now = time.perf_counter_ns()
    tick.update({
        "feed_generation": 1,
        "feed_receive_ns": now,
        "decode_done_ns": now + 10_000,
        "receive_wall_utc": "2026-08-07T04:45:00+00:00",
        "transport_gap_count": 0,
    })
    return tick


def test_lossless_market_gateway_never_relabels_required_drop_as_coalesce():
    gateway = MarketDataGateway(queue_size=1, lossless_tick_delivery=True)

    for index in range(16):
        gateway._enqueue_tick(_tick(index + 1))
    gateway._enqueue_tick(_tick(17))

    health = gateway.health()
    assert gateway._tick_queue.qsize() == 16
    assert health["FLOW_DELIVERY_SEMANTICS"] == "LOSSLESS_EVENT"
    assert health["FLOW_REQUIRED_DROPS"] == 1
    assert health["coalesced_quote_updates"] == 0


@pytest.mark.parametrize("packets", [64, 128, 320], ids=["1x", "2x", "5x_burst"])
def test_parent_flow_lane_processes_bounded_bursts_without_age_drift(packets: int):
    received: list[int] = []

    def consume(tick: dict) -> None:
        received.append(int(tick["cumulative_volume"]))

    gateway = IsolatedMarketDataGateway(on_tick=consume, queue_size=2_048)
    gateway._parent_stop.clear()
    gateway._start_parent_dispatch()
    try:
        for index in range(packets):
            gateway._flow_ticks.put(_tick(index + 1), timeout=1.0)
        deadline = time.monotonic() + 3.0
        while len(received) < packets and time.monotonic() < deadline:
            time.sleep(0.005)
        health = gateway.health()
        flow = health["PARENT_DATA_PLANE"]
        assert received == list(range(1, packets + 1))
        assert flow["dispatched"]["tick"] >= packets
        assert flow["queue_wait_ms"]["tick"]["max"] < 500.0
    finally:
        gateway._parent_stop.set()
        for thread in (gateway._raw_thread, gateway._tick_thread, gateway._futures_display_thread, gateway._transport_thread):
            if thread is not None:
                thread.join(timeout=1.0)


def test_latest_state_meter_coalescing_cannot_drop_action_transition():
    delivered: list[tuple[str, int]] = []
    lane = FlowPublicationLane(lambda kind, payload: delivered.append((kind, int(payload["revision"]))))
    lane.start()
    try:
        for revision in range(64):
            assert lane.submit("FLOW_PULSE_METERS", {"revision": revision})
        assert lane.submit("FLOW_PULSE_ACTION", {"revision": 65})
        deadline = time.monotonic() + 1.0
        while ("FLOW_PULSE_ACTION", 65) not in delivered and time.monotonic() < deadline:
            time.sleep(0.01)
        health = lane.health()
        assert ("FLOW_PULSE_ACTION", 65) in delivered
        assert health["action_drops"] == 0
        assert health["meter_coalesces"] > 0
    finally:
        lane.stop()


def test_futures_latest_state_role_matches_numeric_dhan_segment():
    assert _segment_key(2) == "NSE_FNO"
    assert _segment_key("2") == "NSE_FNO"
    assert _segment_key("NSE_FNO") == "NSE_FNO"


def test_slow_raw_recorder_callback_cannot_age_the_lossless_flow_lane():
    received: list[int] = []

    def slow_raw(_: dict) -> None:
        time.sleep(0.01)

    gateway = IsolatedMarketDataGateway(
        on_tick=lambda tick: received.append(int(tick["cumulative_volume"])),
        on_raw_packet=slow_raw,
        queue_size=2_048,
    )
    gateway._parent_stop.clear()
    gateway._start_parent_dispatch()
    try:
        for index in range(160):
            value = _tick(index + 1)
            gateway._raw_packets.put(value, timeout=1.0)
            gateway._flow_ticks.put(value, timeout=1.0)
        deadline = time.monotonic() + 2.0
        while len(received) < 160 and time.monotonic() < deadline:
            time.sleep(0.005)
        plane = gateway.health()["PARENT_DATA_PLANE"]
        assert received == list(range(1, 161))
        assert plane["queue_wait_ms"]["tick"]["p99"] < 250.0
    finally:
        gateway._parent_stop.set()
        for thread in (gateway._raw_thread, gateway._tick_thread, gateway._futures_display_thread, gateway._transport_thread):
            if thread is not None:
                thread.join(timeout=2.0)


def test_raw_recorder_lane_remains_available_when_derived_lane_is_full(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path, queue_size=2)
    recorder.register_instruments((identity(),))
    assert recorder.submit("FLOW_PROJECTION", {"snapshot_id": "one"}, "one")
    assert recorder.submit("FLOW_PROJECTION", {"snapshot_id": "two"}, "two")
    assert recorder.submit_full_packet(_full_tick(1))

    health = recorder.health()
    assert health["derived_queue_depth"] == 2
    assert health["raw_queue_depth"] == 1
    assert health["raw_dropped"] == 0

    recorder.start()
    recorder.stop()
    assert recorder.health()["raw_written"] == 1
