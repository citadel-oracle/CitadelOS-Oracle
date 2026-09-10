"""Bounded asynchronous evidence persistence kept off the packet path."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import queue
import threading
import tempfile
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, monotonic_ns
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.broker.dhan_time import normalize_dhan_ltt

from src.strategy_lab.storage import ImmutableStream
from .contracts import InstrumentIdentity


IST = ZoneInfo("Asia/Kolkata")


class OrderFlowEvidenceRecorder:
    """One bounded writer for projections, episodes, and raw Full packets."""

    def __init__(
        self,
        root: str | Path,
        *,
        queue_size: int = 16_384,
        batch_size: int = 1_024,
        coalesce_ms: float = 100.0,
    ):
        root = Path(root)
        self.root = root
        self.projections = ImmutableStream(root / "projections.jsonl", max_bytes=250 * 1024 * 1024, max_files=2)
        self.episodes = ImmutableStream(root / "episodes.jsonl", max_bytes=100 * 1024 * 1024, max_files=2)
        self.gaps = ImmutableStream(root / "recorder_gaps.jsonl", max_bytes=10 * 1024 * 1024, max_files=2)
        # Delivery semantics are intentionally explicit.  Raw Full packets and
        # transport evidence are lossless research inputs; derived projection
        # records are useful but must never occupy the raw lane's capacity.
        self._queue: queue.Queue[tuple[str, Mapping[str, Any], str, int]] = queue.Queue(maxsize=queue_size)
        self._raw_queue: queue.Queue[tuple[str, Mapping[str, Any], str, int]] = queue.Queue(maxsize=queue_size)
        self._raw_streams: dict[str, ImmutableStream] = {}
        self._transport_streams: dict[str, ImmutableStream] = {}
        self._paper_streams: dict[str, ImmutableStream] = {}
        # Fusion remains on this one bounded recorder worker; it never owns a
        # second journal thread.
        self._fusion_streams: dict[str, ImmutableStream] = {}
        paper_root = root / "flow_pulse_paper_sessions"
        self._paper_session_ids = {
            path.stem for path in paper_root.glob("*.jsonl")
        } if paper_root.exists() else set()
        self._identities: dict[str, InstrumentIdentity] = {}
        self._identity_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status = "READY"
        self.enqueued = 0
        self.dropped = 0
        self.written = 0
        self.raw_enqueued = 0
        self.raw_dropped = 0
        self.raw_queue_high_water = 0
        self.raw_written = 0
        self.transport_written = 0
        self.max_queue_depth = 0
        self._in_flight = 0
        self._accounting_lock = threading.RLock()
        # Metrics are observed by Fast Lane/health threads while the recorder
        # worker appends to bounded deques.  Every deque snapshot and mutation
        # must share this lock; iterating a live deque caused the 12-Aug crash.
        self._metrics_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._fsync_count = 0
        self._durable_write_completions = 0
        self._serialization_ms: deque[float] = deque(maxlen=512)
        self._write_ms: deque[float] = deque(maxlen=512)
        self._receive_to_enqueue_ms: deque[float] = deque(maxlen=512)
        self._queue_wait_ms: deque[float] = deque(maxlen=512)
        self._receive_to_durable_ms: deque[float] = deque(maxlen=512)
        self._last_metrics_persist_ns = 0
        self._metrics_path = root / "recorder_health.json"
        self._write_lag_ms: deque[float] = deque(maxlen=512)
        self._batch_sizes: deque[int] = deque(maxlen=512)
        self._batch_targets: deque[int] = deque(maxlen=512)
        self._batch_write_ms: deque[float] = deque(maxlen=512)
        self._batch_size = max(1, int(batch_size))
        self._coalesce_seconds = max(0.0, float(coalesce_ms) / 1_000.0)
        self._submitted_at: deque[int] = deque(maxlen=32_768)
        self._written_at: deque[int] = deque(maxlen=32_768)
        self._started_at_ns: int | None = None
        self._first_written_at_ns: int | None = None
        self._last_successful_write_at: str | None = None
        self._last_flush_at: str | None = None
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._worker_failed = False
        self._bytes_written = 0
        self._integrity_rollovers: list[dict[str, Any]] = []

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        with self._state_lock:
            self._worker_failed = False
            self._last_error = None
            self._last_error_at = None
            self.status = "READY"
        self._started_at_ns = monotonic_ns()
        self._first_written_at_ns = None
        self._thread = threading.Thread(target=self._run, name="order-flow-recorder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._persist_metrics(force=True)

    def submit(self, event_type: str, payload: Mapping[str, Any], key: str) -> bool:
        """Submit a derived record without consuming raw-evidence capacity."""

        return self._submit(event_type, payload, key, raw=False)

    def _submit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        key: str,
        *,
        raw: bool,
    ) -> bool:
        queued_at = monotonic_ns()
        target = self._raw_queue if raw else self._queue
        with self._accounting_lock:
            self.enqueued += 1
            if raw:
                self.raw_enqueued += 1
        try:
            target.put_nowait((event_type, payload, key, queued_at))
            with self._metrics_lock:
                self._submitted_at.append(queued_at)
                receive_ns = int(payload.get("feed_receive_monotonic_ns") or payload.get("packet_receive_ns") or 0)
                if receive_ns > 0:
                    self._receive_to_enqueue_ms.append(max(0.0, (queued_at - receive_ns) / 1_000_000.0))
                total_depth = self._queue.qsize() + self._raw_queue.qsize()
                self.max_queue_depth = max(self.max_queue_depth, total_depth)
                if raw:
                    self.raw_queue_high_water = max(self.raw_queue_high_water, self._raw_queue.qsize())
            return True
        except queue.Full:
            with self._accounting_lock:
                self.dropped += 1
                if raw:
                    self.raw_dropped += 1
            with self._state_lock:
                self.status = "DEGRADED_RAW_QUEUE_FULL" if raw else "DEGRADED_QUEUE_FULL"
            return False

    def register_instruments(self, identities: tuple[InstrumentIdentity, ...]) -> None:
        """Replace the recorder basket with the same canonical identities as P2."""
        with self._identity_lock:
            self._identities = {item.security_id: item for item in identities}

    def submit_full_packet(self, tick: Mapping[str, Any]) -> bool:
        """Queue one decoded official Full packet without touching Flow semantics."""
        if int(tick.get("response_code") or tick.get("feed_code") or 0) != 8:
            return False
        security_id = str(tick.get("security_id") or "")
        with self._identity_lock:
            identity = self._identities.get(security_id)
        if identity is None:
            return False
        receive_wall = str(tick.get("receive_wall_utc") or "")
        ltt = int(tick.get("ltt") or 0)
        session_id = _session_id(ltt, receive_wall)
        fingerprint = str(tick.get("packet_fingerprint") or "")
        generation = int(tick.get("feed_generation") or 0)
        cumulative_volume = int(tick.get("cumulative_volume") or 0)
        event_seed = (
            f"{session_id}|{generation}|{identity.exchange_segment}|{security_id}|"
            f"{ltt}|{cumulative_volume}|{fingerprint}"
        )
        event_id = "raw_of_" + hashlib.sha256(event_seed.encode()).hexdigest()[:28]
        payload = {
            "schema_version": 1,
            "session_id": session_id,
            "event_id": event_id,
            "feed_generation": generation,
            "exchange_segment": identity.exchange_segment,
            "security_id": security_id,
            "instrument_role": identity.role,
            "expiry": identity.expiry,
            "strike": identity.strike,
            "option_type": identity.option_type,
            "packet_fingerprint": fingerprint,
            "exchange_ltt": ltt,
            "ltt_raw_epoch": tick.get("ltt_raw_epoch", ltt),
            "ltt_raw_utc": tick.get("ltt_raw_utc"),
            "ltt_raw_ist": tick.get("ltt_raw_ist"),
            "ltt_normalized_epoch": tick.get("ltt_normalized_epoch"),
            "ltt_utc": tick.get("ltt_utc"),
            "ltt_ist": tick.get("ltt_ist"),
            "receive_time_ist": tick.get("receive_time_ist"),
            "ltt_raw_receive_skew_ms": tick.get("ltt_raw_receive_skew_ms"),
            "ltt_receive_skew_ms": tick.get("ltt_receive_skew_ms"),
            "ltt_session_accepted": tick.get("ltt_session_accepted"),
            "ltt_event_session_accepted": tick.get("ltt_event_session_accepted"),
            "DHAN_LTT_RAW_SUSPICIOUS": tick.get("DHAN_LTT_RAW_SUSPICIOUS", False),
            "DHAN_LTT_RECEIVE_TIME_SUBSTITUTED": tick.get("DHAN_LTT_RECEIVE_TIME_SUBSTITUTED", False),
            "receive_wall_utc": receive_wall,
            "feed_receive_monotonic_ns": int(tick.get("feed_receive_ns") or 0),
            "decode_done_monotonic_ns": int(tick.get("decode_done_ns") or 0),
            "gateway_queue_lag_ns": int(tick.get("gateway_queue_lag_ns") or 0),
            "ltp": tick.get("ltp"),
            "ltq": tick.get("ltq"),
            "cumulative_volume": tick.get("cumulative_volume"),
            "atp": tick.get("atp"),
            "open_interest": tick.get("open_interest"),
            "high_open_interest": tick.get("high_open_interest"),
            "low_open_interest": tick.get("low_open_interest"),
            "total_buy_quantity": tick.get("total_buy_quantity"),
            "total_sell_quantity": tick.get("total_sell_quantity"),
            "depth_5": [dict(level) for level in tick.get("depth_5") or ()],
            "transport_gap_count": int(tick.get("transport_gap_count") or 0),
        }
        return self._submit("RAW_FULL_PACKET", payload, event_id, raw=True)

    def submit_transport_event(self, event_type: str, payload: Mapping[str, Any]) -> bool:
        """Record reconnect/gap/reset lifecycle evidence on the same async queue."""
        receive_wall = str(payload.get("receive_wall_utc") or datetime.now(timezone.utc).isoformat())
        session_id = _session_id(0, receive_wall)
        safe_payload = {
            "schema_version": 1,
            "session_id": session_id,
            "event_type": event_type,
            "feed_generation": int(payload.get("feed_generation") or 0),
            "subscription_revision": int(payload.get("subscription_revision") or 0),
            "transport_gap_count": int(payload.get("transport_gap_count") or 0),
            "instrument_count": int(payload.get("instrument_count") or 0),
            "receive_wall_utc": receive_wall,
            "reason": payload.get("reason"),
        }
        seed = "|".join(str(safe_payload[key]) for key in sorted(safe_payload))
        event_id = "transport_" + hashlib.sha256(seed.encode()).hexdigest()[:28]
        safe_payload["event_id"] = event_id
        return self._submit("TRANSPORT_EVENT", safe_payload, event_id, raw=True)

    def health(self) -> dict[str, Any]:
        now_ns = monotonic_ns()
        cutoff_ns = now_ns - 10_000_000_000
        with self._metrics_lock:
            submitted = tuple(self._submitted_at)
            written_at = tuple(self._written_at)
            batch_sizes = sorted(self._batch_sizes)
            batch_write_ms = sorted(self._batch_write_ms)
            receive_to_enqueue = tuple(self._receive_to_enqueue_ms)
            queue_wait = tuple(self._queue_wait_ms)
            serialization = tuple(self._serialization_ms)
            write = tuple(self._write_ms)
            receive_to_durable = tuple(self._receive_to_durable_ms)
            write_lag = tuple(self._write_lag_ms)
            max_queue_depth = self.max_queue_depth
            fsync_count = self._fsync_count
            durable_completions = self._durable_write_completions
            raw_written = self.raw_written
            transport_written = self.transport_written
            bytes_written = self._bytes_written
            first_written_at_ns = self._first_written_at_ns
        producer_rate = sum(value >= cutoff_ns for value in submitted) / 10.0
        writer_rate = sum(value >= cutoff_ns for value in written_at) / 10.0
        with self._queue.mutex:
            oldest_derived = self._queue.queue[0][3] if self._queue.queue else None
        with self._raw_queue.mutex:
            oldest_raw = self._raw_queue.queue[0][3] if self._raw_queue.queue else None
        with self._accounting_lock:
            enqueued, written, dropped, in_flight = self.enqueued, self.written, self.dropped, self._in_flight
            raw_enqueued, raw_dropped = self.raw_enqueued, self.raw_dropped
        with self._state_lock:
            status = self.status
            last_write_at = self._last_successful_write_at
            last_flush_at = self._last_flush_at
            last_error = self._last_error
            last_error_at = self._last_error_at
            worker_failed = self._worker_failed
        with self._identity_lock:
            registered_instruments = len(self._identities)
        with self._state_lock:
            raw_streams = dict(self._raw_streams)
            paper_sessions = len(self._paper_session_ids)
            integrity_rollovers = tuple(self._integrity_rollovers)
        derived_queued = self._queue.qsize()
        raw_queued = self._raw_queue.qsize()
        queued = derived_queued + raw_queued
        worker_alive = bool(self._thread is not None and self._thread.is_alive()) and not worker_failed
        last_write_age_ms = _timestamp_age_ms(last_write_at)
        return {
            "metrics_schema": "ORDER_FLOW_RECORDER_METRICS_V2",
            "status": status,
            "RECORDER_ALIVE": worker_alive,
            "RECORDER_QUEUE_DEPTH": queued,
            "RECORDER_QUEUE_CAPACITY": self._queue.maxsize + self._raw_queue.maxsize,
            "RECORDER_QUEUE_HIGH_WATER": max_queue_depth,
            "RECORDER_DROPS": dropped,
            "RECORDER_RAW_DROPS": raw_dropped,
            "RECORDER_RAW_QUEUE_DEPTH": raw_queued,
            "RECORDER_RAW_QUEUE_CAPACITY": self._raw_queue.maxsize,
            "RECORDER_RAW_QUEUE_HIGH_WATER": self.raw_queue_high_water,
            "RECORDER_DERIVED_QUEUE_DEPTH": derived_queued,
            "RECORDER_DERIVED_QUEUE_CAPACITY": self._queue.maxsize,
            "RECORDER_LAST_WRITE_AGE": last_write_age_ms,
            "RECORDER_LAST_ERROR": last_error,
            "worker_alive": worker_alive,
            "worker_failed": worker_failed,
            "worker_last_error": last_error,
            "worker_last_error_at": last_error_at,
            "last_successful_write_at": last_write_at,
            "last_flush_at": last_flush_at,
            "last_write_age_ms": last_write_age_ms,
            "bytes_written": bytes_written,
            "enqueue_count": enqueued,
            "write_count": written,
            "queue_depth": queued,
            "raw_queue_depth": raw_queued,
            "derived_queue_depth": derived_queued,
            "raw_enqueued": raw_enqueued,
            "raw_dropped": raw_dropped,
            "in_flight": in_flight,
            "dropped_count": dropped,
            "dropped": dropped,
            "written": written,
            "accounting_identity": "ENQUEUED = WRITTEN + QUEUED + IN_FLIGHT + DROPPED",
            "accounting_valid": enqueued == written + queued + in_flight + dropped,
            "raw_written": raw_written,
            "transport_written": transport_written,
            "max_queue_depth": max_queue_depth,
            "write_lag_ms": (
                round(max(write_lag), 3) if write_lag else 0.0
            ),
            "capture_output": str(self.root / "raw_full_packets" / "YYYY-MM-DD.jsonl"),
            "registered_instruments": registered_instruments,
            "paper_sessions": paper_sessions,
            "integrity_rollovers": integrity_rollovers,
            "producer_rate_per_s": round(producer_rate, 3),
            "writer_rate_per_s": round(writer_rate, 3),
            "batching": {
                "max_age_ms": round(self._coalesce_seconds * 1_000.0, 3),
                "last_size": batch_sizes[-1] if batch_sizes else 0,
                "last_target": self._last_batch_target(),
                "p50_size": _percentile(batch_sizes, 0.50),
                "p95_size": _percentile(batch_sizes, 0.95),
                "p95_write_ms": _percentile(batch_write_ms, 0.95),
            },
            "persistence_latency_ms": {
                "receive_to_enqueue": _distribution(receive_to_enqueue),
                "queue_wait": _distribution(queue_wait),
                "serialization": _distribution(serialization),
                "write": _distribution(write),
                "receive_to_durable": _distribution(receive_to_durable),
            },
            "fsync_count": fsync_count,
            "durable_write_completions": durable_completions,
            "oldest_queue_age_ms": _queue_age_ms(now_ns, oldest_derived, oldest_raw),
            "raw_oldest_queue_age_ms": _queue_age_ms(now_ns, oldest_raw),
            "derived_oldest_queue_age_ms": _queue_age_ms(now_ns, oldest_derived),
            "start_to_first_record_ms": (
                round(
                    (first_written_at_ns - self._started_at_ns) / 1_000_000.0,
                    3,
                )
                if self._started_at_ns is not None and first_written_at_ns is not None
                else None
            ),
            "stream_resume": {
                "projections": self.projections.resume_metrics(),
                "episodes": self.episodes.resume_metrics(),
                **{
                    f"raw:{session_id}": stream.resume_metrics()
                    for session_id, stream in sorted(raw_streams.items())
                },
            },
        }

    def _last_batch_target(self) -> int:
        with self._metrics_lock:
            return self._batch_targets[-1] if self._batch_targets else 0

    def paper_sessions(self) -> list[str]:
        with self._state_lock:
            return sorted(self._paper_session_ids, reverse=True)

    def read_paper_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._state_lock:
            known = session_id in self._paper_session_ids
        if not known:
            return []
        with self._state_lock:
            stream = self._paper_streams.setdefault(
                session_id,
                ImmutableStream(
                    self.root / "flow_pulse_paper_sessions" / f"{session_id}.jsonl",
                    max_bytes=20 * 1024 * 1024,
                    max_files=1,
                ),
            )
        latest: dict[str, dict[str, Any]] = {}
        for row in stream.read():
            payload = row.get("payload") if isinstance(row, Mapping) else None
            if isinstance(payload, Mapping) and payload.get("trade_id"):
                latest[str(payload["trade_id"])] = dict(payload)
        return sorted(latest.values(), key=lambda row: (str(row.get("entry_time")), str(row.get("trade_id"))))

    def fusion_sessions(self) -> list[str]:
        root = self.root / "fusion_shadow"
        if not root.exists():
            return []
        return sorted((path.stem for path in root.glob("*.jsonl")), reverse=True)

    def read_fusion_session(self, session_id: str) -> list[dict[str, Any]]:
        """Read the additive Fusion ledger; never mutates live engine state."""
        if session_id not in self.fusion_sessions():
            return []
        with self._state_lock:
            stream = self._fusion_streams.setdefault(
                session_id,
                ImmutableStream(
                    self.root / "fusion_shadow" / f"{session_id}.jsonl",
                    max_bytes=100 * 1024 * 1024,
                    max_files=2,
                ),
            )
        rows: list[dict[str, Any]] = []
        for row in stream.read():
            payload = row.get("payload") if isinstance(row, Mapping) else None
            if isinstance(payload, Mapping):
                rows.append(dict(payload))
        return rows

    def _run(self) -> None:
        """Contain all worker failures so a dead writer is always observable."""
        try:
            self._run_loop()
        except Exception as error:
            self._record_worker_error(error, fatal=True)
        finally:
            try:
                self._persist_metrics(force=True)
            except Exception as error:
                self._record_worker_error(error, fatal=True)

    def _run_loop(self) -> None:
        while not self._stop.is_set() or not self._raw_queue.empty() or not self._queue.empty():
            try:
                first = self._raw_queue.get_nowait()
                first_source = self._raw_queue
            except queue.Empty:
                try:
                    first = self._queue.get(timeout=0.1)
                    first_source = self._queue
                except queue.Empty:
                    continue
            batch = [(first_source, *first)]
            with self._accounting_lock:
                self._in_flight += 1
            deadline = monotonic() + self._coalesce_seconds
            # Flush on configured size or bounded oldest-record age. Reducing
            # the target to instantaneous queue depth turns a 1,024-record
            # writer into tiny fsync-heavy writes while a burst is still
            # arriving, allowing backlog to snowball.
            target_batch_size = self._batch_size
            with self._metrics_lock:
                self._batch_targets.append(target_batch_size)
            while len(batch) < target_batch_size:
                try:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        break
                    try:
                        item = self._raw_queue.get_nowait()
                        source = self._raw_queue
                    except queue.Empty:
                        item = self._queue.get(timeout=remaining)
                        source = self._queue
                    batch.append((source, *item))
                    with self._accounting_lock:
                        self._in_flight += 1
                except queue.Empty:
                    break
            with self._metrics_lock:
                self._batch_sizes.append(len(batch))
            batch_started_ns = monotonic_ns()
            groups: dict[ImmutableStream, list[tuple[str, Mapping[str, Any], str, int]]] = defaultdict(list)
            for _, event_type, payload, key, queued_at in batch:
                groups[self._stream(event_type, payload)].append(
                    (event_type, payload, key, queued_at)
                )
            batch_written = 0
            try:
                for stream, items in groups.items():
                    dequeue_ns = monotonic_ns()
                    for _, _, _, queued_at in items:
                        with self._metrics_lock:
                            self._queue_wait_ms.append(max(0.0, (dequeue_ns - queued_at) / 1_000_000.0))
                    before_bytes = stream.path.stat().st_size if stream.path.exists() else 0
                    batch_records = [
                        (event_type, payload, None, key)
                        for event_type, payload, key, _ in items
                    ]
                    try:
                        stream.append_batch(batch_records, return_rows=False)
                    except RuntimeError as error:
                        if "HASH_CHAIN_INVALID" not in str(error):
                            raise
                        rollover_at = datetime.now(timezone.utc)
                        quarantined = stream.quarantine_corrupted_segment(
                            suffix=rollover_at.strftime("%Y%m%dT%H%M%S%fZ")
                        )
                        rollover = {
                            "event_type": "STREAM_INTEGRITY_ROLLOVER",
                            "at_utc": rollover_at.isoformat(),
                            "active_path": str(stream.path),
                            "quarantined_path": str(quarantined),
                            "original_preserved": True,
                            "reason": "HASH_CHAIN_INVALID",
                        }
                        with self._state_lock:
                            self._integrity_rollovers.append(rollover)
                        self.gaps.append(
                            "ORDER_FLOW_STREAM_INTEGRITY_ROLLOVER",
                            rollover,
                            idempotency_key=f"rollover:{quarantined.name}",
                        )
                        stream.append_batch(batch_records, return_rows=False)
                    after_bytes = stream.path.stat().st_size if stream.path.exists() else before_bytes
                    append_metrics = stream.append_metrics()
                    with self._metrics_lock:
                        self._serialization_ms.append(float(append_metrics.get("serialization_ms") or 0.0))
                        self._write_ms.append(float(append_metrics.get("write_ms") or 0.0))
                        self._fsync_count += int(append_metrics.get("fsync_count") or 0)
                        self._durable_write_completions += 1
                        self._bytes_written += max(0, after_bytes - before_bytes)
                    durable_ns = int(append_metrics.get("durable_complete_ns") or monotonic_ns())
                    for event_type, payload, _, queued_at in items:
                        with self._accounting_lock:
                            self.written += 1
                        batch_written += 1
                        receive_ns = int(payload.get("feed_receive_monotonic_ns") or payload.get("packet_receive_ns") or 0)
                        if receive_ns > 0:
                            with self._metrics_lock:
                                self._receive_to_durable_ms.append(max(0.0, (durable_ns - receive_ns) / 1_000_000.0))
                        with self._metrics_lock:
                            self._write_lag_ms.append(max(0.0, (monotonic_ns() - queued_at) / 1_000_000.0))
                            self._written_at.append(monotonic_ns())
                            if self._first_written_at_ns is None:
                                self._first_written_at_ns = monotonic_ns()
                            if event_type == "RAW_FULL_PACKET":
                                self.raw_written += 1
                            elif event_type == "TRANSPORT_EVENT":
                                self.transport_written += 1
                    with self._state_lock:
                        self._last_successful_write_at = datetime.now(timezone.utc).isoformat()
                        self._last_flush_at = self._last_successful_write_at
                with self._state_lock:
                    if self.status == "READY" or self._queue.qsize() < self._queue.maxsize // 2:
                        self.status = "READY"
            except Exception as error:
                self._record_worker_error(error, fatal=False)
                with self._accounting_lock:
                    self.dropped += len(batch) - batch_written
                for _, event_type, _, key, _ in batch:
                    try:
                        self.gaps.append(
                            "ORDER_FLOW_RESEARCH_GAP",
                            {"event_type": event_type, "idempotency_key": key, "reason": type(error).__name__},
                            idempotency_key=f"gap:{key}",
                        )
                    except Exception:
                        pass
            finally:
                with self._metrics_lock:
                    self._batch_write_ms.append(max(0.0, (monotonic_ns() - batch_started_ns) / 1_000_000.0))
                for source, *_ in batch:
                    source.task_done()
                with self._accounting_lock:
                    self._in_flight -= len(batch)
                try:
                    self._persist_metrics()
                except Exception as error:
                    # Health-file persistence cannot be allowed to kill the
                    # authoritative journal writer.  Surface it and continue.
                    self._record_worker_error(error, fatal=False)

    def _persist_metrics(self, *, force: bool = False) -> None:
        now_ns = monotonic_ns()
        if not force and now_ns - self._last_metrics_persist_ns < 1_000_000_000:
            return
        self._last_metrics_persist_ns = now_ns
        value = self.health()
        self._metrics_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self._metrics_path.name}.", dir=str(self._metrics_path.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._metrics_path)
            _fsync_directory(self._metrics_path.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _record_worker_error(self, error: Exception, *, fatal: bool) -> None:
        with self._state_lock:
            self.status = f"DEGRADED_{type(error).__name__}"
            self._last_error = f"{type(error).__name__}:{error}"
            self._last_error_at = datetime.now(timezone.utc).isoformat()
            self._worker_failed = self._worker_failed or fatal

    def _stream(self, event_type: str, payload: Mapping[str, Any]) -> ImmutableStream:
        if event_type == "RAW_FULL_PACKET":
            session_id = str(payload["session_id"])
            with self._state_lock:
                return self._raw_streams.setdefault(
                    session_id,
                    ImmutableStream(
                        self.root / "raw_full_packets" / f"{session_id}.jsonl",
                        max_bytes=4 * 1024 * 1024 * 1024,
                        max_files=1,
                    ),
                )
        if event_type == "TRANSPORT_EVENT":
            session_id = str(payload["session_id"])
            with self._state_lock:
                return self._transport_streams.setdefault(
                    session_id,
                    ImmutableStream(
                        self.root / "transport_events" / f"{session_id}.jsonl",
                        max_bytes=50 * 1024 * 1024,
                        max_files=2,
                    ),
                )
        if event_type == "FLOW_PULSE_PAPER_SESSION_UPDATE":
            session_id = str(payload["session_id"])
            with self._state_lock:
                self._paper_session_ids.add(session_id)
                return self._paper_streams.setdefault(
                    session_id,
                    ImmutableStream(
                        self.root / "flow_pulse_paper_sessions" / f"{session_id}.jsonl",
                        max_bytes=20 * 1024 * 1024,
                        max_files=1,
                    ),
                )
        if event_type.startswith("ARGUS_FUSION_"):
            session_id = str(
                payload.get("session_id")
                or _session_id(0, str(payload.get("recorded_at") or payload.get("state_timestamp") or ""))
            )
            with self._state_lock:
                return self._fusion_streams.setdefault(
                    session_id,
                    ImmutableStream(
                        self.root / "fusion_shadow" / f"{session_id}.jsonl",
                        max_bytes=100 * 1024 * 1024,
                        max_files=2,
                    ),
                )
        return self.episodes if event_type.startswith("EPISODE") else self.projections


def _session_id(exchange_ltt: int, receive_wall_utc: str) -> str:
    if exchange_ltt > 0:
        return normalize_dhan_ltt(exchange_ltt, receive_wall_utc).ist.date().isoformat()
    try:
        value = datetime.fromisoformat(receive_wall_utc.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        value = datetime.now(timezone.utc)
    return value.astimezone(IST).date().isoformat()


def _timestamp_age_ms(value: str | None) -> float | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
        return round(
            max(
                0.0,
                (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() * 1_000.0,
            ),
            3,
        )
    except (TypeError, ValueError):
        return None


def _queue_age_ms(now_ns: int, *queued_at: int | None) -> float:
    """Return the oldest age across one or more independent bounded lanes."""

    values = [value for value in queued_at if value is not None]
    if not values:
        return 0.0
    return round(max(0.0, (now_ns - min(values)) / 1_000_000.0), 3)


def _fsync_directory(path: Path) -> None:
    """Persist the rename itself where the host filesystem supports it."""
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _percentile(values: list[float] | list[int], fraction: float) -> float | int | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int((len(values) - 1) * fraction)))
    value = values[index]
    return round(value, 3) if isinstance(value, float) else value


def _distribution(values: deque[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
        "max": round(ordered[-1], 3) if ordered else None,
    }
