from __future__ import annotations

from datetime import datetime, timezone

from src.oracle.reliability import OracleRuntimeStatus, RuntimeProvenance, StartupState


def test_liveness_is_cheap_and_has_no_provider_dependency(tmp_path):
    runtime = OracleRuntimeStatus(RuntimeProvenance(tmp_path))
    value = runtime.liveness()
    assert value["status"] == "LIVE"
    assert value["process_alive"] is True
    assert value["startup_state"] == "STARTING"


def test_ready_distinguishes_market_closed_from_a_stale_packet(tmp_path):
    runtime = OracleRuntimeStatus(RuntimeProvenance(tmp_path))
    runtime.transition(StartupState.READY)
    runtime.update_recovery({"status": "RESTORED"})
    ready = runtime.readiness(
        market_data={
            "WS_CONNECTED": True,
            "BASKET_HEALTH": "MARKET_CLOSED",
            "EXPECTED_INSTRUMENTS": 11,
            "REQUESTED_INSTRUMENTS": 11,
            "FRESH_INSTRUMENTS": 0,
            "instruments": [{"role": "NIFTY_FUTURE", "freshness_state": "STALE"}],
        },
        recorder={"status": "READY", "RECORDER_ALIVE": True},
        order_flow={"status": "AVAILABLE", "flow_pulse": {"revision": 1}},
        argus={"status": "AVAILABLE"},
        ose={"status": "AVAILABLE"},
        fast_lane={"status": "READY"},
        sse_revision=1,
        now=datetime(2026, 8, 12, 11, 0, tzinfo=timezone.utc),
    )
    assert ready["market_session"] == "CLOSED"
    assert ready["full_oracle_ready"] is True
    assert "DHAN_FUTURES_PACKET_STALE" not in ready["blockers"]


def test_ready_reports_exact_open_market_blockers(tmp_path):
    runtime = OracleRuntimeStatus(RuntimeProvenance(tmp_path))
    runtime.transition(StartupState.RECOVERING)
    runtime.update_recovery({"status": "RUNNING"})
    ready = runtime.readiness(
        market_data={
            "WS_CONNECTED": True,
            "BASKET_HEALTH": "DATA_DEGRADED",
            "instruments": [{"role": "NIFTY_FUTURE", "freshness_state": "STALE"}],
        },
        recorder={"status": "DEGRADED", "RECORDER_ALIVE": False},
        order_flow={"status": "UNAVAILABLE"},
        argus={"status": "UNAVAILABLE"},
        ose={"status": "UNAVAILABLE"},
        fast_lane={"status": "STARTING"},
        sse_revision=0,
        now=datetime(2026, 8, 12, 4, 30, tzinfo=timezone.utc),
    )
    assert ready["full_oracle_ready"] is False
    assert set(ready["blockers"]) >= {
        "STARTUP_RECOVERING",
        "RECOVERY_RUNNING",
        "DHAN_FUTURES_PACKET_STALE",
        "DHAN_BASKET_DATA_DEGRADED",
        "RECORDER_DEAD",
        "ORDER_FLOW_NOT_INITIALIZED",
        "FLOW_PULSE_NOT_INITIALIZED",
        "ARGUS_NOT_INITIALIZED",
        "OSE_NOT_INITIALIZED",
        "FAST_LANE_NOT_SERVING",
        "SSE_NOT_PUBLISHED",
    }


def test_provenance_never_exposes_dhan_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "secret-token-value")
    provenance = RuntimeProvenance(tmp_path).snapshot()
    assert provenance["DHAN_TOKEN_FINGERPRINT"]
    assert "secret-token-value" not in str(provenance)


def test_provenance_reports_dirty_worktree(monkeypatch, tmp_path):
    import src.oracle.reliability as reliability

    def git_value(_root, *args):
        return " M app/main.py" if args == ("status", "--porcelain") else "fixture"

    monkeypatch.setattr(reliability, "_git_value", git_value)
    assert reliability.RuntimeProvenance(tmp_path).snapshot()["GIT_DIRTY"] is True


def test_runtime_provenance_has_recovery_code_fingerprint(tmp_path):
    snapshot = RuntimeProvenance(tmp_path).snapshot()
    assert len(snapshot["CODE_FINGERPRINT"]) == 16


def test_noncritical_startup_failure_is_visible_without_revoking_core_readiness(tmp_path):
    runtime = OracleRuntimeStatus(RuntimeProvenance(tmp_path))
    runtime.transition(StartupState.READY)
    runtime.update_recovery({"status": "RESTORED"})
    runtime.note_noncritical_failure("FORECAST", RuntimeError("fixture"))
    ready = runtime.readiness(
        market_data={"WS_CONNECTED": True, "BASKET_HEALTH": "MARKET_CLOSED", "instruments": []},
        recorder={"status": "READY", "RECORDER_ALIVE": True},
        order_flow={"status": "AVAILABLE", "flow_pulse": {"revision": 1}},
        argus={"status": "AVAILABLE"}, ose={"status": "AVAILABLE"},
        fast_lane={"status": "READY"}, sse_revision=1,
        now=datetime(2026, 8, 12, 11, 0, tzinfo=timezone.utc),
    )
    assert ready["full_oracle_ready"] is True
    assert ready["noncritical_startup_warnings"][0]["component"] == "FORECAST"


def test_flow_worker_failure_and_required_loss_are_explicit_readiness_blockers(tmp_path):
    runtime = OracleRuntimeStatus(RuntimeProvenance(tmp_path))
    runtime.transition(StartupState.READY)
    runtime.update_recovery({"status": "RESTORED"})
    ready = runtime.readiness(
        market_data={"WS_CONNECTED": True, "BASKET_HEALTH": "MARKET_CLOSED", "instruments": []},
        recorder={"status": "READY", "RECORDER_ALIVE": True},
        order_flow={
            "status": "AVAILABLE",
            "flow_pulse": {"revision": 1},
            "flow_worker": {"FLOW_WORKER_ALIVE": False, "FLOW_REQUIRED_DROPS": 2},
        },
        argus={"status": "AVAILABLE"}, ose={"status": "AVAILABLE"},
        fast_lane={"status": "READY"}, sse_revision=1,
        now=datetime(2026, 8, 12, 11, 0, tzinfo=timezone.utc),
    )
    assert ready["full_oracle_ready"] is False
    assert "FLOW_WORKER_DEAD" in ready["blockers"]
    assert "FLOW_REQUIRED_PACKET_LOSS" in ready["blockers"]
