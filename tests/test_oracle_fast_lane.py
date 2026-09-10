from __future__ import annotations

import json
from time import monotonic, perf_counter_ns, sleep

from src.api.oracle_fast_lane import OracleFastLane
from src.oracle.fast_lane_publisher import FastLaneSnapshotProcessor, _make_lean_live_feed


def _wire_event(event):
    """FastAPI/SSE serves the prepared bytes; parent metadata stays lightweight."""

    return json.loads(event["_encoded"])


def test_fast_lane_serves_pre_serialized_cache_and_atomic_feed_patches():
    state = {
        "argus": {"status": "LIVE", "snapshot_id": "argus-a", "source_timestamp": "2026-08-10T09:30:00Z"},
        "chart": {"status": "AVAILABLE", "content_hash": "chart-a", "source_timestamp": "2026-08-10T09:30:00Z"},
    }
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {"oracle": {"data": {"status": "READY"}}}},
        providers={"argus": lambda: dict(state["argus"])},
        chart_provider=lambda: dict(state["chart"]),
        interval_seconds=0.1,
        base_interval_seconds=5,
    )
    lane.start()
    try:
        for _ in range(30):
            try:
                body, _ = lane.response()
                break
            except RuntimeError:
                sleep(0.02)
        else:
            raise AssertionError("fast lane did not publish")
        first = json.loads(body)
        assert first["feeds"]["argus"]["data"]["snapshot_id"] == "argus-a"
        assert first["runtime_instance_id"] == lane.health()["runtime_instance_id"]
        assert first["safety"]["execution_influence"] == "ZERO"
        stages = lane.health()["latest_latency_stages"]
        assert stages["fastlane_build_start_ns"] <= stages["fastlane_value_tree_done_ns"]
        assert stages["fastlane_serialization_start_ns"] <= stages["fastlane_serialized_ns"]

        state["argus"] = {"status": "LIVE", "snapshot_id": "argus-b", "source_timestamp": "2026-08-10T09:30:01Z"}
        for _ in range(30):
            sleep(0.02)
            current = json.loads(lane.response()[0])
            if current["feeds"]["argus"]["data"]["snapshot_id"] == "argus-b":
                break
        assert current["feeds"]["argus"]["data"]["snapshot_id"] == "argus-b"
        events = lane.wait_for_events(None, 0)
        assert _wire_event(events[-1])["feeds"]["argus"]["data"]["snapshot_id"] == "argus-b"
        assert lane.health()["payload_size"] == len(lane.response()[0])
    finally:
        lane.stop()


def test_fast_lane_preserves_truthful_degraded_source_state():
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={},
    )
    feed = lane._feed(
        "argus",
        {"status": "LAST_GOOD", "reason": "SOURCE_INCOMPLETE", "source_timestamp": "2026-08-10T09:30:00Z"},
        None,
    )
    assert feed["meta"]["freshness"] == "STALE"
    assert feed["meta"]["stale_reason"] == "SOURCE_INCOMPLETE"
    assert feed["meta"]["source_timestamp"] == "2026-08-10T09:30:00Z"


def test_base_oracle_refresh_preserves_existing_live_workspace():
    processor = FastLaneSnapshotProcessor()
    first = processor("BUILD", {
        "source_revisions": {"oracle": "base-1", "oracle_live_workspace": "workspace-1"},
        "changed": ["oracle", "oracle_live_workspace"],
        "base_updates": {"oracle": {"ok": True, "data": {"status": "READY", "revision": 1}}},
        "workspace_update": {"value": {"sync_state": "SYNCED", "content_hash": "workspace-a"}, "error": None},
        "build_revision": 1,
    })
    assert json.loads(first["body"])["feeds"]["oracle"]["data"]["live_workspace"]["content_hash"] == "workspace-a"

    refreshed = processor("BUILD", {
        "source_revisions": {"oracle": "base-2", "oracle_live_workspace": "workspace-1"},
        "changed": ["oracle"],
        "base_updates": {"oracle": {"ok": True, "data": {"status": "READY", "revision": 2}}},
        "build_revision": 2,
    })
    oracle = json.loads(refreshed["body"])["feeds"]["oracle"]["data"]
    assert oracle["revision"] == 2
    assert oracle["live_workspace"] == {"sync_state": "SYNCED", "content_hash": "workspace-a"}


