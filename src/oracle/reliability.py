"""Operational state, provenance, and readiness contracts for Oracle.

This module is deliberately independent of trading engines.  It only records
what the runtime is doing and evaluates whether its authoritative inputs are
available.  It must never participate in a trading decision or provider call.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, time, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


class StartupState(str, Enum):
    STARTING = "STARTING"
    RECOVERING = "RECOVERING"
    CONNECTING_MARKET_DATA = "CONNECTING_MARKET_DATA"
    WARMING = "WARMING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


def _fingerprint(value: object, *, length: int = 12) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _git_value(root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            stderr=subprocess.DEVNULL,
            text=True,
            # Provenance is sampled once at boot, not in a hot request path.
            # A dirty worktree with many artifacts can legitimately take more
            # than one second to enumerate; reporting it as clean is worse
            # than spending a bounded few seconds during startup.
            timeout=5.0,
        ).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _frontend_build_id(root: Path) -> str | None:
    configured = os.getenv("CITADEL_FRONTEND_BUILD_ID")
    if configured:
        return configured.strip() or None
    path = root / "citadel-dashboard" / ".next" / "BUILD_ID"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _code_fingerprint(root: Path) -> str:
    """Stable compatibility identity for the recovery-relevant source slice."""
    digest = hashlib.sha256()
    for relative in (
        "app/main.py",
        "src/order_flow/contracts.py",
        "src/order_flow/features.py",
        "src/order_flow/flow_pulse.py",
        "src/order_flow/reconciler.py",
        "src/order_flow/service.py",
    ):
        path = root / relative
        digest.update(relative.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<MISSING>")
    return digest.hexdigest()[:16]


def is_nse_market_open(now: datetime | None = None) -> bool:
    value = (now or datetime.now(timezone.utc)).astimezone(IST)
    return value.weekday() < 5 and time(9, 15) <= value.time() < time(15, 30)


class RuntimeProvenance:
    """Immutable-at-boot runtime identity with no secret plaintext."""

    def __init__(
        self,
        code_root: str | Path,
        *,
        state_root: str | Path | None = None,
        log_root: str | Path | None = None,
        journal_root: str | Path | None = None,
        config_source: str | Path | None = None,
    ) -> None:
        root = Path(code_root).resolve()
        self.code_root = root
        self.state_root = str(
            Path(state_root or os.getenv("CITADEL_STATE_ROOT") or root / "logs").resolve()
        )
        self.log_root = str(Path(log_root or self.state_root).resolve())
        self.journal_root = str(Path(journal_root or self.state_root).resolve())
        self.config_source = str(
            Path(
                config_source
                or os.getenv("CITADEL_ENV_SOURCE")
                or os.getenv("CITADEL_ENV_FILE")
                or root / ".env"
            ).resolve()
        )
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.git_head = _git_value(root, "rev-parse", "HEAD")
        self.git_branch = _git_value(root, "branch", "--show-current")
        self.git_dirty = bool(_git_value(root, "status", "--porcelain"))
        self.python_executable = sys.executable
        self.python_env_root = str(Path(sys.prefix).resolve())
        self.code_fingerprint = _code_fingerprint(root)
        self.frontend_build_id = _frontend_build_id(root)
        self.env_fingerprint = _fingerprint(
            json.dumps(
                {
                    "config_source": self.config_source,
                    "state_root": self.state_root,
                    "paper_only": os.getenv("CITADEL_PAPER_ONLY", "true"),
                    "live_trading_enabled": os.getenv("LIVE_TRADING_ENABLED", "false"),
                },
                sort_keys=True,
            )
        )
        self.dhan_client_fingerprint = _fingerprint(os.getenv("DHAN_CLIENT_ID"))
        self.dhan_token_fingerprint = _fingerprint(os.getenv("DHAN_ACCESS_TOKEN"))

    def snapshot(self) -> dict[str, Any]:
        return {
            "CODE_ROOT": str(self.code_root),
            "GIT_BRANCH": self.git_branch,
            "GIT_HEAD": self.git_head,
            "GIT_DIRTY": self.git_dirty,
            "CODE_FINGERPRINT": self.code_fingerprint,
            "PYTHON_EXECUTABLE": self.python_executable,
            "PYTHON_ENV_ROOT": self.python_env_root,
            "CONFIG_SOURCE": self.config_source,
            "ENV_FINGERPRINT": self.env_fingerprint,
            "DHAN_CLIENT_FINGERPRINT": self.dhan_client_fingerprint,
            "DHAN_TOKEN_FINGERPRINT": self.dhan_token_fingerprint,
            "STATE_ROOT": self.state_root,
            "LOG_ROOT": self.log_root,
            "JOURNAL_ROOT": self.journal_root,
            "FRONTEND_BUILD_ID": self.frontend_build_id,
            "BACKEND_START_TIME": self.started_at,
            "BACKEND_PID": os.getpid(),
        }


class StageTiming:
    """Small bounded timing ledger for source-to-publication observation."""

    STAGES = (
        "ARGUS_REQUEST_START",
        "ARGUS_SOURCE_RESPONSE",
        "ARGUS_NORMALIZE_END",
        "ARGUS_CALC_END",
        "ARGUS_CACHE_WRITE",
        "ARGUS_FAST_LANE_READ",
        "ARGUS_PUBLICATION",
        "ORDER_FLOW_PUBLICATION",
        "FLOW_PULSE_PUBLICATION",
        "OSE_PUBLICATION",
        "FAST_LANE_ASSEMBLY",
        "FAST_LANE_SERIALIZATION",
        "SSE_EMISSION",
    )

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: dict[str, dict[str, Any]] = {}

    def mark(
        self,
        stage: str,
        *,
        source_timestamp: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        if stage not in self.STAGES:
            return
        now = datetime.now(timezone.utc)
        with self._lock:
            row: dict[str, Any] = dict(self._rows.get(stage) or {})
        row["observed_at"] = now.isoformat()
        if source_timestamp is not None:
            row["source_timestamp"] = str(source_timestamp)
            source = _parse_timestamp(source_timestamp)
            if source is not None:
                row["source_age_at_stage_ms"] = round(
                    max(0.0, (now - source).total_seconds() * 1000.0), 3
                )
        if duration_ms is not None:
            row["duration_ms"] = round(max(0.0, float(duration_ms)), 3)
        with self._lock:
            self._rows[stage] = row

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            rows = {stage: dict(value) for stage, value in self._rows.items()}
        source_response = rows.get("ARGUS_SOURCE_RESPONSE", {})
        calc = rows.get("ARGUS_CALC_END", {})
        publication = rows.get("ARGUS_PUBLICATION", {})
        return {
            "stages": rows,
            "derived": {
                "fetch_ms": source_response.get("duration_ms"),
                "normalize_ms": rows.get("ARGUS_NORMALIZE_END", {}).get("duration_ms"),
                "calc_ms": calc.get("duration_ms"),
                "fanout_ms": rows.get("ARGUS_PUBLICATION", {}).get("duration_ms"),
                "source_age_at_calc_ms": calc.get("source_age_at_stage_ms"),
                "source_age_at_publish_ms": publication.get("source_age_at_stage_ms"),
            },
        }


class OracleRuntimeStatus:
    """Authoritative liveness and readiness state, separate from trading quality."""

    def __init__(self, provenance: RuntimeProvenance) -> None:
        self.provenance = provenance
        self.timing = StageTiming()
        self._lock = threading.RLock()
        self._state = StartupState.STARTING
        self._state_changed_at = datetime.now(timezone.utc).isoformat()
        self._reason: str | None = None
        self._recovery: dict[str, Any] = {"status": "NOT_STARTED"}
        self._noncritical_startup_warnings: list[dict[str, str]] = []

    def transition(self, state: StartupState | str, *, reason: str | None = None) -> None:
        value = state if isinstance(state, StartupState) else StartupState(str(state).upper())
        with self._lock:
            self._state = value
            self._state_changed_at = datetime.now(timezone.utc).isoformat()
            self._reason = reason

    def update_recovery(self, value: Mapping[str, Any] | None) -> None:
        with self._lock:
            self._recovery = dict(value or {"status": "NOT_RUN"})

    def note_noncritical_failure(self, component: str, error: Exception) -> None:
        """Keep optional warm-up failures observable without making core dead."""
        with self._lock:
            self._noncritical_startup_warnings.append(
                {
                    "component": component,
                    "error": f"{type(error).__name__}:{error}",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._noncritical_startup_warnings = self._noncritical_startup_warnings[-16:]

    def liveness(self) -> dict[str, Any]:
        """Cheap endpoint payload: no providers, locks outside this object, or I/O."""
        with self._lock:
            return {
                "process_alive": True,
                "backend_pid": os.getpid(),
                "startup_state": self._state.value,
                "state_changed_at": self._state_changed_at,
                "status": "LIVE",
            }

    def readiness(
        self,
        *,
        market_data: Mapping[str, Any],
        recorder: Mapping[str, Any],
        order_flow: Mapping[str, Any],
        argus: Mapping[str, Any] | None,
        ose: Mapping[str, Any] | None,
        fast_lane: Mapping[str, Any],
        sse_revision: int | None,
        live_analytics_worker: Mapping[str, Any] | None = None,
        persistence_degraded: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Evaluate a stable machine-readable core Oracle readiness contract."""
        at = now or datetime.now(timezone.utc)
        market_open = is_nse_market_open(at)
        with self._lock:
            startup_state = self._state.value
            recovery = dict(self._recovery)
            noncritical_warnings = list(self._noncritical_startup_warnings)
        blockers: list[str] = []
        warnings: list[str] = []

        if startup_state != StartupState.READY.value:
            blockers.append(f"STARTUP_{startup_state}")
        recovery_status = str(recovery.get("status") or "NOT_RUN").upper()
        recovery_complete = recovery_status in {"RESTORED", "COMPLETE", "NOT_REQUIRED", "UNAVAILABLE"}
        if not recovery_complete:
            blockers.append(f"RECOVERY_{recovery_status}")

        if live_analytics_worker is not None:
            if not bool(live_analytics_worker.get("alive")):
                blockers.append("LIVE_ANALYTICS_WORKER_DEAD")
            elif live_analytics_worker.get("state") == "CRASH_LOOP":
                blockers.append("LIVE_ANALYTICS_WORKER_CRASH_LOOP")
            elif live_analytics_worker.get("state") in ("STALE", "AGING"):
                warnings.append("LIVE_ANALYTICS_OUTPUT_STALE")

        if persistence_degraded:
            warnings.append("STORAGE_PERSISTENCE_DEGRADED")

        ws_connected = bool(market_data.get("WS_CONNECTED", market_data.get("status") == "UP"))
        if not ws_connected:
            blockers.append("DHAN_WS_DISCONNECTED")
        futures = _instrument_by_role(market_data, "NIFTY_FUTURE")
        futures_state = str((futures or {}).get("freshness_state") or "STALE")
        if market_open and futures_state not in {"FRESH", "LATE"}:
            blockers.append("DHAN_FUTURES_PACKET_STALE")
        basket = str(market_data.get("BASKET_HEALTH") or "UNCONFIGURED")
        if market_open and basket in {"UNCONFIGURED", "DATA_DEGRADED", "DISCONNECTED"}:
            blockers.append(f"DHAN_BASKET_{basket}")

        recorder_alive = bool(recorder.get("RECORDER_ALIVE", recorder.get("worker_alive")))
        if not recorder_alive:
            blockers.append("RECORDER_DEAD")
        order_flow_ready = str(order_flow.get("status") or "UNAVAILABLE").upper() not in {"UNAVAILABLE", "FAILED", "ERROR"}
        if not order_flow_ready:
            blockers.append("ORDER_FLOW_NOT_INITIALIZED")
        flow_worker = order_flow.get("flow_worker") if isinstance(order_flow.get("flow_worker"), Mapping) else None
        if flow_worker is not None:
            if not bool(flow_worker.get("FLOW_WORKER_ALIVE")):
                blockers.append("FLOW_WORKER_DEAD")
            if int(flow_worker.get("FLOW_REQUIRED_DROPS") or 0) > 0:
                blockers.append("FLOW_REQUIRED_PACKET_LOSS")
        flow_pulse_ready = bool(order_flow.get("flow_pulse"))
        if not flow_pulse_ready:
            blockers.append("FLOW_PULSE_NOT_INITIALIZED")
        argus_status = str((argus or {}).get("status") or "UNAVAILABLE").upper()
        if argus_status in {"UNAVAILABLE", "FAILED", "ERROR"}:
            blockers.append("ARGUS_NOT_INITIALIZED")
        ose_status = str((ose or {}).get("status") or "UNAVAILABLE").upper()
        if ose_status in {"UNAVAILABLE", "FAILED", "ERROR"}:
            blockers.append("OSE_NOT_INITIALIZED")
        fast_lane_ready = str(fast_lane.get("status") or "STARTING").upper() == "READY"
        if not fast_lane_ready:
            blockers.append("FAST_LANE_NOT_SERVING")
        core_feeds = fast_lane.get("core_feeds") if isinstance(fast_lane.get("core_feeds"), Mapping) else {}
        for feed_name in ("argus", "order_flow", "futures_chart"):
            feed = core_feeds.get(feed_name) if isinstance(core_feeds, Mapping) else None
            if isinstance(feed, Mapping) and not bool(feed.get("ok")):
                blockers.append(f"FAST_LANE_{feed_name.upper()}_UNAVAILABLE")
        if not isinstance(sse_revision, int) or sse_revision <= 0:
            blockers.append("SSE_NOT_PUBLISHED")

        full_ready = not blockers
        return {
            "process_alive": True,
            "startup_state": startup_state,
            "recovery_state": recovery,
            "market_session": "OPEN" if market_open else "CLOSED",
            "market_data_state": market_data.get("BASKET_HEALTH") or "UNCONFIGURED",
            "recorder_state": {
                "status": recorder.get("status"),
                "alive": recorder_alive,
            },
            "argus_state": argus_status,
            "order_flow_state": "READY" if order_flow_ready else "UNAVAILABLE",
            "flow_worker_state": dict(flow_worker or {}),
            "flow_pulse_state": "READY" if flow_pulse_ready else "UNAVAILABLE",
            "ose_state": ose_status,
            "subscription_state": {
                "expected": market_data.get("EXPECTED_INSTRUMENTS", 0),
                "requested": market_data.get("REQUESTED_INSTRUMENTS", 0),
                "fresh": market_data.get("FRESH_INSTRUMENTS", 0),
            },
            "fast_lane_state": fast_lane.get("status"),
            "sse_revision": sse_revision,
            "full_oracle_ready": full_ready,
            "blockers": blockers,
            "warnings": warnings,
            "provenance": self.provenance.snapshot(),
            "timing": self.timing.snapshot(),
            "noncritical_startup_warnings": noncritical_warnings,
        }


def _parse_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _instrument_by_role(value: Mapping[str, Any], role: str) -> Mapping[str, Any] | None:
    for row in value.get("instruments") or []:
        if isinstance(row, Mapping) and str(row.get("role")) == role:
            return row
    return None
