import json
from datetime import datetime, timezone

import pytest

from app.main import app
from app.main import strategy_lab_operations
from src.operations.production import (
    HealthState,
    InstitutionalKillSwitch,
    OperationalMonitorLoop,
    OperationalRecovery,
    ProductionCertification,
    ProductionHealthMonitor,
    ProductionOperationsService,
    StructuredEventLogger,
)
from src.risk.authorization import RiskControlStore


pytestmark = [pytest.mark.unit, pytest.mark.safety]
NOW = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)


def logger(tmp_path):
    return StructuredEventLogger(tmp_path / "events.jsonl", clock=lambda: NOW)


def initialized_store(tmp_path, active=False):
    store = RiskControlStore(tmp_path / "risk.json")
    store.initialize(active, "INITIAL", "test")
    return store


def healthy_providers():
    return {
        "scheduler": lambda: {"status": "HEALTHY", "heartbeat": NOW.isoformat()},
        "broker": lambda: {"status": "DISABLED_SAFE"},
        "websocket": lambda: {"status": "DISABLED_SAFE"},
        "quotes": lambda: {"status": "DISABLED_SAFE"},
        "strategy_runtime": lambda: {"status": "HEALTHY"},
        "paper_engine": lambda: {"status": "HEALTHY"},
        "runtime_latency": lambda: {"status": "HEALTHY", "latency_ms": 5},
        "processing_queue": lambda: {"status": "HEALTHY", "depth": 0},
        "exceptions": lambda: {"status": "HEALTHY", "exceptions": 0},
    }


def test_structured_logging_has_mandatory_envelope_and_redacts_secrets(tmp_path):
    log = logger(tmp_path)
    row = log.log(
        "entry_submitted",
        strategy="pullback-master",
        runtime_mode="paper",
        correlation_id="corr-1",
        symbol="nifty",
        timeframe="3m",
        latency_ms=1.23456,
        status="submitted",
        payload={"access_token": "secret", "nested": {"password": "secret", "order": "safe"}},
    )
    assert set(row) == StructuredEventLogger.REQUIRED | {"payload"}
    assert row["event_type"] == "ENTRY_SUBMITTED" and row["latency_ms"] == 1.235
    serialized = (tmp_path / "events.jsonl").read_text()
    assert "secret" not in serialized and "safe" in serialized


def test_exception_and_warning_tracking(tmp_path):
    log = logger(tmp_path)
    log.log("QUOTE_STALE", status="WARNING")
    log.exception(ValueError("bad quote"), correlation_id="quote:1")
    assert log.counters() == {"exceptions": 1, "warnings": 1}


def test_monitor_exposes_every_required_health_state(tmp_path):
    monitor = ProductionHealthMonitor(healthy_providers(), logger=logger(tmp_path), clock=lambda: NOW)
    result = monitor.snapshot()
    expected = {
        "scheduler", "broker", "websocket", "quotes", "strategy_runtime", "paper_engine",
        "runtime_latency", "memory", "cpu", "processing_queue", "exceptions",
    }
    assert set(result["components"]) == expected
    assert result["monitoring_active"] is True and result["polling_loop_created"] is False
    assert result["status"] == HealthState.HEALTHY.value


def test_monitor_tracks_provider_exception_and_fails_closed(tmp_path):
    providers = healthy_providers()
    providers["scheduler"] = lambda: (_ for _ in ()).throw(RuntimeError("scheduler dead"))
    monitor = ProductionHealthMonitor(providers, logger=logger(tmp_path), clock=lambda: NOW)
    result = monitor.snapshot()
    assert result["status"] == "FAILED"
    assert "scheduler" in result["critical_failures"]
    assert result["components"]["scheduler"]["status"] == "RuntimeError"


def test_monitor_marks_stale_quote_and_queue_pressure_unhealthy(tmp_path):
    providers = healthy_providers()
    providers["quotes"] = lambda: {"status": "STALE"}
    providers["processing_queue"] = lambda: {"status": "HEALTHY", "depth": 1001}
    result = ProductionHealthMonitor(providers, logger=logger(tmp_path), clock=lambda: NOW, queue_limit=1000).snapshot()
    assert result["components"]["quotes"]["state"] == "UNAVAILABLE"
    assert result["components"]["processing_queue"]["state"] == "DEGRADED"


