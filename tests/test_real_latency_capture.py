from __future__ import annotations

from tools.audit import capture_real_latency as capture


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_direct_latency_row_requires_real_monotonic_boundaries():
    common = {
        "stage": "FASTLANE_BUILD",
        "sample_id": "runtime:1",
        "revision": 1,
        "runtime_generation": "runtime",
        "session_generation": 2,
        "security_id": "43210",
        "t0_key": "start_ns",
        "t1_key": "end_ns",
    }
    assert capture._direct_row(source={"end_ns": 2_000_000}, **common) is None
    row = capture._direct_row(
        source={"start_ns": 1_000_000, "end_ns": 2_250_000}, **common
    )
    assert row["t0_ns"] == 1_000_000
    assert row["t1_ns"] == 2_250_000
    assert row["delta_ms"] == 1.25


def test_collector_uses_unique_revision_and_unique_invocation_only(monkeypatch):
    fast_lane = {
        "runtime_instance_id": "runtime-a",
        "revision": 7,
        "source_metadata": {"session_generation": 3},
        "polling": {
            "fastlane_build_start_ns": 1_000_000,
            "fastlane_value_tree_done_ns": 3_000_000,
            "fastlane_serialization_start_ns": 3_000_000,
            "fastlane_serialized_ns": 4_000_000,
            "assembly_ms": 999.0,
        },
    }
    sol = {
        "runtime_instance_id": "sol-a",
        "session_generation": 3,
        "state_revision": 9,
        "health_strip": {"last_latency_ms": 999_999.0},
        "provider_telemetry": {
            "invocation_id": "invocation-1",
            "invocation_started_ns": 5_000_000,
            "invocation_completed_ns": 11_000_000,
        },
    }

    fast_lane["latest_latency_stages"] = fast_lane.pop("polling")

    def fake_get(url, timeout):
        return _Response(fast_lane if url == capture.FAST_LANE_HEALTH_URL else sol)

    monkeypatch.setattr(capture.requests, "get", fake_get)
    monkeypatch.setattr(capture.time, "sleep", lambda _: None)
    samples = capture.collect_real_latency_samples(n_samples=1)

    assert len(samples["FASTLANE_BUILD"]) == 1
    assert samples["FASTLANE_BUILD"][0]["delta_ms"] == 2.0
    assert samples["FASTLANE_SERIALIZATION"][0]["delta_ms"] == 1.0
    assert len(samples["GEMINI_PROVIDER"]) == 1
    assert samples["GEMINI_PROVIDER"][0]["sample_id"] == "invocation-1"
    assert samples["GEMINI_PROVIDER"][0]["delta_ms"] == 6.0