def test_fast_lane_runtime_identity_is_in_rest_and_sse_contracts():
    processor = FastLaneSnapshotProcessor()
    result = processor("BUILD", {
        "runtime_instance_id": "runtime-a",
        "source_revisions": {"argus": "a"},
        "changed": ["argus"],
        "provider_updates": {"argus": {"value": {"status": "LIVE"}, "error": None}},
        "build_revision": 7,
    })
    assert json.loads(result["body"])["runtime_instance_id"] == "runtime-a"
    assert json.loads(result["patch_event"])["runtime_instance_id"] == "runtime-a"
    assert result["runtime_instance_id"] == "runtime-a"
    stages = result["latency_stages"]
    assert stages["fastlane_build_start_ns"] <= stages["fastlane_value_tree_done_ns"]
    assert stages["fastlane_serialization_start_ns"] <= stages["fastlane_serialized_ns"]


def test_fast_lane_chart_keeps_four_bounded_finalized_timeframe_lanes():
    def candles(count, *, forming=False):
        return [
            {"time": index, "open": 1, "high": 2, "low": 0, "close": 1, "is_forming": forming and index == count - 1}
            for index in range(count)
        ]

    feed = {"ok": True, "data": {
        "candles": candles(140, forming=True),
        "timeframes": {
            timeframe: {"candles": candles(140, forming=True), "vwap_series": list(range(140))}
            for timeframe in ("1m", "3m", "5m", "15m")
        },
    }}
    lean = _make_lean_live_feed("futures_chart", feed)["data"]
    assert lean["available_timeframes"] == ["1m", "3m", "5m", "15m"]
    assert len(lean["candles"]) == 100
    assert lean["candles"][-1]["time"] == 138
    for timeframe in lean["available_timeframes"]:
        assert len(lean["timeframes"][timeframe]["candles"]) == 100
        assert lean["timeframes"][timeframe]["candles"][-1]["time"] == 138
        assert len(lean["timeframes"][timeframe]["vwap_series"]) == 100


def test_fast_lane_can_refresh_one_provider_after_atomic_restore():
    state = {"value": {"status": "UNAVAILABLE"}}
    lane = OracleFastLane(base_provider=lambda: {"feeds": {}}, providers={"order_flow": lambda: dict(state["value"])})
    assert lane.refresh_provider("order_flow") is True
    state["value"] = {"status": "AVAILABLE", "flow_pulse": {"revision": 7}}
    assert lane.refresh_provider("order_flow") is True
    lane._publish({"order_flow"})
    payload = json.loads(lane.response()[0])
    assert payload["feeds"]["order_flow"]["ok"] is True
    assert lane.health()["core_feeds"]["order_flow"]["readiness"] == "READY"


def test_fast_lane_revision_tracks_cache_only_status_and_flow_pulse_revision():
    unavailable = OracleFastLane._revision({"status": "UNAVAILABLE"}, None)
    restored = OracleFastLane._revision(
        {"status": "AVAILABLE", "flow_pulse": {"revision": 7}}, None
    )
    advanced = OracleFastLane._revision(
        {"status": "AVAILABLE", "flow_pulse": {"revision": 8}}, None
    )
    assert unavailable != restored
    assert restored != advanced


def test_fast_lane_revision_tracks_packet_health_and_subscription_changes():
    first = OracleFastLane._revision(
        {"status": "AVAILABLE", "transport": {"SUBSCRIPTION_REVISION": 1, "EXPECTED_INSTRUMENTS": 1}},
        None,
    )
    second = OracleFastLane._revision(
        {"status": "AVAILABLE", "transport": {"SUBSCRIPTION_REVISION": 2, "EXPECTED_INSTRUMENTS": 11}},
        None,
    )
    assert first != second


def test_fast_lane_publishes_ose_source_revision_without_waiting_for_base_dashboard():
    state = {
        "source_timestamp": "2026-08-12T15:28:50+05:30",
        "status": "LIVE",
        "option_flow": {"status": "LIVE", "balance_marker": 52.0},
        "participation_baseline": {"status": "LIVE", "calculation_revision": "bw-a"},
    }
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {"strategy_lab": {"data": {"execution": {}}}}},
        providers={"options_structure": lambda: dict(state)},
        interval_seconds=0.01,
        base_interval_seconds=60,
    )
    lane.start()
    try:
        deadline = monotonic() + 1.0
        while monotonic() < deadline:
            try:
                payload = json.loads(lane.response()[0])
                if payload["feeds"].get("options_structure"):
                    break
            except RuntimeError:
                pass
            sleep(0.01)
        assert payload["feeds"]["options_structure"]["data"]["option_flow"]["status"] == "LIVE"
        state.update(source_timestamp="2026-08-12T15:28:55+05:30")
        state["participation_baseline"] = {"status": "LIVE", "calculation_revision": "bw-b"}
        deadline = monotonic() + 0.5
        while monotonic() < deadline:
            events = lane.wait_for_events(None, 0)
            wire = _wire_event(events[-1]) if events else {}
            if wire.get("feeds", {}).get("options_structure", {}).get("data", {}).get("source_timestamp") == state["source_timestamp"]:
                break
            sleep(0.01)
        event = _wire_event(events[-1])
        assert set(event["feeds"]) == {"options_structure"}
        assert event["feeds"]["options_structure"]["data"]["participation_baseline"]["calculation_revision"] == "bw-b"
    finally:
        lane.stop()


