"""Operational reliability layer; contains no strategy or trading calculations."""

from __future__ import annotations

import json
import os
import resource
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Event, RLock, Thread
from time import perf_counter, process_time
from typing import Any, Callable, Iterable, Mapping, Optional

from src.broker.live_foundation import AtomicJsonStore
from src.risk.authorization import RiskControlStore


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class ComponentHealth:
    component: str
    state: str
    status: str
    checked_at: str
    latency_ms: float
    heartbeat: Optional[str]
    details: Mapping[str, Any]
    critical: bool


class StructuredEventLogger:
    """Append-only JSONL logger with a mandatory production event envelope."""

    REQUIRED = {
        "timestamp", "strategy", "runtime_mode", "correlation_id", "symbol",
        "timeframe", "event_type", "latency_ms", "status",
    }
    SECRET_KEYS = {
        "access_token", "accessToken", "api_secret", "api_key", "password",
        "pin", "totp", "authorization", "cookie",
    }

    def __init__(self, path: Path | str = "logs/operations/events.jsonl", clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._exceptions = 0
        self._warnings = 0

    def log(
        self,
        event_type: str,
        *,
        strategy: str = "SYSTEM",
        runtime_mode: str = "PAPER",
        correlation_id: str = "SYSTEM",
        symbol: str = "SYSTEM",
        timeframe: str = "N/A",
        latency_ms: Optional[float] = None,
        status: str = "INFO",
        payload: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        timestamp = self.clock()
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ValueError("structured logger requires a timezone-aware clock")
        row = {
            "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
            "strategy": str(strategy or "UNKNOWN"),
            "runtime_mode": str(runtime_mode or "UNKNOWN").upper(),
            "correlation_id": str(correlation_id or "MISSING"),
            "symbol": str(symbol or "UNKNOWN").upper(),
            "timeframe": str(timeframe or "UNKNOWN"),
            "event_type": str(event_type or "UNKNOWN").upper(),
            "latency_ms": round(float(latency_ms), 3) if latency_ms is not None else None,
            "status": str(status or "UNKNOWN").upper(),
            "payload": self._sanitize(dict(payload or {})),
        }
        if set(row).difference({"payload"}) != self.REQUIRED:
            raise RuntimeError("structured event envelope is incomplete")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if row["status"] in {"ERROR", "CRITICAL", "FAILED"}:
                self._exceptions += 1
            elif row["status"] in {"WARNING", "WARN", "DEGRADED"}:
                self._warnings += 1
        return row

    def exception(self, error: Exception, **context: Any) -> Mapping[str, Any]:
        payload = dict(context.pop("payload", {}) or {})
        payload.update({"error_type": type(error).__name__, "message": str(error)[:240]})
        return self.log("ERROR", status="ERROR", payload=payload, **context)

    def counters(self) -> Mapping[str, int]:
        return {"exceptions": self._exceptions, "warnings": self._warnings}

    def record_failure(self) -> None:
        with self._lock:
            self._exceptions += 1

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): cls._sanitize(item) for key, item in value.items() if str(key) not in cls.SECRET_KEYS}
        if isinstance(value, (list, tuple)):
            return [cls._sanitize(item) for item in value]
        if isinstance(value, str):
            return value.replace("\n", " ").replace("\r", " ")[:2000]
        return value


