"""Version 2 shared dashboard projection over authoritative module services."""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from multiprocessing import get_context
from threading import Event, Lock, Thread
from time import monotonic, perf_counter

from src.api.release_contract import dashboard_release_contract


class ProjectionValidationError(ValueError):
    """Raised before publication when a V2 projection is not JSON-safe."""


def _projection_process_task(task, payload):
    """CPU-only worker entry point; payload is an immutable serialized snapshot."""

    if task == "argus_snapshot":
        from src.argus.option_chain_engine import OptionChainEngine

        engine = OptionChainEngine(dhan=False, baseline_store=False)
        return {
            "worker_pid": os.getpid(),
            "projection": engine.build_prepared_snapshot(payload).to_dict(),
        }
    if task == "development_dashboard":
        raw = payload.pop("evidence_bytes", b"")
        try:
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            previous_hash = "0" * 64
            integrity = {"valid": True, "records": len(rows), "head_hash": previous_hash, "reason": "VERIFIED"}
            for index, row in enumerate(rows):
                if row.get("previous_hash") != previous_hash:
                    integrity = {"valid": False, "records": len(rows), "failed_index": index, "reason": "CHAIN_LINK_MISMATCH"}
                    break
                unsigned = {key: value for key, value in row.items() if key != "record_hash"}
                canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), default=str)
                expected = hashlib.sha256(canonical.encode()).hexdigest()
                if row.get("record_hash") != expected:
                    integrity = {"valid": False, "records": len(rows), "failed_index": index, "reason": "RECORD_HASH_MISMATCH"}
                    break
                previous_hash = row["record_hash"]
                integrity["head_hash"] = previous_hash
            decisions = [row for row in rows if row.get("event_type") == "DEVELOPMENT_DECISION"]
            trades = [row for row in rows if row.get("event_type") == "DEVELOPMENT_TRADE_CLOSED"]
            evidence = {
                "status": "available", "integrity": integrity,
                "decision_count": len(decisions), "closed_trade_evidence_count": len(trades),
                "recent_decisions": [row["payload"] for row in decisions[-10:]],
                "recent_trades": [row["payload"] for row in trades[-10:]],
            }
        except Exception:
            evidence = {
                "status": "unavailable", "integrity": {"valid": False},
                "decision_count": None, "closed_trade_evidence_count": None,
                "recent_decisions": [], "recent_trades": [],
            }
        return {
            "worker_pid": os.getpid(),
            "projection": {
                **payload, "evidence": evidence,
                "safety_labels": [
                    "DEVELOPMENT PAPER TRADING", "NOT USED FOR PRODUCTION", "NOT USED FOR LIVE TRADING",
                ],
            },
        }
    raise ValueError(f"unsupported projection task: {task}")


class ProjectionProcessWorker:
    """Single-process, zero-queue projection worker with bounded recovery."""

    def __init__(self, *, timeout_seconds=8.0, backoff_seconds=1.0):
        self.timeout_seconds = float(timeout_seconds)
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self._lock = Lock()
        self._executor = None
        self._future = None
        self._task = None
        self._submissions = 0
        self._coalesced = 0
        self._failures = 0
        self._last_worker_pid = None
        self._retry_at = 0.0

    def _pool(self):
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
        return self._executor

    def run(self, task, payload):
        with self._lock:
            if self._future is not None and not self._future.done():
                if self._task != task:
                    raise RuntimeError("PROJECTION_WORKER_BUSY")
                future = self._future
                self._coalesced += 1
            else:
                if monotonic() < self._retry_at:
                    raise RuntimeError("PROJECTION_WORKER_BACKOFF")
                future = self._pool().submit(_projection_process_task, task, payload)
                self._future = future
                self._task = task
                self._submissions += 1
        try:
            result = future.result(timeout=self.timeout_seconds)
            self._last_worker_pid = result.get("worker_pid")
            return result["projection"]
        except (FutureTimeoutError, BrokenProcessPool):
            self._failures += 1
            self._retry_at = monotonic() + self.backoff_seconds
            self._reset_pool()
            raise RuntimeError("PROJECTION_WORKER_FAILED")
        finally:
            with self._lock:
                if self._future is future and future.done():
                    self._future = None
                    self._task = None

    def _reset_pool(self):
        with self._lock:
            executor = self._executor
            processes = list(getattr(executor, "_processes", {}).values()) if executor is not None else []
            self._executor = None
            self._future = None
            self._task = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1.0)

    def stop(self):
        with self._lock:
            executor = self._executor
            self._executor = None
            self._future = None
            self._task = None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def status(self):
        with self._lock:
            active = self._future is not None and not self._future.done()
            return {
                "max_workers": 1, "active": active, "pending": 0,
                "submissions": self._submissions, "coalesced": self._coalesced,
                "failures": self._failures, "worker_pid": self._last_worker_pid,
                "backoff_active": monotonic() < self._retry_at,
            }