def test_fast_lane_sse_patch_contains_only_changed_current_feed_not_full_snapshot():
    state = {"argus": "a", "order_flow": "a"}
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {"strategy_lab": {"data": {"history": list(range(1000))}}}},
        providers={
            "argus": lambda: {"snapshot_id": state["argus"]},
            "order_flow": lambda: {"snapshot_id": state["order_flow"]},
        },
        interval_seconds=0.01,
        base_interval_seconds=5,
    )
    lane.start()
    try:
        deadline = monotonic() + 1.0
        while monotonic() < deadline:
            try:
                json.loads(lane.response()[0])
                break
            except RuntimeError:
                sleep(0.01)
        lane.wait_for_events(None, 0)
        state["argus"] = "b"
        deadline = monotonic() + 0.5
        while monotonic() < deadline:
            events = lane.wait_for_events(None, 0)
            wire = _wire_event(events[-1]) if events else {}
            if wire.get("feeds", {}).get("argus", {}).get("data", {}).get("snapshot_id") == "b":
                break
            sleep(0.01)
        event = _wire_event(events[-1])
        assert event["full"] is False
        assert set(event["feeds"]) == {"argus"}
        assert "strategy_lab" not in event["feeds"]
    finally:
        lane.stop()


def test_slow_optional_provider_cannot_block_critical_cached_publication():
    state = {"critical": "a"}
    calls = {"slow": 0}

    def slow_optional():
        calls["slow"] += 1
        sleep(0.6)
        return {"status": "AVAILABLE", "revision": "slow"}

    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={
            "order_flow": lambda: {"status": "AVAILABLE", "snapshot_id": state["critical"]},
            "comparison": slow_optional,
        },
        interval_seconds=0.1,
        base_interval_seconds=5,
        provider_intervals={"comparison": 1.0},
    )
    lane.start()
    try:
        deadline = monotonic() + 1.0
        while monotonic() < deadline:
            try:
                if json.loads(lane.response()[0])["feeds"].get("order_flow"):
                    break
            except RuntimeError:
                pass
            sleep(0.01)
        state["critical"] = "b"
        started = monotonic()
        while monotonic() - started < 0.45:
            current = json.loads(lane.response()[0])
            if current["feeds"]["order_flow"]["data"]["snapshot_id"] == "b":
                break
            sleep(0.01)
        assert current["feeds"]["order_flow"]["data"]["snapshot_id"] == "b"
        assert monotonic() - started < 0.45
        assert calls["slow"] == 1
    finally:
        lane.stop()


def test_provider_changes_are_coalesced_into_one_atomic_publication_cadence():
    state = {"argus": "a", "order_flow": "a"}
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={
            "argus": lambda: {"snapshot_id": state["argus"]},
            "order_flow": lambda: {"snapshot_id": state["order_flow"]},
        },
        interval_seconds=0.1,
        base_interval_seconds=5,
    )
    lane.start()
    try:
        deadline = monotonic() + 1.0
        while monotonic() < deadline:
            try:
                if len(json.loads(lane.response()[0])["feeds"]) == 2:
                    break
            except RuntimeError:
                pass
            sleep(0.01)
        initial_sequence = lane.health()["revision"]
        state.update(argus="b", order_flow="b")
        deadline = monotonic() + 0.5
        while monotonic() < deadline:
            current = json.loads(lane.response()[0])
            if (
                current["feeds"]["argus"]["data"]["snapshot_id"] == "b"
                and current["feeds"]["order_flow"]["data"]["snapshot_id"] == "b"
            ):
                break
            sleep(0.01)
        assert current["feeds"]["argus"]["data"]["snapshot_id"] == "b"
        assert current["feeds"]["order_flow"]["data"]["snapshot_id"] == "b"
        assert lane.health()["revision"] <= initial_sequence + 2
    finally:
        lane.stop()