class ProductionHealthMonitor:
    """Pull-based monitor reused by the V2 projection; it creates no polling loop."""

    CRITICAL_COMPONENTS = {
        "scheduler", "broker", "websocket", "quotes", "strategy_runtime",
        "paper_engine", "processing_queue", "exceptions",
    }

    def __init__(
        self,
        providers: Mapping[str, Callable[[], Mapping[str, Any]]],
        *,
        logger: StructuredEventLogger,
        clock=None,
        cpu_limit_percent: float = 90.0,
        memory_limit_mb: float = 2048.0,
        latency_limit_ms: float = 1000.0,
        queue_limit: int = 1000,
    ):
        self.providers = dict(providers)
        self.logger = logger
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cpu_limit_percent = float(cpu_limit_percent)
        self.memory_limit_mb = float(memory_limit_mb)
        self.latency_limit_ms = float(latency_limit_ms)
        self.queue_limit = int(queue_limit)
        self._last_process_time = process_time()
        self._last_wall_time = perf_counter()
        self._resource_sampled = False
        self._last_snapshot: Optional[Mapping[str, Any]] = None
        self._lock = RLock()

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            checked = self.clock().astimezone(timezone.utc).isoformat()
            components = []
            for name in (
                "scheduler", "broker", "websocket", "quotes", "strategy_runtime",
                "paper_engine", "runtime_latency", "processing_queue", "exceptions",
            ):
                components.append(self._check(name, self.providers.get(name), checked))
            resources = self._resources(checked)
            components.extend(resources)
            unhealthy = [item for item in components if item.critical and item.state in {HealthState.UNAVAILABLE.value, HealthState.FAILED.value}]
            degraded = [item for item in components if item.state == HealthState.DEGRADED.value]
            overall = HealthState.FAILED.value if unhealthy else HealthState.DEGRADED.value if degraded else HealthState.HEALTHY.value
            snapshot = {
                "status": overall,
                "health": overall,
                "generated_at": checked,
                "heartbeat": checked,
                "components": {item.component: asdict(item) for item in components},
                "critical_failures": [item.component for item in unhealthy],
                "degraded_components": [item.component for item in degraded],
                "monitoring_active": True,
                "polling_loop_created": False,
                "schema_version": 1,
            }
            self._last_snapshot = snapshot
            return snapshot

    def last_snapshot(self) -> Optional[Mapping[str, Any]]:
        return self._last_snapshot

    def _check(self, name: str, provider: Optional[Callable[[], Mapping[str, Any]]], checked: str) -> ComponentHealth:
        if provider is None:
            return ComponentHealth(name, HealthState.UNAVAILABLE.value, "PROVIDER_NOT_CONFIGURED", checked, 0.0, None, {}, name in self.CRITICAL_COMPONENTS)
        started = perf_counter()
        try:
            value = provider()
            if not isinstance(value, Mapping):
                raise TypeError("health provider did not return a mapping")
            latency = round((perf_counter() - started) * 1000, 3)
            state = self._state(value, name, latency)
            heartbeat = _timestamp(value)
            return ComponentHealth(name, state, str(value.get("status") or value.get("state") or state), checked, latency, heartbeat, _safe_details(value), name in self.CRITICAL_COMPONENTS)
        except Exception as error:
            latency = round((perf_counter() - started) * 1000, 3)
            self.logger.exception(error, correlation_id=f"health:{name}", payload={"component": name}, latency_ms=latency)
            return ComponentHealth(name, HealthState.FAILED.value, type(error).__name__, checked, latency, None, {}, name in self.CRITICAL_COMPONENTS)

    def _state(self, value: Mapping[str, Any], name: str, latency: float) -> str:
        raw = str(value.get("health") or value.get("state_health") or value.get("status") or value.get("state") or "UNKNOWN").upper()
        if raw in {"DISABLED", "DISABLED_SAFE", "LIVE_DISABLED"}:
            return HealthState.DISABLED.value
        if any(token in raw for token in ("FAILED", "ERROR", "CORRUPT")):
            return HealthState.FAILED.value
        if any(token in raw for token in ("UNAVAILABLE", "UNKNOWN", "DISCONNECTED", "STALE")):
            return HealthState.UNAVAILABLE.value
        if any(token in raw for token in ("DEGRADED", "LIMITED", "RECONNECTING", "PARTIAL")):
            return HealthState.DEGRADED.value
        if name == "runtime_latency" and float(value.get("latency_ms") or latency) > self.latency_limit_ms:
            return HealthState.DEGRADED.value
        if name == "processing_queue" and int(value.get("depth") or 0) > self.queue_limit:
            return HealthState.DEGRADED.value
        return HealthState.HEALTHY.value

    def _resources(self, checked: str) -> list[ComponentHealth]:
        now_wall, now_process = perf_counter(), process_time()
        wall_delta = max(0.000001, now_wall - self._last_wall_time)
        cpu_percent = max(0.0, (now_process - self._last_process_time) / wall_delta * 100.0) if self._resource_sampled else 0.0
        self._last_wall_time, self._last_process_time = now_wall, now_process
        self._resource_sampled = True
        maximum_rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        memory_mb = maximum_rss / (1024 * 1024) if os.uname().sysname == "Darwin" else maximum_rss / 1024
        cpu_state = HealthState.DEGRADED.value if cpu_percent > self.cpu_limit_percent else HealthState.HEALTHY.value
        memory_state = HealthState.DEGRADED.value if memory_mb > self.memory_limit_mb else HealthState.HEALTHY.value
        return [
            ComponentHealth("cpu", cpu_state, "PROCESS_CPU", checked, 0.0, checked, {"percent": round(cpu_percent, 3), "limit_percent": self.cpu_limit_percent}, False),
            ComponentHealth("memory", memory_state, "PROCESS_MAX_RSS", checked, 0.0, checked, {"megabytes": round(memory_mb, 3), "limit_megabytes": self.memory_limit_mb}, False),
        ]


