import inspect
import json
from pathlib import Path

from src.api.event_loop_watchdog import EventLoopWatchdog
from src.api.oracle_fast_lane import OracleFastLane
from src.api.v2_integration import V2DashboardIntegration


def test_v2_turbo_mode_changes_scheduling_not_projection_semantics():
    source = inspect.getsource(V2DashboardIntegration._build_dashboard)
    assert "turbo_mode" not in source
    assert V2DashboardIntegration(turbo_mode=False).turbo_mode is False
    assert V2DashboardIntegration(turbo_mode=True).turbo_mode is True


def test_production_parent_v2_rebuild_is_opt_in_and_conditionally_started():
    source = (Path(__file__).parents[2] / "app" / "main.py").read_text()
    assert 'CITADEL_ORACLE_V2_PARENT_REBUILD_ENABLED", "0"' in source
    assert "if ORACLE_V2_PARENT_REBUILD_ENABLED:\n        v2_integration.start" in source
    assert "base_provider=_oracle_fast_base_projection" in source


def test_fast_lane_compatibility_dashboard_reuses_immutable_revision():
    lane = OracleFastLane(base_provider=lambda: {}, providers={})
    body = json.dumps(
        {
            "api_version": "2.0-oracle-fast-lane",
            "revision": 7,
            "feeds": {"oracle": {"ok": True, "data": {"state": "READY"}}},
        }
    ).encode()
    lane._on_published_snapshot(
        {
            "body": body,
            "revision": 7,
            "source_revisions": {"oracle": "1"},
            "changed_sections": ["oracle"],
            "event_id": "snapshot-7",
            "generated_at": "2026-08-14T08:00:00+00:00",
            "patch_event": b"{}",
            "resync_event": b"{}",
            "full_builds": 1,
            "full_serializations": 1,
        }
    )

    first = lane.compatibility_dashboard()
    first["feeds"]["oracle"]["data"]["state"] = "MUTATED"
    second = lane.compatibility_dashboard()

    assert second["feeds"]["oracle"]["data"]["state"] == "READY"
    assert lane.health()["full_builds"] == 1
    assert lane.health()["full_serializations"] == 1


def test_watchdog_health_payload_remains_compact_after_repeated_stalls():
    watchdog = EventLoopWatchdog()
    for index in range(32):
        signature = f"sig-{index % 3}"
        watchdog._stalls.append(
            {
                "signature_id": signature,
                "lag_ms": 300.0 + index,
                "top": {"name": "worker", "top": "src/example.py:1:run"},
                "tasks": [],
                "threads": [],
            }
        )
        aggregate = watchdog._signature_counts.setdefault(
            signature,
            {"signature_id": signature, "count": 0, "max_lag_ms": 0.0, "top": None},
        )
        aggregate["count"] += 1
        aggregate["max_lag_ms"] = 331.0
    watchdog._refresh_snapshot(1.0)

    encoded = json.dumps(watchdog.snapshot()).encode()
    assert len(encoded) < 16_384
    assert len(watchdog.snapshot()["recent_stalls"]) <= 8
    assert len(watchdog.snapshot()["top_stall_signatures"]) <= 8