def test_complete_snapshot_cadence_bounds_provider_refreshes():
    """A full REST resync must never inherit packet-rate refresh scheduling."""

    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={"order_flow": lambda: {"status": "AVAILABLE"}},
        interval_seconds=1.0,
        provider_intervals={"order_flow": 0.1},
    )
    # The compact Flow event path remains separate; this floor governs only
    # full snapshot provider refresh/assembly in the backend process.
    assert lane.provider_intervals["order_flow"] == 1.0


def test_fast_lane_reuses_unchanged_large_feed_bytes_on_live_revision():
    """A tiny current-state change must not rebuild immutable research feeds."""

    state = {"revision": "a"}
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={"order_flow": lambda: {"status": "AVAILABLE", "snapshot_id": state["revision"]}},
    )
    lane._base = {
        "feeds": {
            "strategy_lab": {"ok": True, "data": {"history": list(range(10_000))}},
        }
    }
    assert lane.refresh_provider("order_flow")
    lane._publish({"strategy_lab", "order_flow"})
    first = lane.health()
    assert first["feed_cache_builds"] == 2

    state["revision"] = "b"
    assert lane.refresh_provider("order_flow")
    lane._publish({"order_flow"})
    second = lane.health()
    assert second["feed_cache_builds"] == 3
    assert second["feed_cache_reuses"] >= 1
    assert json.loads(lane.response()[0])["feeds"]["strategy_lab"]["data"]["history"][-1] == 9_999


def test_flow_pulse_action_is_immediate_compact_and_uses_existing_event_queue():
    lane = OracleFastLane(base_provider=lambda: {"feeds": {}}, providers={})
    started = monotonic()
    packet_receive_ns = perf_counter_ns()
    lane.publish_flow_pulse("FLOW_PULSE_ACTION", {
        "headline": "BUY PE", "model": "MODEL 2 · TREND", "story": "SELLERS BACK",
        "key_level": {"label": "PDL 24600"}, "trigger": 24595.0,
        "option": {"strike": 24500, "option_type": "PE", "ask": 63.35},
        "stop": 24600.0, "target_1": 24580.0, "target_2": 24560.0,
        "episode_state": "BUY PE · CONFIRMED",
        "packet_receive_ns": packet_receive_ns,
    })
    [event] = lane.wait_for_events(None, 0)
    assert monotonic() - started < 0.1
    assert event["event_type"] == "FLOW_PULSE_ACTION"
    assert event["flow_pulse"]["headline"] == "BUY PE"
    assert "feeds" not in event
    assert len(event["_encoded"]) < 2_000
    lane.record_sse_yield(event, len(event["_encoded"]) + 64)
    health = lane.health()
    assert health["action_serialization_ms"]["p99"] is not None
    assert health["packet_to_action_event_ms"]["p99"] < 100
    assert health["event_to_sse_yield_ms"]["p99"] < 100


def test_flow_pulse_meters_are_coalesced_not_serialized_per_raw_packet():
    lane = OracleFastLane(base_provider=lambda: {"feeds": {}}, providers={}, interval_seconds=0.1)
    lane.start()
    try:
        for revision in range(100):
            lane.publish_flow_pulse("FLOW_PULSE_METERS", {"revision": revision, "semantic": {"pressure": "SELLERS ACTIVE"}})
        deadline = monotonic() + 0.5
        while monotonic() < deadline:
            events = lane.wait_for_events(None, 0)
            if events and events[-1]["event_type"] == "FLOW_PULSE_METERS":
                break
            sleep(0.01)
        assert events[-1]["flow_pulse"]["revision"] == 99
        assert lane.health()["meter_serialization_ms"]["p99"] is not None
    finally:
        lane.stop()


def test_sse_waits_for_a_new_revision_and_resyncs_a_lagging_client_once():
    state = {"revision": "a"}
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={"order_flow": lambda: {"snapshot_id": state["revision"]}},
    )
    assert lane.refresh_provider("order_flow")
    lane._publish({"order_flow"})
    [first] = lane.wait_for_events(None, 0)

    state["revision"] = "b"
    assert lane.refresh_provider("order_flow")
    lane._publish({"order_flow"})
    state["revision"] = "c"
    assert lane.refresh_provider("order_flow")
    lane._publish({"order_flow"})

    [resync] = lane.wait_for_events(first["event_id"], 0)
    assert resync["event_type"] == "ORACLE_FAST_LANE_RESYNC"
    assert resync["full"] is True
    assert _wire_event(resync)["feeds"]["order_flow"]["data"]["snapshot_id"] == "c"
    assert lane.health()["sse_coalesced_events"] == 1

    started = monotonic()
    assert lane.wait_for_events(resync["event_id"], 0.04) == []
    assert monotonic() - started >= 0.03