class InstitutionalKillSwitch:
    """Coordinates persisted manual/automatic emergency stops without stopping monitoring."""

    AUTOMATIC_REASONS = {
        "BROKER_DISCONNECTED", "QUOTE_STALE", "SCHEDULER_FAILURE", "POSITION_MISMATCH",
        "DUPLICATE_EXECUTION", "UNEXPECTED_EXCEPTION", "CRITICAL_RUNTIME_FAILURE",
    }

    def __init__(
        self,
        store: RiskControlStore,
        *,
        stop_strategies: Callable[[], Any],
        cancel_pending_orders: Callable[[], Any],
        logger: StructuredEventLogger,
        monitoring_active: Callable[[], bool],
    ):
        self.store = store
        self.stop_strategies = stop_strategies
        self.cancel_pending_orders = cancel_pending_orders
        self.logger = logger
        self.monitoring_active = monitoring_active
        self._lock = RLock()

    def activate_manual(self, *, reason: str, actor: str, correlation_id: str) -> Mapping[str, Any]:
        return self._activate(reason=reason, actor=actor, correlation_id=correlation_id, automatic=False)

    def activate_automatic(self, reason: str, *, correlation_id: str) -> Mapping[str, Any]:
        reason = str(reason).upper()
        if reason not in self.AUTOMATIC_REASONS:
            raise ValueError("unsupported automatic kill-switch reason")
        return self._activate(reason=reason, actor="automatic-safety", correlation_id=correlation_id, automatic=True)

    def evaluate_health(self, snapshot: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        mapping = {
            "broker": "BROKER_DISCONNECTED",
            "websocket": "BROKER_DISCONNECTED",
            "quotes": "QUOTE_STALE",
            "scheduler": "SCHEDULER_FAILURE",
            "strategy_runtime": "CRITICAL_RUNTIME_FAILURE",
            "exceptions": "UNEXPECTED_EXCEPTION",
        }
        failures = list(snapshot.get("critical_failures") or [])
        reason = next((mapping[name] for name in failures if name in mapping), None)
        return self.activate_automatic(reason, correlation_id=f"health:{snapshot.get('generated_at')}") if reason else None

    def _activate(self, *, reason: str, actor: str, correlation_id: str, automatic: bool) -> Mapping[str, Any]:
        if not str(reason).strip() or not str(actor).strip() or not str(correlation_id).strip():
            raise ValueError("kill-switch reason, actor, and correlation ID are required")
        with self._lock:
            current = self.store.projection()
            if current.state == "ACTIVE":
                return {**current.to_dict(), "idempotent": True, "monitoring_active": self.monitoring_active()}
            stop_error = cancel_error = None
            try:
                self.stop_strategies()
            except Exception as error:
                stop_error = type(error).__name__
            try:
                self.cancel_pending_orders()
            except Exception as error:
                cancel_error = type(error).__name__
            state = self.store.activate(str(reason), str(actor))
            self.logger.log(
                "KILL_SWITCH", correlation_id=correlation_id, status="CRITICAL",
                payload={"reason": reason, "automatic": automatic, "stop_error": stop_error, "cancel_error": cancel_error},
            )
            return {
                "state": "ACTIVE" if state.active else "INACTIVE",
                "reason": state.reason,
                "activated_at": state.timestamp,
                "actor": state.actor,
                "automatic": automatic,
                "strategies_stopped": stop_error is None,
                "pending_orders_cancelled": cancel_error is None,
                "new_entries_blocked": True,
                "monitoring_active": self.monitoring_active(),
                "idempotent": False,
            }


class OperationalMonitorLoop:
    """Single backend heartbeat loop; frontend polling remains unchanged."""

    def __init__(self, monitor: ProductionHealthMonitor, kill_switch: InstitutionalKillSwitch, *, interval_seconds: float = 5.0):
        self.monitor = monitor
        self.kill_switch = kill_switch
        self.interval_seconds = max(1.0, float(interval_seconds))
        self._stop = Event()
        self._thread: Optional[Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="citadel-production-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_seconds + 1.0)

    def run_once(self) -> Mapping[str, Any]:
        snapshot = self.monitor.snapshot()
        activation = self.kill_switch.evaluate_health(snapshot)
        return {"snapshot": snapshot, "kill_switch_activation": activation}

    def status(self) -> Mapping[str, Any]:
        return {
            "status": "RUNNING" if self._thread and self._thread.is_alive() else "STOPPED",
            "heartbeat": (self.monitor.last_snapshot() or {}).get("heartbeat"),
            "interval_seconds": self.interval_seconds,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.interval_seconds)


class OperationalRecovery:
    """Atomic operational checkpoint and fail-closed restart validation."""

    REQUIRED = {
        "open_positions", "pending_exits", "replay", "journal", "scheduler_state",
        "processed_candles", "exactly_once_state",
    }

    def __init__(self, path: Path | str = "logs/operations/recovery.json", logger: Optional[StructuredEventLogger] = None):
        self.store = AtomicJsonStore(Path(path))
        self.logger = logger or StructuredEventLogger()

    def checkpoint(self, state: Mapping[str, Any], *, correlation_id: str = "checkpoint") -> None:
        missing = self.REQUIRED.difference(state)
        if missing:
            raise ValueError("operational recovery state missing: " + ",".join(sorted(missing)))
        document = {"schema_version": 1, "checkpointed_at": datetime.now(timezone.utc).isoformat(), **dict(state)}
        self.store.write(document)
        self.logger.log("RECOVERY_CHECKPOINT", correlation_id=correlation_id, payload={"state_keys": sorted(self.REQUIRED)})

    def recover(self, *, reconcile: Callable[[Mapping[str, Any]], Mapping[str, Any]], correlation_id: str = "restart") -> Mapping[str, Any]:
        state = self.store.read({})
        if state.get("schema_version") != 1 or self.REQUIRED.difference(state):
            raise RuntimeError("operational recovery state unavailable")
        reconciliation = reconcile(state)
        allowed = reconciliation.get("status") == "MATCHED"
        result = {
            "status": "RECOVERED" if allowed else "BLOCKED",
            "trading_allowed": allowed,
            "scheduler_resume_required": True,
            "state": state,
            "reconciliation": dict(reconciliation),
        }
        self.logger.log("RECOVERY", correlation_id=correlation_id, status="INFO" if allowed else "CRITICAL", payload={"status": result["status"]})
        return result


class ProductionCertification:
    SCENARIOS = (
        "market_open", "market_close", "weekend", "holiday", "restart", "reconnect",
        "duplicate_events", "stale_quotes", "network_interruption", "expiry_rollover",
        "order_rejection", "partial_fills", "paper_mode", "live_mode_disabled",
        "position_reconciliation", "kill_switch", "dashboard_synchronization",
    )

    def __init__(self, validators: Mapping[str, Callable[[], Any]], clock=None):
        self.validators = dict(validators)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self) -> Mapping[str, Any]:
        results = []
        for name in self.SCENARIOS:
            validator = self.validators.get(name)
            if validator is None:
                results.append({"scenario": name, "status": "NOT_VALIDATED", "detail": "VALIDATOR_MISSING"})
                continue
            try:
                value = validator()
                passed = value is True or isinstance(value, Mapping) and value.get("passed") is True
                results.append({"scenario": name, "status": "PASSED" if passed else "FAILED", "detail": value if isinstance(value, Mapping) else None})
            except Exception as error:
                results.append({"scenario": name, "status": "FAILED", "detail": {"error_type": type(error).__name__}})
        passed = sum(item["status"] == "PASSED" for item in results)
        return {
            "status": "CERTIFIED" if passed == len(self.SCENARIOS) else "BLOCKED",
            "generated_at": self.clock().astimezone(timezone.utc).isoformat(),
            "passed": passed,
            "total": len(self.SCENARIOS),
            "results": results,
            "live_trading_enabled": False,
        }


class ProductionOperationsService:
    """Read-only health/dashboard projection plus internal kill-switch workflow."""

    def __init__(
        self,
        *,
        monitor: ProductionHealthMonitor,
        kill_switch: InstitutionalKillSwitch,
        strategy_provider: Callable[[], Mapping[str, Any]],
        risk_provider: Callable[[], Mapping[str, Any]],
        recovery_provider: Callable[[], Mapping[str, Any]],
        runtime_mode: str = "PAPER",
    ):
        self.monitor = monitor
        self.kill_switch = kill_switch
        self.strategy_provider = strategy_provider
        self.risk_provider = risk_provider
        self.recovery_provider = recovery_provider
        self.runtime_mode = str(runtime_mode).upper()

    def dashboard(self) -> Mapping[str, Any]:
        health = self.monitor.snapshot()
        strategies = self.strategy_provider()
        risk = self.risk_provider()
        recovery = self.recovery_provider()
        rows = list(strategies.get("strategies") or [])
        open_positions = sum(row.get("current_position") is not None for row in rows)
        pending_signals = sum(
            decision.get("pending_signal") is True or str(decision.get("status") or "").upper() in {"PENDING", "SIGNAL_PENDING"}
            for row in rows
            for decision in [row.get("current_decision")]
            if isinstance(decision, Mapping)
        )
        schedulers = [dict(row.get("scheduler") or {}) for row in rows]
        latest_candle = next((item.get("last_tick_at") for item in schedulers if item.get("last_tick_at")), None)
        latency = max((float(row.get("latency_ms") or 0.0) for row in rows), default=0.0)
        components = health["components"]
        return {
            "status": health["status"],
            "health": health["health"],
            "generated_at": health["generated_at"],
            "runtime_mode": self.runtime_mode,
            "live_trading_enabled": False,
            "broker_status": components["broker"]["state"],
            "websocket_status": components["websocket"]["state"],
            "scheduler_status": components["scheduler"]["state"],
            "quote_status": components["quotes"]["state"],
            "open_positions": open_positions,
            "pending_signals": pending_signals,
            "current_strategy": rows[0].get("metadata", {}).get("name") if len(rows) == 1 else "MULTIPLE" if rows else None,
            "current_timeframe": rows[0].get("metadata", {}).get("supported_timeframes", [None])[0] if len(rows) == 1 else None,
            "current_candle": latest_candle,
            "heartbeat": health["heartbeat"],
            "latency_ms": latency,
            "risk_status": risk.get("state_health") or risk.get("status"),
            "kill_switch_state": risk.get("kill_switch_state") or "UNKNOWN",
            "recovery_status": recovery.get("status") or "NOT_STARTED",
            "monitoring": health,
            "strategies": rows,
            "schema_version": 1,
        }

    def critical_event(self, reason: str, *, correlation_id: str) -> Mapping[str, Any]:
        """Operational event sink for reconciliation and execution safeguards."""

        return self.kill_switch.activate_automatic(reason, correlation_id=correlation_id)


def _timestamp(value: Mapping[str, Any]) -> Optional[str]:
    for key in ("heartbeat", "updated_at", "last_updated", "generated_at", "last_tick_at", "timestamp"):
        if value.get(key):
            return str(value[key])
    return None


def _safe_details(value: Mapping[str, Any]) -> Mapping[str, Any]:
    blocked = {"access_token", "accessToken", "api_secret", "password", "pin", "totp"}
    return {str(key): item for key, item in value.items() if str(key) not in blocked}