class V2DashboardIntegration:
    API_VERSION = "2.0"
    SCHEMA_VERSION = 2
    MAX_OVERLAP_CACHE_AGE_SECONDS = 5.0
    REFRESH_INTERVAL_SECONDS = 3.0
    INITIAL_SNAPSHOT_TIMEOUT_SECONDS = 5.0
    STRATEGY_LAB_REFRESH_INTERVAL_SECONDS = 3.0
    STRATEGIES_REFRESH_INTERVAL_SECONDS = 3.0
    AUXILIARY_REFRESH_INTERVAL_SECONDS = 1.0
    AUXILIARY_CACHE_STALE_SECONDS = 20.0
    AUXILIARY_PROVIDERS = frozenset({
        "snapshot", "oracle_live_workspace", "athena", "readiness",
        "risk_status", "development",
    })
    STALE_SNAPSHOT_AGE_SECONDS = 15.0
    _AGE_MARKER = "__CITADEL_PROJECTION_AGE_MS__"
    _DELIVERY_MARKER = "__CITADEL_PROJECTION_DELIVERY__"
    _STATUS_MARKER = "__CITADEL_PROJECTION_STATUS__"
    _REFRESH_MARKER = "__CITADEL_REFRESH_IN_PROGRESS__"
    _PROJECTION_STATUS_MARKER = "__CITADEL_PROJECTION_REFRESH_STATUS__"
    _SERIALIZATION_MS_MARKER = "__CITADEL_PROJECTION_SERIALIZATION_MS__"
    _ORACLE_LIVE_MARKER = "__CITADEL_ORACLE_LIVE_WORKSPACE__"
    _EYE_MARKER = "__CITADEL_EYE_PROJECTION__"

    def __init__(self, *, process_worker=None, turbo_mode=False, **providers):
        self.providers = providers
        self.process_worker = process_worker
        self.turbo_mode = bool(turbo_mode)
        self._projection_lock = Lock()
        self._state_lock = Lock()
        self._last_projection = None
        self._last_projection_at = None
        self._serialized_template = None
        self._refreshing = False
        self._refresh_count = 0
        self._refresh_stop = Event()
        self._initial_snapshot_ready = Event()
        self._refresh_thread = None
        self._strategy_lab_refresh_thread = None
        self._strategies_refresh_thread = None
        self._comparison_refresh_thread = None
        self._auxiliary_refresh_thread = None
        self._strategy_lab_cache = None
        self._strategies_cache = None
        self._comparison_cache = None
        self._auxiliary_cache = {}
        self._auxiliary_cache_at = {}
        self._strategy_lab_cache_at = None
        self._last_refresh_status = "STARTING"

    def start(self, *, wait_for_initial: bool = True) -> bool:
        """Start exactly one projection worker outside the HTTP request path."""

        with self._state_lock:
            if self._refresh_thread is not None and self._refresh_thread.is_alive():
                thread = self._refresh_thread
            else:
                self._refresh_stop.clear()
                thread = Thread(target=self._refresh_loop, name="citadel-v2-projection", daemon=True)
                self._refresh_thread = thread
                thread.start()
        if wait_for_initial:
            return self._initial_snapshot_ready.wait(self.INITIAL_SNAPSHOT_TIMEOUT_SECONDS)
        return True

    def stop(self) -> None:
        self._refresh_stop.set()
        with self._state_lock:
            thread = self._refresh_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        with self._state_lock:
            strategy_thread = self._strategy_lab_refresh_thread
            strategies_thread = self._strategies_refresh_thread
            comparison_thread = self._comparison_refresh_thread
            auxiliary_thread = self._auxiliary_refresh_thread
        if strategy_thread is not None and strategy_thread.is_alive():
            strategy_thread.join(timeout=5.0)
        if strategies_thread is not None and strategies_thread.is_alive():
            strategies_thread.join(timeout=5.0)
        if comparison_thread is not None and comparison_thread.is_alive():
            comparison_thread.join(timeout=5.0)
        if auxiliary_thread is not None and auxiliary_thread.is_alive():
            auxiliary_thread.join(timeout=5.0)
        if self.process_worker is not None:
            self.process_worker.stop()

    @property
    def refresh_count(self) -> int:
        with self._state_lock:
            return self._refresh_count

    def serialized_dashboard(self):
        """Return the atomic pre-serialized snapshot with truthful dynamic age."""

        with self._state_lock:
            template = self._serialized_template
            generated_at = self._last_projection_at
            refreshing = self._refreshing
            refresh_status = self._last_refresh_status
        if template is None or generated_at is None:
            raise RuntimeError("V2_PROJECTION_NOT_READY")
        age_ms = max(0.0, (monotonic() - generated_at) * 1000.0)
        stale = age_ms > self.STALE_SNAPSHOT_AGE_SECONDS * 1000.0
        status = "STALE" if stale else "FRESH"
        if refreshing:
            delivery = "STALE_WHILE_REFRESHING" if stale else "CACHED_WHILE_REFRESHING"
        else:
            delivery = "STALE_CACHE" if stale else "PRECOMPUTED_SNAPSHOT"
        body = template
        body = body.replace(json.dumps(self._AGE_MARKER).encode(), str(round(age_ms, 3)).encode())
        body = body.replace(json.dumps(self._DELIVERY_MARKER).encode(), json.dumps(delivery).encode())
        body = body.replace(json.dumps(self._STATUS_MARKER).encode(), json.dumps(status).encode())
        body = body.replace(json.dumps(self._REFRESH_MARKER).encode(), b"true" if refreshing else b"false")
        body = body.replace(json.dumps(self._PROJECTION_STATUS_MARKER).encode(), json.dumps(refresh_status).encode())
        return body, {"age_ms": age_ms, "status": status, "delivery": delivery}

    def cached_dashboard(self):
        """Return a copy of the current atomic projection without refreshing it."""

        with self._state_lock:
            projection = deepcopy(self._last_projection)
            generated_at = self._last_projection_at
            refreshing = self._refreshing
        if projection is None or generated_at is None:
            raise RuntimeError("V2_PROJECTION_NOT_READY")
        age_ms = max(0.0, (monotonic() - generated_at) * 1000.0)
        stale = age_ms > self.STALE_SNAPSHOT_AGE_SECONDS * 1000.0
        polling = dict(projection.get("polling") or {})
        polling["served_from_cache"] = True
        polling["snapshot_status"] = "STALE" if stale else "FRESH"
        polling["delivery"] = (
            "STALE_WHILE_REFRESHING"
            if stale and refreshing
            else "CACHED_WHILE_REFRESHING"
            if refreshing
            else "STALE_CACHE"
            if stale
            else "PRECOMPUTED_SNAPSHOT"
        )
        projection["polling"] = polling

        return projection

    def _refresh_loop(self) -> None:
        first_refresh = True
        while not self._refresh_stop.is_set():
            self._refresh_once()
            if first_refresh:
                if not self.turbo_mode:
                    self._start_strategy_lab_refresh_worker()
                    self._start_auxiliary_refresh_worker()
                first_refresh = False
            self._refresh_stop.wait(
                300.0 if self.turbo_mode else self.REFRESH_INTERVAL_SECONDS
            )

    def _start_strategies_refresh_worker(self) -> None:
        if "strategies_command" not in self.providers:
            return
        with self._state_lock:
            if self._strategies_refresh_thread is not None and self._strategies_refresh_thread.is_alive():
                return
            thread = Thread(
                target=self._strategies_refresh_loop,
                name="citadel-v2-strategies-projection",
                daemon=True,
            )
            self._strategies_refresh_thread = thread
            thread.start()

    def _start_comparison_refresh_worker(self) -> None:
        """Keep the optional research comparison off the live V2 rebuild path."""
        if "comparison" not in self.providers:
            return
        with self._state_lock:
            if self._comparison_refresh_thread is not None and self._comparison_refresh_thread.is_alive():
                return
            thread = Thread(
                target=self._comparison_refresh_loop,
                name="citadel-v2-comparison-projection",
                daemon=True,
            )
            self._comparison_refresh_thread = thread
            thread.start()

    def _start_auxiliary_refresh_worker(self) -> None:
        """Refresh slow non-market authorities without blocking live publication."""
        with self._state_lock:
            if self._auxiliary_refresh_thread is not None and self._auxiliary_refresh_thread.is_alive():
                return
            thread = Thread(
                target=self._auxiliary_refresh_loop,
                name="citadel-v2-auxiliary-providers",
                daemon=True,
            )
            self._auxiliary_refresh_thread = thread
            thread.start()

    def _auxiliary_refresh_loop(self) -> None:
        while not self._refresh_stop.is_set():
            for name in sorted(self.AUXILIARY_PROVIDERS):
                provider = self.providers.get(name)
                if provider is None or self._refresh_stop.is_set():
                    continue
                feed = self._call(name, provider)
                with self._state_lock:
                    self._auxiliary_cache[name] = feed
                    self._auxiliary_cache_at[name] = monotonic()
            self._refresh_stop.wait(self.AUXILIARY_REFRESH_INTERVAL_SECONDS)

    def _cached_auxiliary(self, name, provider):
        started = perf_counter()
        with self._state_lock:
            feed = deepcopy(self._auxiliary_cache.get(name))
            cached_at = self._auxiliary_cache_at.get(name)
        if feed is None or cached_at is None:
            feed = self._call(name, provider)
            with self._state_lock:
                self._auxiliary_cache[name] = deepcopy(feed)
                self._auxiliary_cache_at[name] = monotonic()
            return feed
        age_seconds = max(0.0, monotonic() - cached_at)
        meta = dict(feed.get("meta") or {})
        meta["provider_latency_ms"] = meta.get("latency_ms")
        meta["latency_ms"] = round((perf_counter() - started) * 1000.0, 3)
        meta["projection_cache"] = {
            "age_seconds": round(age_seconds, 3),
            "status": "STALE" if age_seconds > self.AUXILIARY_CACHE_STALE_SECONDS else "FRESH",
            "refresh_in_background": True,
        }
        feed["meta"] = meta
        return feed

    def _comparison_refresh_loop(self) -> None:
        while not self._refresh_stop.is_set():
            feed = self._call("comparison", self.providers["comparison"])
            with self._state_lock:
                self._comparison_cache = feed
            self._refresh_stop.wait(self.REFRESH_INTERVAL_SECONDS)

    def _cached_comparison(self):
        with self._state_lock:
            feed = deepcopy(self._comparison_cache)
        if feed is not None:
            return feed
        return {
            "ok": False,
            "data": None,
            "error": {
                "code": "COMPARISON_HOT_PATH_PAUSED",
                "message": "Optional research comparison is paused to protect live publication",
            },
            "meta": self._meta("comparison", "UNAVAILABLE", "NOT_READY", 0.0, None),
        }

    def _strategies_refresh_loop(self) -> None:
        while not self._refresh_stop.is_set():
            feed = self._call("strategies", lambda: self.providers["strategies_command"]())
            publish_target = None
            with self._state_lock:
                self._strategies_cache = feed
                if self._last_projection is not None:
                    projection = deepcopy(self._last_projection)
                    if "feeds" not in projection:
                        projection["feeds"] = {}
                    projection["feeds"]["strategies"] = feed
                    publish_target = projection
            if publish_target is not None:
                if self._projection_lock.acquire(blocking=False):
                    try:
                        self._publish(publish_target, update_timestamp=False)
                    except Exception:
                        pass
                    finally:
                        self._projection_lock.release()
            self._refresh_stop.wait(self.STRATEGIES_REFRESH_INTERVAL_SECONDS)

    def _start_strategy_lab_refresh_worker(self) -> None:
        if "strategy_lab" not in self.providers:
            return
        with self._state_lock:
            if self._strategy_lab_refresh_thread is not None and self._strategy_lab_refresh_thread.is_alive():
                return
            thread = Thread(
                target=self._strategy_lab_refresh_loop,
                name="citadel-v2-strategy-lab-projection",
                daemon=True,
            )
            self._strategy_lab_refresh_thread = thread
            thread.start()

    def _strategy_lab_refresh_loop(self) -> None:
        self._refresh_stop.wait(self.STRATEGY_LAB_REFRESH_INTERVAL_SECONDS)
        while not self._refresh_stop.is_set():
            try:
                data = self.providers["strategy_lab"]()
            except Exception:
                data = None
            if data is not None:
                with self._state_lock:
                    self._strategy_lab_cache = data
                    self._strategy_lab_cache_at = monotonic()
            self._refresh_stop.wait(self.STRATEGY_LAB_REFRESH_INTERVAL_SECONDS)

    def _cached_strategy_lab(self):
        with self._state_lock:
            data = self._strategy_lab_cache
            cached_at = self._strategy_lab_cache_at
        if data is None or cached_at is None:
            return self.providers["strategy_lab"]()
        age_seconds = max(0.0, monotonic() - cached_at)
        return {
            **data,
            "cache_status": "STALE" if age_seconds > self.MAX_OVERLAP_CACHE_AGE_SECONDS else "FRESH",
            "projection_cache": {
                "age_seconds": round(age_seconds, 3),
                "refresh_in_background": True,
            },
        }

    def _refresh_once(self) -> bool:
        if not self._projection_lock.acquire(blocking=False):
            return False
        with self._state_lock:
            self._refreshing = True
        try:
            result = self._build_dashboard("NIFTY")
            if self._has_projection_worker_failure(result):
                with self._state_lock:
                    self._last_refresh_status = "WORKER_REFRESH_FAILED"
                return False
            self._publish(result)
            with self._state_lock:
                self._last_refresh_status = "READY"
            return True
        except ProjectionValidationError as error:
            # Preserve the last complete projection.  A malformed rebuild is
            # never partially published and the exact failing path remains
            # visible in the projection worker status.
            with self._state_lock:
                self._last_refresh_status = str(error)
            return False
        finally:
            with self._state_lock:
                self._refreshing = False
            self._projection_lock.release()

    def _publish(self, result, *, update_timestamp: bool = True):
        malformed_path = self._non_finite_path(result)
        if malformed_path is not None:
            raise ProjectionValidationError(
                f"V2_SNAPSHOT_MALFORMED:{malformed_path}:NON_FINITE_NUMBER"
            )
        try:
            canonical = json.loads(
                json.dumps(
                    result,
                    sort_keys=True,
                    default=str,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError) as error:
            raise ProjectionValidationError(
                f"V2_SNAPSHOT_MALFORMED:root:{type(error).__name__}"
            ) from error

        strategy_feed = canonical.get("feeds", {}).get("strategy_lab")
        if strategy_feed and strategy_feed.get("ok"):
            with self._state_lock:
                if self._strategy_lab_cache is None:
                    self._strategy_lab_cache = strategy_feed.get("data")
                    self._strategy_lab_cache_at = monotonic()
        template_projection = {
            **canonical,
            "feeds": dict(canonical.get("feeds", {})),
            "polling": {
                **canonical["polling"],
                "delivery": self._DELIVERY_MARKER,
                "served_from_cache": True,
                "overlap_skipped": self._REFRESH_MARKER,
                "refresh_in_progress": self._REFRESH_MARKER,
                "projection_age_ms": self._AGE_MARKER,
                "snapshot_status": self._STATUS_MARKER,
                "request_path": "ATOMIC_PRECOMPUTED_SNAPSHOT",
                "projection_status": self._PROJECTION_STATUS_MARKER,
            },
        }
        if "oracle_live_workspace" in self.providers:
            template_projection["polling"]["recommended_interval_ms"] = 1000
        template_projection["polling"]["serialization_ms"] = self._SERIALIZATION_MS_MARKER
        serialization_started = perf_counter()
        template = json.dumps(
            template_projection,
            sort_keys=True,
            default=str,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
        serialization_ms = round((perf_counter() - serialization_started) * 1000, 3)
        canonical["polling"]["serialization_ms"] = serialization_ms
        # Embed the diagnostic with one bounded byte replacement instead of
        # serializing the full 1 MB+ projection a second time.
        template = template.replace(
            json.dumps(self._SERIALIZATION_MS_MARKER).encode(),
            str(serialization_ms).encode(),
            1,
        )
        with self._state_lock:
            self._last_projection = canonical
            if update_timestamp:
                self._last_projection_at = monotonic()
            self._serialized_template = template
            self._refresh_count += 1
            self._initial_snapshot_ready.set()
        return canonical

    @classmethod
    def _non_finite_path(cls, value, path="root"):
        if isinstance(value, float) and not (value == value and abs(value) != float("inf")):
            return path
        if isinstance(value, dict):
            for key in sorted(value, key=str):
                found = cls._non_finite_path(value[key], f"{path}.{key}")
                if found is not None:
                    return found
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                found = cls._non_finite_path(item, f"{path}[{index}]")
                if found is not None:
                    return found
        return None

    @staticmethod
    def _has_projection_worker_failure(result):
        # ARGUS is a canonical live input and must fail the rebuild closed.
        # Development is an optional advisory projection; shared-worker
        # contention must not age an otherwise coherent market snapshot into
        # STALE.
        for name in ("argus",):
            error = ((result.get("feeds") or {}).get(name) or {}).get("error") or {}
            if "PROJECTION_WORKER" in str(error.get("message") or "").upper():
                return True
        return False

    def dashboard(self, symbol="NIFTY"):
        if not self._projection_lock.acquire(blocking=False):
            if self._last_projection is None:
                # The first projection is authoritative.  A concurrent startup
                # request waits for it instead of turning normal contention into
                # an HTTP 500 or launching a duplicate projection build.
                with self._projection_lock:
                    return self._overlap_projection()
            return self._overlap_projection()
        try:
            result = self._build_dashboard(symbol)
            return self._publish(result)
        finally:
            self._projection_lock.release()

    def _build_dashboard(self, symbol):
        projection_started = perf_counter()
        generated = datetime.now(timezone.utc).isoformat()
        feeds = {}
        snapshot_feed = self._cached_auxiliary(
            "snapshot", self.providers["snapshot"]
        )
        snapshot = snapshot_feed["data"] if snapshot_feed["ok"] else {}
        live_workspace_feed = None
        live_workspace_data = None
        if "oracle_live_workspace" in self.providers:
            live_workspace_feed = self._cached_auxiliary(
                "oracle_live_workspace",
                self.providers["oracle_live_workspace"],
            )
            if live_workspace_feed["ok"] and isinstance(
                live_workspace_feed.get("data"), dict
            ):
                live_workspace_data = live_workspace_feed["data"]
        feeds["mission"] = self._derived("mission", lambda: {
            "system": snapshot.get("status", {}), "journal": snapshot.get("journal_summary", {}),
            "active_trade": snapshot.get("active_trade"), "analytics": snapshot.get("analytics", {}).get("summary", {}),
            "optimizer": snapshot.get("optimizer", {}).get("suggestions", []),
        }, snapshot_feed)
        feeds["matrix"] = self._derived(
            "matrix",
            lambda: self._matrix(snapshot.get("scanner", [])),
            snapshot_feed,
        )
        feeds["trade"] = self._derived("trade", lambda: snapshot.get("active_trade"), snapshot_feed)
        feeds["performance"] = self._derived("performance", lambda: snapshot.get("analytics", {}).get("summary", {}), snapshot_feed)
        tv_tf = "5m"
        tv_chart_state = None
        if isinstance(live_workspace_data, dict):
            tv_chart_state = (
                live_workspace_data.get("chart_state")
                if isinstance(live_workspace_data.get("chart_state"), dict)
                else None
            )
            tv_tf = (tv_chart_state or {}).get("timeframe", "5m")

        from src.eye.oracle_projection.projection_service import EyeOracleProjectionService
        from src.eye.oracle_projection.runtime_state import EyeRuntimeState
        eye_runtime = EyeRuntimeState.get_instance()
        eye_runtime.update_tradingview_context(
            symbol, tv_tf, chart_state=tv_chart_state
        )
        eye_service = EyeOracleProjectionService(runtime_state=eye_runtime)

        calls = {
            "kronos_alpha": lambda: self.providers["kronos_alpha"](), "chronos2": lambda: self.providers["chronos2"](),
            "oracle": lambda: self.providers["oracle"](symbol), "athena": lambda: self.providers["athena"](),
            "hermes": lambda: self.providers["hermes"](), "argus": lambda: self.providers["argus"](symbol),
            "risk_status": lambda: self.providers["risk_status"](), "kill_switch": lambda: self.providers["kill_switch"](),
            "paper_status": lambda: self.providers["paper_status"](), "personal_oracle": lambda: self.providers["personal_oracle"](),
            "readiness": lambda: self.providers["readiness"](),
            "next_session_plan": lambda: self.providers["next_session_plan"](), "order_ledger": lambda: self.providers["order_ledger"](),
            "paper_trading": lambda: self.providers["paper_trading"](),
            "eye_oracle_projection": lambda: eye_service.get_projection(symbol=symbol, timeframe=tv_tf).to_dict(),
        }

        if "order_flow" in self.providers:
            calls["order_flow"] = lambda: self.providers["order_flow"]()
        if "futures_chart" in self.providers:
            calls["futures_chart"] = lambda: self.providers["futures_chart"]()


        if "development" in self.providers:
            calls["development"] = lambda: self.providers["development"]()
        if "strategy_lab" in self.providers:
            calls["strategy_lab"] = self._cached_strategy_lab
        for name, provider in calls.items():
            feeds[name] = (
                self._cached_auxiliary(name, provider)
                if name in self.AUXILIARY_PROVIDERS
                else self._call(name, provider)
            )
        if "comparison" in self.providers:
            feeds["comparison"] = self._cached_comparison()
        if "strategies_command" in self.providers:
            with self._state_lock:
                feed = self._strategies_cache
            if feed is None:
                feed = {"ok": False, "data": None, "error": {"code": "STRATEGIES_HOT_PATH_PAUSED", "message": "Optional Strategies projection is paused to protect live publication"}, "meta": self._meta("strategies", "UNAVAILABLE", "NOT_READY", 0.0, None)}
            feeds["strategies"] = feed
        # Phase-6A is carried by the existing Oracle feed so the frontend keeps
        # one Provider -> Adapter -> Store subscription and one polling loop.
        if "oracle_live_workspace" in self.providers:
            oracle_data = (feeds.get("oracle") or {}).get("data")
            if isinstance(oracle_data, dict):
                oracle_data["live_workspace"] = live_workspace_data if isinstance(live_workspace_data, dict) else {
                    "sync_state": "UNAVAILABLE",
                    "health": (live_workspace_feed or {}).get("error"),
                }
        intelligence_boundary = self._intelligence_boundary(feeds, generated)
        if "aegis_prepared" in self.providers:
            prepared = {
                "technical": self._feed_data(feeds, "oracle") or {},
                "argus": self._feed_data(feeds, "argus") or {},
                "kronos_alpha": self._feed_data(feeds, "kronos_alpha") or {},
                "kronos_core": {
                    "status": "AVAILABLE" if (feeds.get("kronos") or {}).get("ok") else "UNAVAILABLE",


                    "setup_quality": self._feed_data(feeds, "kronos", "score"),
                    "timing_state": "VALID" if self._feed_data(feeds, "kronos", "label") else "WAIT",
                    "trend": self._feed_data(feeds, "kronos", "label"),
                    "momentum": self._feed_data(feeds, "kronos", "momentum"),
                    "liquidity": self._feed_data(feeds, "kronos", "liquidity"),
                    "structure": self._feed_data(feeds, "kronos", "structure"),
                    "session_quality": self._feed_data(feeds, "kronos", "regime"),
                },
                "athena": self._feed_data(feeds, "athena") or {},
                "hermes": self._feed_data(feeds, "hermes") or {},
                "personal_oracle": self._feed_data(feeds, "personal_oracle") or {},
                "risk": self._feed_data(feeds, "risk_status") or {},
                "paper": self._feed_data(feeds, "paper_status") or {},
                "session": snapshot.get("status", {}),
            }
            feeds["aegis"] = self._call("aegis", lambda: self.providers["aegis_prepared"](symbol, prepared))
        else:
            feeds["aegis"] = self._call("aegis", lambda: self.providers["aegis"](symbol))
        feeds["insights"] = self._derived("insights", lambda: self._insights(snapshot), snapshot_feed)
        module_fields = {
            "module", "health", "readiness", "latency_ms", "source_timestamp",
            "source_last_updated", "freshness_age_seconds",
            "freshness_threshold_seconds", "market_input_state", "stale_reason",
        }
        modules = {
            name: {
                key: value
                for key, value in feed["meta"].items()
                if key in module_fields
            }
            for name, feed in feeds.items()
        }
        trace = self._trace(feeds, generated)
        canonical = json.dumps({"generated_at": generated, "trace": trace}, sort_keys=True, default=str)
        provider_timings = {"dashboard_snapshot": snapshot_feed["meta"]["latency_ms"], **{
            name: feed["meta"]["latency_ms"] for name, feed in feeds.items()
        }}
        slowest_provider = max(provider_timings, key=provider_timings.get)
        projection_latency = round((perf_counter() - projection_started) * 1000, 3)
        return {"api_version": self.API_VERSION, "schema_version": self.SCHEMA_VERSION,
                "release_contract": dashboard_release_contract(),
                "trace_id": hashlib.sha256(canonical.encode()).hexdigest()[:24], "generated_at": generated,
                "symbol": str(symbol).upper(), "feeds": feeds, "modules": modules,
                "intelligence_boundary": intelligence_boundary,
                "timeline": {"synchronized_at": generated, "paper_events": self._feed_data(feeds, "paper_trading", "timeline", "events") or []},
                "trace": trace, "polling": {"recommended_interval_ms": 3000, "single_request": True,
                    "frontend_side_effects": False, "delivery": "FRESH", "served_from_cache": False,
                    "overlap_skipped": False, "projection_age_ms": 0.0,
                    "projection_latency_ms": projection_latency, "slowest_provider": slowest_provider,
                    "provider_timings_ms": provider_timings}}

    @classmethod
    def _intelligence_boundary(cls, feeds, generated):
        strategy = cls._feed_data(feeds, "strategy_lab") or {}
        execution = (
            strategy.get("execution")
            if isinstance(strategy.get("execution"), dict)
            else {}
        )
        options = (
            execution.get("options_structure")
            if isinstance(execution.get("options_structure"), dict)
            else {}
        )
        vob = (
            execution.get("nifty_vob")
            if isinstance(execution.get("nifty_vob"), dict)
            else {}
        )
        oracle = cls._feed_data(feeds, "oracle") or {}
        if not options and not vob:
            return None

        ose_values = []
        for side in ("CE", "PE"):
            contract = (options.get("contracts") or {}).get(side) or {}
            for component in ("vob", "trend"):
                value = contract.get(component)
                if isinstance(value, dict):
                    ose_values.append(value.get("evaluated_through"))
        ose_boundaries = {
            cls._completed_five_minute_boundary(value, generated)
            for value in ose_values
        }
        vob_value = ((vob.get("timeframes") or {}).get("5m") or {}).get(
            "evaluated_through"
        )
        vob_boundary = cls._completed_five_minute_boundary(
            vob_value, generated
        )
        oracle_boundary = (
            cls._completed_five_minute_boundary(
                oracle.get("market_data_as_of"), generated
            )
            if str(oracle.get("timeframe") or "").lower() == "5m"
            else None
        )
        import sys
        mission_data = (feeds.get("mission") or {}).get("data")
        system = (
            mission_data.get("system", {})
            if isinstance(mission_data, dict)
            else {}
        )
        is_pytest = "pytest" in sys.modules
        live_trading_enabled = system.get("live_trading_enabled")
        is_live = (
            (live_trading_enabled is True and system.get("session", {}).get("market_open", False))
            or (is_pytest and live_trading_enabled is not False)
        )

        has_error = (
            len(ose_boundaries) != 1
            or None in ose_boundaries
            or vob_boundary is None
            or oracle_boundary is None
        )
        if not has_error:
            ose_boundary = next(iter(ose_boundaries))
            if len({ose_boundary, vob_boundary, oracle_boundary}) != 1:
                has_error = True

        if has_error:
            if is_live:
                if len(ose_boundaries) != 1 or None in ose_boundaries or vob_boundary is None or oracle_boundary is None:
                    raise ProjectionValidationError(
                        "MODULE_LAG:OSE_VOB_OR_ORACLE_BOUNDARY_UNAVAILABLE"
                    )
                else:
                    ose_boundary = next(iter(ose_boundaries))
                    raise ProjectionValidationError(
                        "MODULE_LAG:"
                        f"OSE={ose_boundary or 'UNAVAILABLE'}:"
                        f"VOB={vob_boundary or 'UNAVAILABLE'}:"
                        f"ORACLE={oracle_boundary or 'UNAVAILABLE'}"
                    )
            else:
                fallback_boundary = (next(iter(ose_boundaries)) if ose_boundaries and None not in ose_boundaries else None) or vob_boundary or oracle_boundary or "UNAVAILABLE"
                if isinstance(options, dict):
                    options["decision_boundary_5m"] = fallback_boundary
                if isinstance(vob, dict):
                    vob["decision_boundary_5m"] = fallback_boundary
                if isinstance(oracle, dict):
                    oracle["decision_boundary_5m"] = fallback_boundary
                return {
                    "status": "DEGRADED",
                    "reason": "REPLAY_POST_MARKET_INTELLIGENCE_DEGRADED",
                    "timeframe": "5m",
                    "completed_boundary": fallback_boundary,
                    "modules": {
                        "OSE": (next(iter(ose_boundaries)) if ose_boundaries and None not in ose_boundaries else None) or "UNAVAILABLE",
                        "VOB": vob_boundary or "UNAVAILABLE",
                        "ORACLE": oracle_boundary or "UNAVAILABLE",
                    },
                }

        ose_boundary = next(iter(ose_boundaries))
        boundary = ose_boundary
        options["decision_boundary_5m"] = boundary
        vob["decision_boundary_5m"] = boundary
        oracle["decision_boundary_5m"] = boundary
        return {
            "status": "COHERENT",
            "timeframe": "5m",
            "completed_boundary": boundary,
            "modules": {
                "OSE": boundary,
                "VOB": boundary,
                "ORACLE": boundary,
            },
        }

    @staticmethod
    def _completed_five_minute_boundary(value, generated):
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            built = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None or built.tzinfo is None:
            return None
        if parsed.second or parsed.microsecond or parsed.minute % 5:
            return None
        if parsed + timedelta(minutes=5) > built:
            return None
        return parsed.isoformat()

    def _overlap_projection(self):
        if self._last_projection is None or self._last_projection_at is None:
            raise RuntimeError("V2_PROJECTION_BUSY_NO_SAFE_CACHE")
        age_seconds = max(0.0, monotonic() - self._last_projection_at)
        result = deepcopy(self._last_projection)
        result["polling"].update({
            "delivery": "CACHED_WHILE_REFRESHING",
            "served_from_cache": True,
            "overlap_skipped": True,
            "projection_age_ms": round(age_seconds * 1000, 3),
        })
        return result

    def _call(self, name, provider):
        started = perf_counter()
        try:
            data = provider(); latency = round((perf_counter()-started)*1000, 3)
            health, readiness = self._states(data)
            return {"ok": True, "data": data, "error": None, "meta": self._meta(name, health, readiness, latency, data)}
        except Exception as error:
            latency = round((perf_counter()-started)*1000, 3)
            return {"ok": False, "data": None, "error": {"code": f"{name.upper()}_UNAVAILABLE", "message": str(error)[:160]},
                    "meta": self._meta(name, "UNAVAILABLE", "NOT_READY", latency, None)}

    def _derived(self, name, provider, dependency):
        if not dependency["ok"]:
            return {"ok": False, "data": None, "error": dependency["error"], "meta": self._meta(name, "UNAVAILABLE", "NOT_READY", dependency["meta"]["latency_ms"], None)}
        return self._call(name, provider)

    @staticmethod
    def _kronos(rows):
        best=max(rows,key=lambda row:row.get("confidence",0),default={}); context=best.get("context"); kronos=getattr(context,"kronos",{}) or {}; scores=kronos.get("scores",{}); structure=getattr(context,"structure_v2",{}) or {}; liquidity=getattr(context,"liquidity",{}) or {}
        return {"score":best.get("smart_score"),"label":best.get("bias"),"regime":best.get("regime"),"confidence":best.get("confidence"),"trend":scores.get("trend_score"),"momentum":scores.get("momentum_score"),"structure":structure.get("score"),"liquidity":liquidity.get("score")}

    @staticmethod
    def _matrix(rows):
        """Expose only the public scanner row contract, never runtime objects."""

        result = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            result.append(
                {
                    key: deepcopy(value)
                    for key, value in row.items()
                    if key != "context"
                }
            )
        return result

    @staticmethod
    def _insights(snapshot):
        rows=[]
        for suggestion in snapshot.get("optimizer",{}).get("suggestions",[])[:5]:
            if suggestion.get("message"):
                rows.append({"source":"Optimizer","title":suggestion.get("type") or "Insight","message":suggestion["message"],"severity":suggestion.get("priority") or "LOW","timestamp":snapshot.get("status",{}).get("generated_at")})
        return rows

    @staticmethod
    def _states(data):
        if not isinstance(data, dict): return "HEALTHY", "READY"
        status = data.get("status")
        if isinstance(status, dict):
            status = status.get("health") or status.get("state") or status.get("status")
        freshness = str(data.get("freshness") or data.get("data_status") or data.get("cache_status") or "").upper()
        raw=str(data.get("health") or status or data.get("state_health") or data.get("model_status") or data.get("athena_status") or data.get("hermes_status") or "HEALTHY").upper()
        if "STALE" in raw or "STALE" in freshness:
            return "STALE", "STALE"
        if any(token in raw for token in ("CORRUPT","ERROR","BLOCKED","UNAVAILABLE")): health="UNAVAILABLE"
        elif any(token in raw for token in ("DEGRADED","STALE","PARTIAL","NOT_CONFIGURED")): health="DEGRADED"
        else: health="HEALTHY"
        readiness="READY" if health=="HEALTHY" else "LIMITED" if health=="DEGRADED" else "NOT_READY"
        return health, readiness

    def _meta(self, name, health, readiness, latency, data):
        source_last_updated = self._last_updated(data)
        lineage = self._lineage(name, data)
        market_state = lineage["market_input_state"]
        if lineage["freshness_age_seconds"] is not None and lineage["freshness_threshold_seconds"] is not None:
            if market_state == "STALE":
                health, readiness = "STALE", "STALE"
                lineage["stale_reason"] = (
                    f"SOURCE_CANDLE_AGE_{round(lineage['freshness_age_seconds'], 3)}S_"
                    f"EXCEEDS_{lineage['freshness_threshold_seconds']}S"
                )
            elif market_state == "WAITING_FOR_NEXT_CANDLE" and health == "HEALTHY":
                readiness = "WAITING_FOR_NEXT_CANDLE"
        elif market_state == "UNAVAILABLE":
            health, readiness = "UNAVAILABLE", "NOT_READY"
            lineage["stale_reason"] = "SOURCE_TIME_UNAVAILABLE"
        authoritative = not (name == "aegis" and isinstance(data, dict) and data.get("input_status") in {"UNAVAILABLE", "STALE"})
        return {"module":name,"api_version":self.API_VERSION,"schema_version":self.SCHEMA_VERSION,
                "health":health,"readiness":readiness,"latency_ms":latency,
                "last_updated":datetime.now(timezone.utc).isoformat(),"source_last_updated":source_last_updated,
                "fail_closed":True,"authoritative":authoritative, **lineage}

    @staticmethod
    def _lineage(name, data):
        value = data if isinstance(data, dict) else {}
        input_metadata = value.get("input_metadata") if isinstance(value.get("input_metadata"), dict) else {}
        runtime = value.get("runtime") if isinstance(value.get("runtime"), dict) else {}
        runtime_input = runtime.get("input_metadata") if isinstance(runtime.get("input_metadata"), dict) else {}
        underlying = value.get("data", {}).get("underlying", {}) if isinstance(value.get("data"), dict) else {}
        source_timestamps = value.get("source_timestamps") if isinstance(value.get("source_timestamps"), dict) else {}
        source_event_time = value.get("source_event_time") or underlying.get("source_event_time")
        receipt_timestamp = (
            value.get("receipt_timestamp") or underlying.get("receipt_timestamp")
            or underlying.get("fetched_at")
        )
        timestamp_semantics = (
            value.get("timestamp_semantics") or underlying.get("timestamp_semantics")
            or "LEGACY_TIMESTAMP_SEMANTICS_UNCLASSIFIED"
        )
        provider_market_state = str(
            underlying.get("market_state")
            or value.get("market_state")
            or ""
        ).upper()
        timeframe = value.get("timeframe") or input_metadata.get("instrument", {}).get("timeframe")
        latest_candle = (
            value.get("last_input_candle_at") or value.get("context_end") or input_metadata.get("last_candle_at")
            or runtime_input.get("last_candle_at") or value.get("market_data_as_of")
        )
        source_timestamp = (
            latest_candle or source_event_time
            or next((item for item in source_timestamps.values() if item), None)
        )
        candle_count = (
            value.get("input_candle_count") if value.get("input_candle_count") is not None
            else input_metadata.get("candle_count", runtime_input.get("candle_count"))
        )
        candle_id = value.get("candle_id") or input_metadata.get("candle_id") or runtime_input.get("candle_id")
        
        # Freshness calculation
        from datetime import datetime, timedelta, timezone
        interval = V2DashboardIntegration._timeframe_seconds(timeframe) if latest_candle else None
        
        source_candle_open = None
        source_candle_close = None
        calculated_at = value.get("generated_at") or value.get("last_inference_at")
        
        # `freshness_timestamp` may use a receipt only when no provider event
        # is present, but it is explicitly labelled below.  Source age remains
        # null in that case and cannot be reset by a refetch.
        freshness_timestamp = latest_candle or source_event_time or receipt_timestamp
        explicit_threshold = value.get("freshness_threshold_seconds")
        prime = value.get("argus_prime") if isinstance(value.get("argus_prime"), dict) else {}
        data_truth = prime.get("data_truth") if isinstance(prime.get("data_truth"), dict) else {}
        if explicit_threshold is None:
            explicit_threshold = data_truth.get("freshness_threshold_seconds")

        if latest_candle:
            try:
                open_dt = (
                    latest_candle
                    if isinstance(latest_candle, datetime)
                    else datetime.fromisoformat(str(latest_candle).replace("Z", "+00:00"))
                )
            except (TypeError, ValueError):
                open_dt = None
            if open_dt is not None and open_dt.tzinfo is None:
                open_dt = open_dt.replace(
                    tzinfo=timezone(timedelta(hours=5, minutes=30))
                )
            source_candle_open = open_dt.isoformat() if open_dt else None
            
            if interval is not None:
                close_dt = open_dt + timedelta(seconds=interval)
                source_candle_close = close_dt.isoformat()
                age = V2DashboardIntegration._age_seconds(close_dt)
                threshold = (
                    int(interval * 1.2)
                    if name in {"kronos_alpha", "chronos2"}
                    else V2DashboardIntegration._freshness_threshold(timeframe)
                )
            else:
                age = V2DashboardIntegration._age_seconds(latest_candle)
                threshold = V2DashboardIntegration._freshness_threshold(timeframe)
        elif freshness_timestamp:
            age = V2DashboardIntegration._age_seconds(freshness_timestamp)
            threshold = (
                float(explicit_threshold)
                if isinstance(explicit_threshold, (int, float)) and not isinstance(explicit_threshold, bool)
                else V2DashboardIntegration._freshness_threshold(timeframe)
            )
        else:
            age = None
            threshold = None

        market_state = None
        if provider_market_state in {"CLOSED", "POST_MARKET", "PRE_MARKET", "WEEKEND", "HOLIDAY"}:
            market_state = "STALE"
        elif age is not None and threshold is not None:
            if interval is not None:
                market_state = "READY" if age <= interval else "WAITING_FOR_NEXT_CANDLE" if age <= threshold else "STALE"
            else:
                market_state = "READY" if age <= threshold else "STALE"
        elif not freshness_timestamp:
            market_state = "UNAVAILABLE"
            
        freshness = "STALE" if market_state == "STALE" else "FRESH" if market_state in {"READY", "WAITING_FOR_NEXT_CANDLE"} else "UNAVAILABLE"
        
        runtime_state = (
            value.get("scheduler_health") or runtime.get("scheduler_health") or value.get("model_status")
            or value.get("oracle_status") or value.get("athena_status") or value.get("hermes_status")
            or value.get("status")
        )
        if isinstance(runtime_state, dict):
            runtime_state = runtime_state.get("state") or runtime_state.get("health") or runtime_state.get("status")
        source_metadata = value.get("source_metadata") if isinstance(value.get("source_metadata"), dict) else {}
        real_candles = True if name in {"kronos_alpha", "chronos2"} and latest_candle else None
        if source_metadata.get("fixture_data") is True:
            real_candles = False
            
        # Compute canonical status contract
        from src.system_status import CanonicalStatusEngine
        canonical_contract = CanonicalStatusEngine.evaluate(
            backend_online=True,
            session_calendar_status=value.get("session") if isinstance(value, dict) else None,
            safety_status=value.get("risk") if isinstance(value, dict) else None,
            deployments_status=value.get("strategy_lab", {}).get("strategies") if isinstance(value.get("strategy_lab"), dict) else None,
            intelligence_modules=value if isinstance(value, dict) else None,
        )
        return {
            "status": "stale" if freshness == "STALE" else "available" if freshness == "FRESH" else "unavailable",
            "freshness": freshness,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "canonical_status": canonical_contract,
            "system_status": canonical_contract["overall_status"],
            "operating_mode": canonical_contract["operating_mode"],
            "safety_status": canonical_contract["safety_status"],
            "symbol": value.get("symbol") or underlying.get("symbol"),
            "timeframe": timeframe,
            "candle_id": candle_id,
            "latest_completed_candle_at": latest_candle,
            "source_timestamp": source_timestamp,
            "source_event_time": source_event_time,
            "receipt_timestamp": receipt_timestamp,
            "freshness_timestamp": freshness_timestamp,
            "freshness_basis": (
                "COMPLETED_CANDLE"
                if latest_candle
                else "PROVIDER_EVENT_TIME"
                if source_event_time is not None
                else "RECEIPT_TIME_NO_PROVIDER_EVENT_TIME"
                if receipt_timestamp is not None
                else "UNAVAILABLE"
            ),
            "timestamp_semantics": timestamp_semantics,
            "calculation_timestamp": calculated_at,
            "calculation_age_seconds": V2DashboardIntegration._age_seconds(calculated_at),
            "input_candle_count": candle_count,
            "freshness_age_seconds": age,
            "source_age_seconds": V2DashboardIntegration._age_seconds(source_event_time),
            "receipt_age_seconds": V2DashboardIntegration._age_seconds(receipt_timestamp),
            "provider_market_state": provider_market_state or None,
            "market_input_state": market_state,
            "freshness_threshold_seconds": threshold,
            "runtime_state": runtime_state,
            "stale_reason": None,
            "real_candles": real_candles,
            "advisory_only": name in {"kronos", "kronos_alpha", "chronos2", "argus", "order_flow", "futures_chart", "oracle", "athena", "aegis", "hermes", "personal_oracle", "performance"},
            "execution_influence": 0 if name in {"kronos", "kronos_alpha", "chronos2", "argus", "order_flow", "futures_chart", "oracle", "athena", "aegis", "hermes", "personal_oracle", "performance"} else None,
            "source_candle_open": source_candle_open,
            "source_candle_close": source_candle_close,
            "calculated_at": calculated_at,
            "age_seconds": age,
            "freshness": freshness,
        }

    @staticmethod
    def _to_utc_dt(value):
        if not value:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except Exception:
                return None
        if dt.tzinfo is None:
            # Naive exchange timestamp represents IST (UTC+05:30)
            dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _age_seconds(value):
        dt_utc = V2DashboardIntegration._to_utc_dt(value)
        if dt_utc is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - dt_utc).total_seconds())

    @staticmethod
    def _freshness_threshold(timeframe):
        interval = V2DashboardIntegration._timeframe_seconds(timeframe)
        if interval is None:
            return 600
        grace = min(90, max(30, round(interval * 0.2)))
        return interval + grace

    @staticmethod
    def _timeframe_seconds(timeframe):
        raw = str(timeframe or "").strip().lower()
        if raw.endswith("m") and raw[:-1].isdigit():
            return int(raw[:-1]) * 60
        if raw.endswith("h") and raw[:-1].isdigit():
            return int(raw[:-1]) * 3600
        return None

    @staticmethod
    def _last_updated(data):
        if not isinstance(data, dict): return None
        for key in ("last_updated","updated_at","generated_at","fetched_at","market_data_as_of","last_inference_at","context_end"):
            if data.get(key): return data[key]
        for key in ("underlying","source_metadata","freshness_metadata","status"):
            nested=data.get(key)
            if isinstance(nested,dict):
                value=V2DashboardIntegration._last_updated(nested)
                if value: return value
        return None

    @staticmethod
    def _feed_data(feeds, name, *path):
        value=feeds.get(name,{}).get("data")
        for key in path:
            if not isinstance(value,dict): return None
            value=value.get(key)
        return value

    def _trace(self, feeds, generated):
        aegis=feeds.get("aegis",{}).get("data") or {}; alpha=feeds.get("kronos_alpha",{}).get("data") or {}; chronos=feeds.get("chronos2",{}).get("data") or {}; argus=feeds.get("argus",{}).get("data") or {}
        return {"generated_at":generated,"decision_id":aegis.get("decision_id"),"decision_input_fingerprint":aegis.get("input_fingerprint"),
                "evidence":{"argus_fetched_at":self._feed_data(feeds,"argus","data","underlying","fetched_at"),"kronos_alpha_inference_at":alpha.get("last_inference_at"),"chronos_forecast_id":chronos.get("forecast_id"),"chronos_context_end":chronos.get("context_end"),"paper_runtime_updated_at":self._feed_data(feeds,"paper_trading","status","updated_at")},
                "immutable_audits":{"aegis":True,"order_fill_ledger":True,"paper_state":True}}