def test_one_hundred_gets_reuse_one_immutable_serialized_revision():
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={"order_flow": lambda: {"status": "AVAILABLE", "snapshot_id": "fixed"}},
    )
    assert lane.refresh_provider("order_flow")
    lane._publish({"order_flow"})
    before = lane.health()
    original = lane.response()[0]
    for _ in range(99):
        assert lane.response()[0] is original
    after = lane.health()
    assert after["full_builds"] == before["full_builds"] == 1
    assert after["full_serializations"] == before["full_serializations"] == 1
    assert after["http_serves"] - before["http_serves"] == 100


def test_one_hundred_sse_recoveries_reuse_one_prepared_full_event():
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={"order_flow": lambda: {"status": "AVAILABLE", "snapshot_id": "fixed"}},
    )
    assert lane.refresh_provider("order_flow")
    lane._publish({"order_flow"})
    before = lane.health()
    prepared = None
    for _ in range(100):
        [event] = lane.wait_for_events("client-revision-not-in-window", 0)
        assert event["event_type"] == "ORACLE_FAST_LANE_RESYNC"
        if prepared is None:
            prepared = event["_encoded"]
        else:
            assert event["_encoded"] is prepared
    after = lane.health()
    assert after["full_builds"] == before["full_builds"] == 1
    assert after["full_serializations"] == before["full_serializations"] == 1
    assert after["sse_full_resyncs"] - before["sse_full_resyncs"] == 100


def test_published_revision_cannot_be_mutated_by_later_provider_state():
    provider = {"status": "AVAILABLE", "snapshot_id": "a", "nested": {"value": 1}}
    lane = OracleFastLane(base_provider=lambda: {"feeds": {}}, providers={})
    lane._values["order_flow"] = provider
    lane._revisions["order_flow"] = "a"
    lane._publish({"order_flow"})
    revision_a = lane.response()[0]
    provider["nested"]["value"] = 999
    assert json.loads(revision_a)["feeds"]["order_flow"]["data"]["nested"]["value"] == 1

    lane._revisions["order_flow"] = "b"
    lane._publish({"order_flow"})
    revision_b = lane.response()[0]
    assert revision_b is not revision_a
    assert json.loads(revision_b)["feeds"]["order_flow"]["data"]["nested"]["value"] == 999
    assert json.loads(revision_a)["feeds"]["order_flow"]["data"]["nested"]["value"] == 1


def test_lagging_compact_meter_updates_coalesce_without_full_resync():
    lane = OracleFastLane(base_provider=lambda: {"feeds": {}}, providers={})
    lane._publish_compact("FLOW_PULSE_METERS", {"revision": 1})
    [first] = lane.wait_for_events(None, 0)
    lane._publish_compact("FLOW_PULSE_METERS", {"revision": 2})
    lane._publish_compact("FLOW_PULSE_METERS", {"revision": 3})
    [latest] = lane.wait_for_events(first["event_id"], 0)
    assert latest["event_type"] == "FLOW_PULSE_METERS"
    assert latest["flow_pulse"]["revision"] == 3
    assert lane.health()["sse_full_resyncs"] == 0


def test_fast_lane_publisher_has_one_owned_process_and_clean_shutdown():
    lane = OracleFastLane(base_provider=lambda: {"feeds": {}}, providers={})
    assert lane.start_publisher() is True
    try:
        status = lane.health()["publisher"]
        assert status["role"] == "fast_lane_publisher"
        assert status["alive"] is True
        assert isinstance(status["pid"], int)
        assert status["pid"] > 0
        assert lane.start_publisher() is False
        assert lane.health()["publisher"]["pid"] == status["pid"]
    finally:
        lane.stop()
    assert lane.health()["publisher"]["alive"] is False


def test_push_provider_is_published_once_without_parent_poll_thread():
    calls = {"count": 0}

    def provider():
        calls["count"] += 1
        return {"snapshot_id": "polled"}

    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={"argus": provider},
        push_providers={"argus"},
        interval_seconds=0.1,
    )
    lane.start()
    try:
        assert lane.publish_provider_value("argus", {"snapshot_id": "pushed"})
        deadline = monotonic() + 1.0
        while monotonic() < deadline:
            try:
                payload = json.loads(lane.response()[0])
            except RuntimeError:
                sleep(0.01)
                continue
            if payload["feeds"].get("argus"):
                break
        assert payload["feeds"]["argus"]["data"]["snapshot_id"] == "pushed"
        assert calls["count"] == 0
    finally:
        lane.stop()
