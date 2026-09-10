"""Process-isolated, pre-serialized publication lane for the Oracle surface."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from threading import Condition, Event, Lock, Thread
from time import monotonic, perf_counter, perf_counter_ns
from typing import Any, Callable, Mapping

from src.oracle.fast_lane_publisher import (
    FastLanePublisherBoundary,
    FastLaneSnapshotProcessor,
    wrap_provider_feed,
)


class OracleFastLane:
    """Collect canonical caches; serve child-built immutable JSON bytes."""

    BASE_NAMES = ("oracle", "strategy_lab", "strategies", "eye_oracle_projection")

    def __init__(
        self,
        *,
        base_provider: Callable[[], Mapping[str, Any]],
        providers: Mapping[str, Callable[[], Any]],
        chart_provider: Callable[[], Any] | None = None,
        interval_seconds: float = 0.10,
        base_interval_seconds: float = 30.0,
        provider_intervals: Mapping[str, float] | None = None,
        push_providers: set[str] | None = None,
        publisher_context_name: str | None = None,
    ) -> None:
        self.base_provider = base_provider
        self.providers = dict(providers)
        self.chart_provider = chart_provider
        self.interval_seconds = max(0.1, float(interval_seconds))
        self.base_interval_seconds = max(5.0, float(base_interval_seconds))
        self.provider_intervals = {
            str(name): max(self.interval_seconds, float(seconds))
            for name, seconds in (provider_intervals or {}).items()
        }
        self.push_providers = {str(name) for name in (push_providers or set())}
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._stop = Event()
        self._publish_requested = Event()
        self._threads: list[Thread] = []
        self._dirty: set[str] = set()
        self._base: dict[str, Any] = {}
        self._base_revisions: dict[str, str] = {}
        self._values: dict[str, Any] = {}
        self._errors: dict[str, str] = {}
        self._revisions: dict[str, str] = {}
        self._body: bytes | None = None
        self._decoded_revision = 0
        self._decoded_dashboard: dict[str, Any] | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=64)
        self._latest_snapshot_event: dict[str, Any] | None = None
        self._pending_flow_meters: dict[str, Any] | None = None
        self._compact_sequence = 0
        self._build_revision = 0
        self._active_revision = 0
        self._source_revisions: dict[str, str] = {}
        self._core_feeds: dict[str, Any] = {}
        self._assembly_ms: deque[float] = deque(maxlen=256)
        self._serialization_ms: deque[float] = deque(maxlen=256)
        self._action_serialization_ms: deque[float] = deque(maxlen=2_048)
        self._meter_serialization_ms: deque[float] = deque(maxlen=2_048)
        self._action_payload_bytes: deque[float] = deque(maxlen=2_048)
        self._meter_payload_bytes: deque[float] = deque(maxlen=2_048)
        self._packet_to_action_event_ms: deque[float] = deque(maxlen=2_048)
        self._event_to_sse_yield_ms: deque[float] = deque(maxlen=2_048)
        self._sse_frame_bytes: deque[float] = deque(maxlen=2_048)
        self._sse_resyncs = 0
        self._sse_full_resyncs = 0
        self._sse_coalesced_events = 0
        self._http_serves = 0
        self._provider_ms: dict[str, deque[float]] = {}
        self._provider_ms_cached: dict[str, dict[str, float | int | None]] = {}
        self._provider_push_monotonic: dict[str, float] = {}
        self._publisher_metrics: dict[str, Any] = {
            "full_builds": 0,
            "full_serializations": 0,
            "duplicate_builds_avoided": 0,
            "feed_serializations": 0,
            "feed_reuses": 0,
            "feed_count": 0,
        }
        self._stats_cache: dict[str, Any] = {}
        self._stats_refresh_monotonic = 0.0
        self._inline_processor = FastLaneSnapshotProcessor()
        self._publisher = FastLanePublisherBoundary(
            on_snapshot=self._on_published_snapshot,
            context_name=publisher_context_name,
        )
        self._refresh_stats_cache_unlocked(force=True)

    def start_publisher(self) -> bool:
        """Start the sole process owner before application threads exist."""

        return self._publisher.start()

    def start(self) -> None:
        self.start_publisher()
        with self._lock:
            if any(thread.is_alive() for thread in self._threads):
                return
            self._stop.clear()
            self._threads = [
                Thread(target=self._base_loop, name="oracle-fast-lane-base", daemon=True),
                Thread(target=self._publisher_loop, name="oracle-fast-lane-submit", daemon=True),
            ]
            self._threads.extend(
                Thread(
                    target=self._critical_provider_loop,
                    args=(name, provider),
                    name=f"oracle-fast-lane-{name}",
                    daemon=True,
                )
                for name, provider in self.providers.items()
                if name not in self.push_providers
            )
            if self.chart_provider is not None:
                self._threads.append(
                    Thread(target=self._chart_loop, name="oracle-fast-lane-chart", daemon=True)
                )
            for thread in self._threads:
                thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._publish_requested.set()
        with self._condition:
            self._condition.notify_all()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        self._publisher.stop(timeout=10.0)

    def _base_loop(self) -> None:
        while not self._stop.is_set():
            try:
                base = dict(self.base_provider())
            except Exception:
                base = {}
            if base:
                feeds = base.get("feeds") if isinstance(base.get("feeds"), Mapping) else {}
                changed: set[str] = set()
                revisions: dict[str, str] = {}
                for name in self.BASE_NAMES:
                    value = feeds.get(name)
                    if value is None and name not in self._base_revisions:
                        continue
                    revision = self._revision(value, None) if value is not None else "missing"
                    revisions[name] = revision
                    if revision != self._base_revisions.get(name):
                        changed.add(name)
                with self._lock:
                    self._base = base
                    self._base_revisions.update(revisions)
                if changed:
                    self._request_publish(changed)
            self._stop.wait(self.base_interval_seconds if base else 1.0)

    def _critical_provider_loop(self, name: str, provider: Callable[[], Any]) -> None:
        while not self._stop.is_set():
            self.refresh_provider(name)
            self._stop.wait(self.provider_intervals.get(name, self.interval_seconds))

    def refresh_provider(self, name: str) -> bool:
        """Refresh one existing cache-only provider after an atomic restore."""

        provider = self.providers.get(name)
        if provider is None:
            return False
        started = perf_counter()
        try:
            value = provider()
            error = None
        except Exception as exc:
            value = None
            error = f"{type(exc).__name__}:{exc}"
        elapsed = (perf_counter() - started) * 1000.0
        return self.publish_provider_value(name, value, error=error, elapsed_ms=elapsed)

    def publish_provider_value(
        self,
        name: str,
        value: Any,
        *,
        error: str | None = None,
        elapsed_ms: float | None = None,
    ) -> bool:
        """Accept one producer-owned cache snapshot without polling it again."""

        name = str(name)
        revision = self._revision(value, error)
        changed = False
        with self._lock:
            if elapsed_ms is not None:
                samples = self._provider_ms.setdefault(name, deque(maxlen=256))
                samples.append(float(elapsed_ms))
                self._provider_ms_cached[name] = self._percentiles(samples)
            if revision != self._revisions.get(name):
                self._revisions[name] = revision
                self._values[name] = value
                if error is None:
                    self._errors.pop(name, None)
                else:
                    self._errors[name] = error
                changed = True
        if changed:
            self._request_publish({name})
        return changed

    def provider_push_due(self, name: str, minimum_interval_seconds: float) -> bool:
        """Bound optional presentation enrichment before a producer push."""

        now = monotonic()
        with self._lock:
            previous = self._provider_push_monotonic.get(str(name))
            if previous is not None and now - previous < max(0.0, minimum_interval_seconds):
                return False
            self._provider_push_monotonic[str(name)] = now
            return True

    def _chart_loop(self) -> None:
        assert self.chart_provider is not None
        while not self._stop.is_set():
            started = perf_counter()
            try:
                value = self.chart_provider()
                error = None
            except Exception as exc:
                value = None
                error = f"{type(exc).__name__}:{exc}"
            elapsed = (perf_counter() - started) * 1000.0
            revision = self._revision(value, error)
            changed = False
            with self._lock:
                samples = self._provider_ms.setdefault("futures_chart", deque(maxlen=256))
                samples.append(elapsed)
                self._provider_ms_cached["futures_chart"] = self._percentiles(samples)
                if revision != self._revisions.get("futures_chart"):
                    self._revisions["futures_chart"] = revision
                    self._values["futures_chart"] = value
                    if error is None:
                        self._errors.pop("futures_chart", None)
                    else:
                        self._errors["futures_chart"] = error
                    changed = True
            if changed:
                self._request_publish({"futures_chart"})
            self._stop.wait(self.interval_seconds)

    def _request_publish(self, changed: set[str]) -> None:
        with self._lock:
            self._dirty.update(changed)
            self._publish_requested.set()

    def _publisher_loop(self) -> None:
        while not self._stop.is_set():
            if not self._publish_requested.wait(1.0):
                continue
            if self._stop.wait(self.interval_seconds):
                break
            with self._lock:
                changed = set(self._dirty)
                self._dirty.clear()
                meters = self._pending_flow_meters
                self._pending_flow_meters = None
                self._publish_requested.clear()
            if changed:
                self._publish(changed)
            if meters is not None:
                self._publish_compact("FLOW_PULSE_METERS", meters)

    def publish_flow_pulse(self, kind: str, payload: Mapping[str, Any]) -> None:
        if kind == "FLOW_PULSE_ACTION":
            self._publish_compact(kind, payload)
            return
        if kind != "FLOW_PULSE_METERS":
            raise ValueError(f"unsupported Flow Pulse publication kind: {kind}")
        with self._lock:
            self._pending_flow_meters = dict(payload)
            self._publish_requested.set()

    def _publish_compact(self, kind: str, payload: Mapping[str, Any]) -> None:
        import json

        serialization_started = perf_counter()
        published_at = datetime.now(timezone.utc).isoformat()
        with self._condition:
            self._compact_sequence += 1
            event_id = f"oracle-fast-compact-{self._compact_sequence}"
            event = {
                "event_id": event_id,
                "event_type": kind,
                "published_at": published_at,
                "trace_id": event_id,
                "generated_at": published_at,
                "symbol": "NIFTY",
                "global_revision": self._active_revision,
                "changed_sections": ["order_flow"],
                "source_revisions": dict(self._source_revisions),
                "flow_pulse": dict(payload),
                "full": False,
                "latency_schema": "ORACLE_HOT_PATH_LATENCY_V2",
                "latency_timestamps": {
                    "t0_packet_receive_ns": payload.get("packet_receive_ns"),
                    "t2_semantic_event_committed_ns": payload.get("action_ready_ns"),
                },
            }
            encoded = json.dumps(
                event, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
            ).encode()
            ready_ns = perf_counter_ns()
            event["_encoded"] = encoded
            event["_fast_lane_ready_ns"] = ready_ns
            elapsed = (perf_counter() - serialization_started) * 1000.0
            if kind == "FLOW_PULSE_ACTION":
                self._action_serialization_ms.append(elapsed)
                self._action_payload_bytes.append(float(len(encoded)))
                packet_receive_ns = payload.get("packet_receive_ns")
                if isinstance(packet_receive_ns, int) and packet_receive_ns > 0:
                    self._packet_to_action_event_ms.append(
                        max(0.0, (ready_ns - packet_receive_ns) / 1_000_000.0)
                    )
            else:
                self._meter_serialization_ms.append(elapsed)
                self._meter_payload_bytes.append(float(len(encoded)))
            self._events.append(event)
            if kind == "FLOW_PULSE_ACTION":
                self._stats_cache["action_serialization_ms"] = self._percentiles(
                    self._action_serialization_ms
                )
                self._stats_cache["action_payload_bytes"] = self._percentiles(
                    self._action_payload_bytes
                )
                self._stats_cache["packet_to_action_event_ms"] = self._percentiles(
                    self._packet_to_action_event_ms
                )
            else:
                self._stats_cache["meter_serialization_ms"] = self._percentiles(
                    self._meter_serialization_ms
                )
                self._stats_cache["meter_payload_bytes"] = self._percentiles(
                    self._meter_payload_bytes
                )
            self._condition.notify_all()

    def record_sse_yield(self, event: Mapping[str, Any], frame_bytes: int) -> None:
        ready_ns = event.get("_fast_lane_ready_ns")
        if not isinstance(ready_ns, int):
            return
        write_ns = perf_counter_ns()
        with self._lock:
            self._event_to_sse_yield_ms.append(
                max(0.0, (write_ns - ready_ns) / 1_000_000.0)
            )
            self._sse_frame_bytes.append(float(frame_bytes))
            self._stats_cache["event_to_sse_yield_ms"] = self._percentiles(
                self._event_to_sse_yield_ms
            )
            self._stats_cache["sse_frame_bytes"] = self._percentiles(self._sse_frame_bytes)

    def _publish(self, changed: set[str]) -> None:
        with self._lock:
            base = self._base
            base_feeds = base.get("feeds") if isinstance(base.get("feeds"), Mapping) else {}
            values = dict(self._values)
            errors = dict(self._errors)
            self._build_revision += 1
            build_revision = self._build_revision
            source_revisions = {
                **{f"base:{name}": revision for name, revision in self._base_revisions.items()},
                **dict(self._revisions),
            }
            base_updates = {
                name: base_feeds[name]
                for name in changed
                if name in self.BASE_NAMES and name in base_feeds
            }
            removed = [
                name for name in changed if name in self.BASE_NAMES and name not in base_feeds
            ]
            provider_updates = {
                name: {"value": values.get(name), "error": errors.get(name)}
                for name in changed
                if name not in self.BASE_NAMES and name != "oracle_live_workspace"
            }
            workspace_update = (
                {
                    "value": values.get("oracle_live_workspace"),
                    "error": errors.get("oracle_live_workspace"),
                }
                if "oracle_live_workspace" in changed
                else None
            )
        payload = {
            "build_revision": build_revision,
            "changed": sorted(changed),
            "source_revisions": source_revisions,
            "base_updates": base_updates,
            "provider_updates": provider_updates,
            "workspace_update": workspace_update,
            "removed": removed,
        }
        if self._publisher.status()["alive"]:
            if not self._publisher.submit("BUILD", payload, timeout=5.0):
                with self._lock:
                    self._dirty.update(changed)
                    self._publish_requested.set()
            return
        # Deterministic inline path is retained only for focused unit tests
        # that explicitly exercise _publish without starting runtime workers.
        result = self._inline_processor("BUILD", payload)
        if result is not None:
            self._on_published_snapshot(result)

    def _on_published_snapshot(self, snapshot: Any) -> None:
        if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("body"), bytes):
            return
        ready_ns = perf_counter_ns()
        event = {
            "event_id": str(snapshot["event_id"]),
            "event_type": "ORACLE_FAST_LANE_UPDATED",
            "published_at": snapshot.get("generated_at"),
            "trace_id": snapshot.get("trace_id"),
            "generated_at": snapshot.get("generated_at"),
            "global_revision": int(snapshot.get("revision") or 0),
            "changed_sections": list(snapshot.get("changed_sections") or ()),
            "source_revisions": dict(snapshot.get("source_revisions") or {}),
            "full": False,
            "_encoded": snapshot.get("patch_event"),
            "_resync_encoded": snapshot.get("resync_event"),
            "_fast_lane_ready_ns": ready_ns,
        }
        with self._condition:
            self._body = snapshot["body"]
            self._active_revision = int(snapshot.get("revision") or 0)
            self._source_revisions = dict(snapshot.get("source_revisions") or {})
            self._core_feeds = dict(snapshot.get("core_feeds") or {})
            self._publisher_metrics.update(
                {
                    key: snapshot.get(key)
                    for key in (
                        "full_builds",
                        "full_serializations",
                        "duplicate_builds_avoided",
                        "feed_serializations",
                        "feed_reuses",
                        "feed_count",
                        "byte_length",
                    )
                }
            )
            self._assembly_ms.append(float(snapshot.get("assembly_ms") or 0.0))
            self._serialization_ms.append(float(snapshot.get("serialization_ms") or 0.0))
            self._events.append(event)
            self._latest_snapshot_event = event
            self._refresh_stats_cache_unlocked(force=True)
            self._condition.notify_all()

    def response(self) -> tuple[bytes, dict[str, Any]]:
        with self._lock:
            body = self._body
            if body is None:
                raise RuntimeError("ORACLE_FAST_LANE_NOT_READY")
            self._http_serves += 1
            metrics = dict(self._stats_cache)
            metrics["http_serves"] = self._http_serves
            return body, metrics

    def compatibility_dashboard(self) -> dict[str, Any]:
        """Decode one immutable published revision for warm legacy consumers.

        Live HTTP/SSE never call this method.  The decoded object is cached by
        revision so mission/research compatibility reads cannot revive the old
        periodic V2 rebuild or repeatedly decode the same megabyte document.
        """

        import json

        with self._lock:
            body = self._body
            revision = self._active_revision
            cached = self._decoded_dashboard if self._decoded_revision == revision else None
        if body is None:
            raise RuntimeError("ORACLE_FAST_LANE_NOT_READY")
        if cached is None:
            decoded = json.loads(body)
            with self._lock:
                if self._active_revision == revision:
                    self._decoded_dashboard = decoded
                    self._decoded_revision = revision
                    cached = decoded
                else:
                    cached = None
            if cached is None:
                return self.compatibility_dashboard()
        return deepcopy(cached)

    def wait_for_events(self, after_event_id: str | None, timeout: float) -> list[dict[str, Any]]:
        """Return prepared current events without copying/encoding under the lock."""

        deadline = monotonic() + max(0.0, timeout)
        with self._condition:
            while not self._stop.is_set():
                events = list(self._events)
                if events:
                    if after_event_id is None:
                        return [self._event_view(events[-1], resync=False)]
                    for index, event in enumerate(events):
                        if event["event_id"] != after_event_id:
                            continue
                        pending = events[index + 1 :]
                        if len(pending) <= 1:
                            if pending:
                                return [self._event_view(pending[0], resync=False)]
                            break
                        return self._coalesce_pending_unlocked(pending)
                    else:
                        return self._prepared_recovery_unlocked(events)
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return []
                self._condition.wait(remaining)
            return []

    def _coalesce_pending_unlocked(self, pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
        snapshots = [event for event in pending if event.get("_resync_encoded") is not None]
        actions = [event for event in pending if event.get("event_type") == "FLOW_PULSE_ACTION"]
        meters = [event for event in pending if event.get("event_type") == "FLOW_PULSE_METERS"]
        result: list[dict[str, Any]] = []
        if snapshots:
            latest_snapshot = snapshots[-1]
            self._sse_resyncs += 1
            self._sse_full_resyncs += 1
            result.append(self._event_view(latest_snapshot, resync=True))
            position = pending.index(latest_snapshot)
            actions = [event for event in pending[position + 1 :] if event.get("event_type") == "FLOW_PULSE_ACTION"]
            meters = [event for event in pending[position + 1 :] if event.get("event_type") == "FLOW_PULSE_METERS"]
        result.extend(self._event_view(event, resync=False) for event in actions)
        if meters:
            result.append(self._event_view(meters[-1], resync=False))
        retained = len(result)
        self._sse_coalesced_events += max(0, len(pending) - retained)
        self._refresh_stats_cache_unlocked()
        return result or [self._event_view(pending[-1], resync=False)]

    def _prepared_recovery_unlocked(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        snapshot = self._latest_snapshot_event
        if snapshot is None:
            return [self._event_view(events[-1], resync=False)]
        self._sse_resyncs += 1
        self._sse_full_resyncs += 1
        self._sse_coalesced_events += max(0, len(events) - 1)
        self._refresh_stats_cache_unlocked()
        result = [self._event_view(snapshot, resync=True)]
        try:
            position = events.index(snapshot)
        except ValueError:
            position = len(events) - 1
        trailing = events[position + 1 :]
        result.extend(
            self._event_view(event, resync=False)
            for event in trailing
            if event.get("event_type") == "FLOW_PULSE_ACTION"
        )
        meters = [event for event in trailing if event.get("event_type") == "FLOW_PULSE_METERS"]
        if meters:
            result.append(self._event_view(meters[-1], resync=False))
        return result

    @staticmethod
    def _event_view(event: Mapping[str, Any], *, resync: bool) -> dict[str, Any]:
        view = {
            key: value
            for key, value in event.items()
            if key not in {"_encoded", "_resync_encoded"}
        }
        if resync and event.get("_resync_encoded") is not None:
            view["event_type"] = "ORACLE_FAST_LANE_RESYNC"
            view["full"] = True
            view["_encoded"] = event["_resync_encoded"]
        else:
            view["_encoded"] = event.get("_encoded")
        return view

    def health(self) -> dict[str, Any]:
        with self._lock:
            provider_readiness = {
                name: self._provider_readiness(value, self._errors.get(name))
                for name, value in self._values.items()
            }
            return {
                "status": "READY" if self._body is not None else "STARTING",
                "payload_size": len(self._body or b""),
                "revision": self._active_revision,
                "source_revisions": dict(self._source_revisions),
                "core_feeds": dict(self._core_feeds),
                "provider_readiness": provider_readiness,
                "publisher": self._publisher.status(),
                "provider_ms": dict(self._provider_ms_cached),
                **dict(self._stats_cache),
                "http_serves": self._http_serves,
                "sse_resyncs": self._sse_resyncs,
                "sse_full_resyncs": self._sse_full_resyncs,
                "sse_coalesced_events": self._sse_coalesced_events,
            }

    def _refresh_stats_cache_unlocked(self, *, force: bool = False) -> None:
        now = monotonic()
        if not force and now - self._stats_refresh_monotonic < 1.0:
            return
        self._stats_refresh_monotonic = now
        self._stats_cache = {
            "assembly_ms": self._percentiles(self._assembly_ms),
            "serialization_ms": self._percentiles(self._serialization_ms),
            "action_serialization_ms": self._percentiles(self._action_serialization_ms),
            "meter_serialization_ms": self._percentiles(self._meter_serialization_ms),
            "action_payload_bytes": self._percentiles(self._action_payload_bytes),
            "meter_payload_bytes": self._percentiles(self._meter_payload_bytes),
            "packet_to_action_event_ms": self._percentiles(self._packet_to_action_event_ms),
            "event_to_sse_yield_ms": self._percentiles(self._event_to_sse_yield_ms),
            "sse_frame_bytes": self._percentiles(self._sse_frame_bytes),
            "sse_resyncs": self._sse_resyncs,
            "sse_full_resyncs": self._sse_full_resyncs,
            "sse_coalesced_events": self._sse_coalesced_events,
            "http_serves": self._http_serves,
            "feed_cache_builds": self._publisher_metrics.get("feed_serializations", 0),
            "feed_cache_reuses": self._publisher_metrics.get("feed_reuses", 0),
            "feed_cache_entries": self._publisher_metrics.get("feed_count", 0),
            **dict(self._publisher_metrics),
        }

    @staticmethod
    def _provider_readiness(value: Any, error: str | None) -> dict[str, Any]:
        if error is not None or value is None:
            return {"status": "UNAVAILABLE", "flow_pulse_ready": False}
        if not isinstance(value, Mapping):
            return {"status": "AVAILABLE", "flow_pulse_ready": False}
        status = str(value.get("status") or "AVAILABLE").upper()
        return {"status": status, "flow_pulse_ready": bool(value.get("flow_pulse"))}

    @staticmethod
    def _percentiles(values: deque[float]) -> dict[str, float | int | None]:
        ordered = sorted(values)
        if not ordered:
            return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}

        def pick(value: float) -> float:
            return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * value))], 3)

        return {
            "count": len(ordered),
            "p50": pick(0.5),
            "p95": pick(0.95),
            "p99": pick(0.99),
            "max": round(ordered[-1], 3),
        }

    @classmethod
    def _feed(cls, name: str, value: Any, error: str | None) -> dict[str, Any]:
        return wrap_provider_feed(name, value, error)

    @staticmethod
    def _timestamp(value: Any) -> str | None:
        if not isinstance(value, Mapping):
            return None
        for key in (
            "source_event_time",
            "source_timestamp",
            "observed_at",
            "generated_at",
            "generated_timestamp",
            "updated_at",
            "calculated_at",
        ):
            if value.get(key):
                return str(value[key])
        data = value.get("data")
        if isinstance(data, Mapping):
            tactical = data.get("tactical_edge")
            if isinstance(tactical, Mapping):
                return OracleFastLane._timestamp(tactical)
        return None

    @staticmethod
    def _revision(value: Any, error: str | None) -> str:
        if error is not None:
            return f"error:{error}"
        if not isinstance(value, Mapping):
            return repr(value)
        candidates: list[Any] = [value.get("status")]
        for key in (
            "content_hash",
            "event_id",
            "snapshot_id",
            "calculation_id",
            "forecast_revision",
            "source_event_time",
            "source_timestamp",
            "generated_at",
            "updated_at",
            "observed_at",
            "revision",
        ):
            candidates.append(value.get(key))
        meta = value.get("meta")
        if isinstance(meta, Mapping):
            candidates.extend(meta.get(key) for key in ("source_timestamp", "last_updated", "revision"))
        forming = value.get("forming_candle")
        if isinstance(forming, Mapping):
            candidates.extend(
                forming.get(key) for key in ("timestamp", "open", "high", "low", "close", "volume")
            )
        data = value.get("data")
        if isinstance(data, Mapping):
            candidates.extend(data.get(key) for key in ("revision", "generated_at", "updated_at", "source_timestamp"))
            tactical = data.get("tactical_edge")
            candidates.append(
                tactical.get("calculation_id") if isinstance(tactical, Mapping) else None
            )
        flow_pulse = value.get("flow_pulse")
        if isinstance(flow_pulse, Mapping):
            candidates.extend(
                flow_pulse.get(key)
                for key in ("revision", "semantic_revision", "source_timestamp", "snapshot_id")
            )
        transport = value.get("transport")
        if isinstance(transport, Mapping):
            candidates.extend(
                transport.get(key)
                for key in (
                    "SUBSCRIPTION_REVISION",
                    "SENT_SUBSCRIPTION_REVISION",
                    "FEED_GENERATION",
                    "LAST_ANY_PACKET_TS",
                    "BASKET_HEALTH",
                    "EXPECTED_INSTRUMENTS",
                    "REQUESTED_INSTRUMENTS",
                    "FRESH_INSTRUMENTS",
                )
            )
        return "|".join("" if item is None else str(item) for item in candidates)