def test_backend_monitor_heartbeat_activates_automatic_kill_switch(tmp_path):
    providers = healthy_providers()
    providers["quotes"] = lambda: {"status": "STALE"}
    monitor = ProductionHealthMonitor(providers, logger=logger(tmp_path), clock=lambda: NOW)
    store = initialized_store(tmp_path)
    switch = InstitutionalKillSwitch(store, stop_strategies=lambda: None, cancel_pending_orders=lambda: None, logger=logger(tmp_path), monitoring_active=lambda: True)
    result = OperationalMonitorLoop(monitor, switch).run_once()
    assert result["snapshot"]["heartbeat"] == NOW.isoformat()
    assert result["kill_switch_activation"]["reason"] == "QUOTE_STALE"
    assert store.projection().state == "ACTIVE"


def test_manual_kill_switch_stops_cancels_blocks_entries_and_keeps_monitoring(tmp_path):
    calls = []
    switch = InstitutionalKillSwitch(
        initialized_store(tmp_path),
        stop_strategies=lambda: calls.append("stop"),
        cancel_pending_orders=lambda: calls.append("cancel"),
        logger=logger(tmp_path),
        monitoring_active=lambda: True,
    )
    result = switch.activate_manual(reason="OPERATOR_EMERGENCY", actor="operator", correlation_id="kill-1")
    assert calls == ["stop", "cancel"]
    assert result["state"] == "ACTIVE" and result["new_entries_blocked"] is True
    assert result["monitoring_active"] is True


@pytest.mark.parametrize(
    "component,reason",
    [
        ("broker", "BROKER_DISCONNECTED"),
        ("quotes", "QUOTE_STALE"),
        ("scheduler", "SCHEDULER_FAILURE"),
        ("strategy_runtime", "CRITICAL_RUNTIME_FAILURE"),
        ("exceptions", "UNEXPECTED_EXCEPTION"),
    ],
)
def test_automatic_kill_switch_maps_critical_health(component, reason, tmp_path):
    switch = InstitutionalKillSwitch(
        initialized_store(tmp_path),
        stop_strategies=lambda: None,
        cancel_pending_orders=lambda: None,
        logger=logger(tmp_path),
        monitoring_active=lambda: True,
    )
    result = switch.evaluate_health({"critical_failures": [component], "generated_at": NOW.isoformat()})
    assert result["reason"] == reason and result["automatic"] is True


def test_kill_switch_activation_is_idempotent(tmp_path):
    calls = []
    switch = InstitutionalKillSwitch(
        initialized_store(tmp_path),
        stop_strategies=lambda: calls.append("stop"),
        cancel_pending_orders=lambda: calls.append("cancel"),
        logger=logger(tmp_path),
        monitoring_active=lambda: True,
    )
    switch.activate_automatic("DUPLICATE_EXECUTION", correlation_id="duplicate")
    result = switch.activate_automatic("DUPLICATE_EXECUTION", correlation_id="duplicate")
    assert result["idempotent"] is True and calls == ["stop", "cancel"]


def test_kill_switch_still_persists_when_cancellation_fails(tmp_path):
    def fail():
        raise RuntimeError("broker unavailable")

    store = initialized_store(tmp_path)
    switch = InstitutionalKillSwitch(store, stop_strategies=lambda: None, cancel_pending_orders=fail, logger=logger(tmp_path), monitoring_active=lambda: True)
    result = switch.activate_automatic("BROKER_DISCONNECTED", correlation_id="broker")
    assert store.projection().state == "ACTIVE"
    assert result["pending_orders_cancelled"] is False and result["new_entries_blocked"] is True


def recovery_state():
    return {
        "open_positions": [],
        "pending_exits": [],
        "replay": [],
        "journal": [],
        "scheduler_state": {"state": "STOPPED"},
        "processed_candles": ["candle-1"],
        "exactly_once_state": {"orders": {}},
    }


def test_restart_recovery_restores_all_required_state_after_reconciliation(tmp_path):
    recovery = OperationalRecovery(tmp_path / "recovery.json", logger(tmp_path))
    recovery.checkpoint(recovery_state())
    result = recovery.recover(reconcile=lambda _: {"status": "MATCHED"})
    assert result["status"] == "RECOVERED" and result["trading_allowed"] is True
    assert result["scheduler_resume_required"] is True
    assert result["state"]["processed_candles"] == ["candle-1"]


def test_restart_recovery_blocks_on_position_mismatch(tmp_path):
    recovery = OperationalRecovery(tmp_path / "recovery.json", logger(tmp_path))
    recovery.checkpoint(recovery_state())
    result = recovery.recover(reconcile=lambda _: {"status": "MISMATCH"})
    assert result["status"] == "BLOCKED" and result["trading_allowed"] is False


def test_runtime_dashboard_contains_required_operational_fields(tmp_path):
    monitor = ProductionHealthMonitor(healthy_providers(), logger=logger(tmp_path), clock=lambda: NOW)
    switch = InstitutionalKillSwitch(initialized_store(tmp_path), stop_strategies=lambda: None, cancel_pending_orders=lambda: None, logger=logger(tmp_path), monitoring_active=lambda: True)
    service = ProductionOperationsService(
        monitor=monitor,
        kill_switch=switch,
        strategy_provider=lambda: {"strategies": [{
            "metadata": {"name": "PULLBACK MASTER", "supported_timeframes": ["3m"]},
            "current_position": {"id": "position"}, "current_decision": {"signal": "WAITING"},
            "scheduler": {"last_tick_at": NOW.isoformat()}, "latency_ms": 4,
        }]},
        risk_provider=lambda: {"state_health": "HEALTHY", "kill_switch_state": "INACTIVE"},
        recovery_provider=lambda: {"status": "READY"},
    )
    result = service.dashboard()
    required = {
        "runtime_mode", "broker_status", "scheduler_status", "quote_status", "open_positions",
        "pending_signals", "current_strategy", "current_timeframe", "current_candle", "heartbeat",
        "latency_ms", "risk_status", "kill_switch_state", "recovery_status",
    }
    assert required.issubset(result)
    assert result["live_trading_enabled"] is False and result["open_positions"] == 1
    assert result["pending_signals"] == 0


@pytest.mark.parametrize("reason", ["POSITION_MISMATCH", "DUPLICATE_EXECUTION"])
def test_operational_event_sink_activates_kill_switch(reason, tmp_path):
    monitor = ProductionHealthMonitor(healthy_providers(), logger=logger(tmp_path), clock=lambda: NOW)
    store = initialized_store(tmp_path)
    switch = InstitutionalKillSwitch(store, stop_strategies=lambda: None, cancel_pending_orders=lambda: None, logger=logger(tmp_path), monitoring_active=lambda: True)
    service = ProductionOperationsService(
        monitor=monitor, kill_switch=switch,
        strategy_provider=lambda: {"strategies": []},
        risk_provider=lambda: {}, recovery_provider=lambda: {},
    )
    assert service.critical_event(reason, correlation_id="critical")["state"] == "ACTIVE"


def test_production_certification_runs_every_required_scenario():
    validators = {name: (lambda: True) for name in ProductionCertification.SCENARIOS}
    result = ProductionCertification(validators, clock=lambda: NOW).run()
    assert result["status"] == "CERTIFIED"
    assert result["passed"] == result["total"] == 17
    assert result["live_trading_enabled"] is False


def test_production_certification_fails_closed_when_validator_missing():
    result = ProductionCertification({}, clock=lambda: NOW).run()
    assert result["status"] == "BLOCKED" and result["passed"] == 0


def test_operations_dashboard_is_get_only_and_in_v2_aggregation():
    routes = {(route.path, frozenset(route.methods or ())) for route in app.routes}
    assert ("/v1/strategy-lab/operations", frozenset({"GET"})) in routes
    assert not any(path == "/v1/strategy-lab/operations" and methods & {"POST", "PUT", "PATCH", "DELETE"} for path, methods in routes)
    assert "operations" in __import__("app.main", fromlist=["v2_integration"]).v2_integration.providers


def test_live_mode_remains_disabled_in_operational_endpoint():
    assert strategy_lab_operations()["live_trading_enabled"] is False
