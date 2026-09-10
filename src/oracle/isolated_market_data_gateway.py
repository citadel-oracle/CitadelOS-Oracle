"""Process-isolated ownership of Oracle's one canonical Dhan WebSocket.

The normal Oracle backend may run CPU-heavy research and presentation work. In
CPython, a separate thread isn't a sufficient boundary when that work holds the
GIL: it can still delay the WebSocket thread's Ping/Pong and recv processing.
This adapter keeps the single socket in a launchd-parented child process and
ships only immutable decoded packets over bounded one-way IPC queues.

It deliberately preserves the existing :class:`MarketDataGateway` decoder,
subscription mechanics and packet-health semantics.  It changes process
ownership and fanout timing only; no analytics are run in the child.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from src.oracle.market_data_gateway import MarketDataGateway
from src.oracle.shared_ipc import SharedFlag, shared_int_slots


_SEGMENT_NAMES = {
    0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 3: "NSE_CURRENCY",
    4: "BSE_EQ", 5: "MCX_COMM", 7: "BSE_CURRENCY", 8: "BSE_FNO",
}


def _segment_key(value: Any) -> str:
    if isinstance(value, int):
        return _SEGMENT_NAMES.get(value, str(value))
    text = str(value)
    try:
        return _SEGMENT_NAMES.get(int(text), text)
    except ValueError:
        return text


def _queue_depth(value: Any) -> int | None:
    try:
        return int(value.qsize())
    except (AttributeError, NotImplementedError, OSError):
        return None


def _replace_latest(target: Any, value: Mapping[str, Any]) -> int:
    """Health is a latest-state channel, so an old sample may be superseded."""

    replaced = 0
    try:
        while True:
            target.get_nowait()
            replaced += 1
    except queue.Empty:
        pass
    try:
        target.put_nowait(dict(value))
    except queue.Full:
        pass
    return replaced


def _isolated_gateway_child(
    client_id: str,
    access_token: str,
    instruments: list[dict[str, Any]],
    commands: Any,
    raw_packets: Any,
    flow_ticks: Any,
    futures_display_ticks: Any,
    transport_events: Any,
    health_samples: Any,
    stop_event: Any,
    raw_ipc_drops: Any,
    flow_ipc_drops: Any,
    transport_ipc_drops: Any,
    futures_display_coalesces: Any,
    raw_ipc_enqueued: Any,
    flow_ipc_enqueued: Any,
    transport_ipc_enqueued: Any,
) -> None:
    """Child target: it owns the only Dhan connection for this backend."""

    ingress_lock = threading.Lock()
    ingress_times: dict[str, deque[int]] = {
        "raw": deque(maxlen=8_192),
        "flow": deque(maxlen=8_192),
        "transport": deque(maxlen=1_024),
    }

    def enqueue(target: Any, payload: Any, counter: Any, enqueued: Any, lane: str) -> bool:
        try:
            target.put_nowait(payload)
            with enqueued.get_lock():
                enqueued.value += 1
            with ingress_lock:
                ingress_times[lane].append(time.perf_counter_ns())
            return True
        except queue.Full:
            with counter.get_lock():
                counter.value += 1
            return False

    def emit_raw(tick: dict[str, Any]) -> None:
        enqueue(raw_packets, dict(tick), raw_ipc_drops, raw_ipc_enqueued, "raw")

    role_by_key = {
        (_segment_key(item.get("exchange_segment")), str(item.get("security_id"))): str(item.get("role") or "")
        for item in instruments
    }

    def update_roles(values: list[dict[str, Any]]) -> None:
        role_by_key.clear()
        role_by_key.update({
            (_segment_key(item.get("exchange_segment")), str(item.get("security_id"))): str(item.get("role") or "")
            for item in values
        })

    def emit_tick(tick: dict[str, Any]) -> None:
        value = dict(tick)
        key = (_segment_key(value.get("exchange_segment")), str(value.get("security_id")))
        role = role_by_key.get(key)
        if role:
            value["instrument_role"] = role
        enqueue(flow_ticks, value, flow_ipc_drops, flow_ipc_enqueued, "flow")
        if role == "NIFTY_FUTURE":
            replaced = _replace_latest(futures_display_ticks, value)
            if replaced:
                with futures_display_coalesces.get_lock():
                    futures_display_coalesces.value += replaced

    def emit_transport(event_type: str, payload: dict[str, Any]) -> None:
        enqueue(
            transport_events,
            (str(event_type), dict(payload)),
            transport_ipc_drops,
            transport_ipc_enqueued,
            "transport",
        )

    gateway = MarketDataGateway(
        client_id=client_id,
        access_token=access_token,
        on_tick=emit_tick,
        on_raw_packet=emit_raw,
        on_transport_event=emit_transport,
        lossless_tick_delivery=True,
    )
    gateway.subscribe(instruments)

    def command_loop() -> None:
        while not stop_event.is_set():
            try:
                command, payload = commands.get(timeout=0.1)
            except queue.Empty:
                continue
            if command == "SUBSCRIBE":
                values = list(payload or ())
                update_roles(values)
                gateway.subscribe(values)
            elif command == "STOP":
                stop_event.set()
                loop = gateway._loop
                if loop is not None and loop.is_running():
                    try:
                        import asyncio
                        asyncio.run_coroutine_threadsafe(gateway.stop(), loop)
                    except Exception:
                        pass
                return

    def health_loop() -> None:
        while not stop_event.is_set():
            snapshot = gateway.health()
            gateway_required_drops = int(snapshot.get("FLOW_REQUIRED_DROPS") or 0)
            total_required_drops = gateway_required_drops + int(flow_ipc_drops.value)
            cutoff = time.perf_counter_ns() - 10_000_000_000
            with ingress_lock:
                ingress_rates = {
                    name: round(sum(value >= cutoff for value in values) / 10.0, 3)
                    for name, values in ingress_times.items()
                }
            snapshot.update(
                {
                    "ISOLATION_TIER": "SEPARATE_PROCESS",
                    "WS_OWNER_COUNT": 1,
                    "RAW_IPC_DROPS": int(raw_ipc_drops.value),
                    "RAW_IPC_ENQUEUED": int(raw_ipc_enqueued.value),
                    # Compatibility preserves the former field, now with an
                    # explicit lossless Flow meaning rather than a cosmetic
                    # analytical bucket.
                    "ANALYTICAL_IPC_DROPS": int(flow_ipc_drops.value),
                    "FLOW_REQUIRED_IPC_DROPS": int(flow_ipc_drops.value),
                    "FLOW_REQUIRED_IPC_ENQUEUED": int(flow_ipc_enqueued.value),
                    "FLOW_REQUIRED_GATEWAY_DROPS": gateway_required_drops,
                    "FLOW_REQUIRED_DROPS": total_required_drops,
                    "TRANSPORT_IPC_DROPS": int(transport_ipc_drops.value),
                    "TRANSPORT_IPC_ENQUEUED": int(transport_ipc_enqueued.value),
                    "RAW_IPC_QUEUE_DEPTH": _queue_depth(raw_packets),
                    "FLOW_REQUIRED_IPC_QUEUE_DEPTH": _queue_depth(flow_ticks),
                    "ANALYTICAL_IPC_QUEUE_DEPTH": _queue_depth(flow_ticks),
                    "FUTURES_DISPLAY_LATEST_QUEUE_DEPTH": _queue_depth(futures_display_ticks),
                    "FUTURES_DISPLAY_COALESCES": int(futures_display_coalesces.value),
                    "IPC_INGRESS_RATE_PER_S": ingress_rates,
                }
            )
            _replace_latest(health_samples, snapshot)
            stop_event.wait(0.25)

    command_thread = threading.Thread(
        target=command_loop,
        name="oracle-dhan-child-commands",
        daemon=True,
    )
    health_thread = threading.Thread(
        target=health_loop,
        name="oracle-dhan-child-health",
        daemon=True,
    )
    command_thread.start()
    health_thread.start()
    try:
        import asyncio
        asyncio.run(gateway.start())
    finally:
        stop_event.set()
        gateway.stop_background()
        command_thread.join(timeout=1.0)
        health_thread.join(timeout=1.0)


class IsolatedMarketDataGateway:
    """Parent-side proxy for a single child-owned canonical Dhan gateway."""

    def __init__(
        self,
        client_id: str | None = None,
        access_token: str | None = None,
        on_tick: Callable[[dict[str, Any]], Any] | None = None,
        on_latest_futures_tick: Callable[[dict[str, Any]], Any] | None = None,
        on_raw_packet: Callable[[dict[str, Any]], Any] | None = None,
        on_transport_event: Callable[[str, dict[str, Any]], Any] | None = None,
        queue_size: int = 2_048,
    ) -> None:
        import os

        self.client_id = client_id or os.getenv("DHAN_CLIENT_ID", "")
        self.access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN", "")
        self.on_tick = on_tick
        self.on_latest_futures_tick = on_latest_futures_tick
        self.on_raw_packet = on_raw_packet
        self.on_transport_event = on_transport_event
        self.instruments: list[dict[str, Any]] = []
        self._subscription_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._ctx = mp.get_context("spawn")
        capacity = max(16, int(queue_size))
        self._commands = self._ctx.Queue(maxsize=128)
        # Raw evidence is deliberately deeper than the lossless Flow lane.
        # It is never coalesced; a full queue is explicit health degradation.
        # macOS named-semaphore limits prohibit an enormous Queue maxsize;
        # 32k is still materially deeper than the analytical lane and keeps
        # raw evidence pressure explicit rather than pretending it is infinite.
        self._raw_packets = self._ctx.Queue(maxsize=min(32_760, max(16_384, capacity * 8)))
        # Every Full packet is required by Order Flow.  This queue is not a
        # display coalescer: exhaustion is an explicit required-event loss.
        self._flow_ticks = self._ctx.Queue(maxsize=capacity)
        # Legacy test/diagnostic alias retained without changing its meaning.
        self._analytical_ticks = self._flow_ticks
        self._futures_display_ticks = self._ctx.Queue(maxsize=1)
        self._transport_events = self._ctx.Queue(maxsize=4_096)
        self._health_samples = self._ctx.Queue(maxsize=1)
        self._ipc_state, ipc_slots = shared_int_slots(self._ctx, 8)
        (
            self._raw_ipc_drops,
            self._flow_ipc_drops,
            self._transport_ipc_drops,
            self._futures_display_coalesces,
            self._raw_ipc_enqueued,
            self._flow_ipc_enqueued,
            self._transport_ipc_enqueued,
            _stop_slot,
        ) = ipc_slots
        self._stop_event = SharedFlag(self._ipc_state, 7)
        self._process: mp.Process | None = None
        self._raw_thread: threading.Thread | None = None
        self._tick_thread: threading.Thread | None = None
        self._futures_display_thread: threading.Thread | None = None
        self._transport_thread: threading.Thread | None = None
        self._parent_stop = threading.Event()
        self._health: dict[str, Any] = {
            "status": "DOWN",
            "WS_CONNECTED": False,
            "DHAN_CONNECTION_STATE": "DISCONNECTED",
            "CONNECTION_GENERATION": 0,
            "ISOLATION_TIER": "SEPARATE_PROCESS",
            "WS_OWNER_COUNT": 0,
        }
        self._parent_callback_failures = {"raw": 0, "tick": 0, "futures_display": 0, "transport": 0}
        self._parent_metrics_lock = threading.RLock()
        self._parent_counts = {"raw": 0, "tick": 0, "futures_display": 0, "transport": 0}
        self._parent_queue_wait_ms = {name: deque(maxlen=2_048) for name in self._parent_counts}
        self._parent_callback_ms = {name: deque(maxlen=2_048) for name in self._parent_counts}
        self._parent_dispatch_times = {name: deque(maxlen=8_192) for name in self._parent_counts}

    def subscribe(self, instruments: list[dict[str, Any]]) -> None:
        canonical = {
            (str(row.get("exchange_segment")), str(row.get("security_id"))): dict(row)
            for row in instruments
            if row.get("security_id") is not None
        }
        values = [canonical[key] for key in sorted(canonical)]
        with self._subscription_lock:
            if values == self.instruments:
                return
            self.instruments = values
        if self._child_alive():
            try:
                self._commands.put_nowait(("SUBSCRIBE", values))
            except queue.Full:
                with self._state_lock:
                    self._health["SUBSCRIPTION_COMMAND_STATUS"] = "DEGRADED_QUEUE_FULL"

    def start_background(self) -> None:
        if self._child_alive():
            return
        with self._subscription_lock:
            instruments = [dict(row) for row in self.instruments]
        self._parent_stop.clear()
        self._stop_event.clear()
        self._process = self._ctx.Process(
            target=_isolated_gateway_child,
            args=(
                self.client_id, self.access_token, instruments, self._commands,
                self._raw_packets, self._flow_ticks, self._futures_display_ticks,
                self._transport_events, self._health_samples, self._stop_event,
                self._raw_ipc_drops, self._flow_ipc_drops, self._transport_ipc_drops,
                self._futures_display_coalesces, self._raw_ipc_enqueued,
                self._flow_ipc_enqueued, self._transport_ipc_enqueued,
            ),
            name="oracle-dhan-market-data",
            daemon=True,
        )
        self._process.start()
        self._start_parent_dispatch()

    def stop_background(self) -> None:
        self._parent_stop.set()
        self._stop_event.set()
        if self._child_alive():
            try:
                self._commands.put_nowait(("STOP", None))
            except queue.Full:
                pass
            assert self._process is not None
            self._process.join(timeout=3.0)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2.0)
        for thread in (self._raw_thread, self._tick_thread, self._futures_display_thread, self._transport_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1.0)

    def _child_alive(self) -> bool:
        return bool(self._process is not None and self._process.is_alive())

    def _start_parent_dispatch(self) -> None:
        for name, target in (
            ("raw", self._dispatch_raw),
            ("tick", self._dispatch_tick),
            ("futures_display", self._dispatch_futures_display),
            ("transport", self._dispatch_transport),
        ):
            thread = threading.Thread(
                target=target,
                name=f"oracle-dhan-parent-{name}",
                daemon=True,
            )
            setattr(self, f"_{name}_thread", thread)
            thread.start()

    def _dispatch_raw(self) -> None:
        self._dispatch_loop(self._raw_packets, "raw")

    def _dispatch_tick(self) -> None:
        self._dispatch_loop(self._flow_ticks, "tick")

    def _dispatch_futures_display(self) -> None:
        self._dispatch_loop(self._futures_display_ticks, "futures_display")

    def _dispatch_transport(self) -> None:
        self._dispatch_loop(self._transport_events, "transport")

    def _dispatch_loop(self, source: Any, kind: str) -> None:
        while not self._parent_stop.is_set() or _queue_depth(source) not in {0, None}:
            try:
                payload = source.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                started_ns = time.perf_counter_ns()
                if isinstance(payload, Mapping):
                    decode_ns = int(payload.get("decode_done_ns") or 0)
                    if decode_ns > 0:
                        with self._parent_metrics_lock:
                            self._parent_queue_wait_ms[kind].append(
                                max(0.0, (started_ns - decode_ns) / 1_000_000.0)
                            )
                if kind == "raw" and self.on_raw_packet is not None:
                    self.on_raw_packet(payload)
                elif kind == "tick" and self.on_tick is not None:
                    self.on_tick(payload)
                elif kind == "futures_display" and self.on_latest_futures_tick is not None:
                    self.on_latest_futures_tick(payload)
                elif kind == "transport" and self.on_transport_event is not None:
                    event_type, event_payload = payload
                    self.on_transport_event(event_type, event_payload)
            except Exception:
                with self._state_lock:
                    self._parent_callback_failures[kind] += 1
            finally:
                with self._parent_metrics_lock:
                    self._parent_counts[kind] += 1
                    self._parent_dispatch_times[kind].append(time.perf_counter_ns())
                    self._parent_callback_ms[kind].append(
                        max(0.0, (time.perf_counter_ns() - started_ns) / 1_000_000.0)
                    )

    def _drain_health(self) -> None:
        latest: dict[str, Any] | None = None
        try:
            while True:
                latest = self._health_samples.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            with self._state_lock:
                self._health = dict(latest)

    def health(self) -> dict[str, Any]:
        """A local cache read; it never waits on child IPC or Dhan."""

        self._drain_health()
        with self._state_lock, self._subscription_lock:
            value = deepcopy(self._health)
            value.update(
                {
                    "ISOLATION_TIER": "SEPARATE_PROCESS",
                    "WS_OWNER_COUNT": 1 if self._child_alive() else 0,
                    "EXPECTED_INSTRUMENTS": value.get("EXPECTED_INSTRUMENTS", len(self.instruments)),
                    "PARENT_RAW_QUEUE_DEPTH": _queue_depth(self._raw_packets),
                    "PARENT_FLOW_REQUIRED_QUEUE_DEPTH": _queue_depth(self._flow_ticks),
                    "PARENT_ANALYTICAL_QUEUE_DEPTH": _queue_depth(self._flow_ticks),
                    "PARENT_FUTURES_DISPLAY_LATEST_QUEUE_DEPTH": _queue_depth(self._futures_display_ticks),
                    "PARENT_CALLBACK_FAILURES": dict(self._parent_callback_failures),
                    "CHILD_PROCESS_PID": self._process.pid if self._child_alive() and self._process else None,
                }
            )
        with self._parent_metrics_lock:
            cutoff = time.perf_counter_ns() - 10_000_000_000
            value["PARENT_DATA_PLANE"] = {
                "delivery_semantics": {
                    "raw": "LOSSLESS_EVENT",
                    "flow_required": "LOSSLESS_EVENT",
                    "futures_display": "LATEST_STATE",
                    "transport": "LOSSLESS_EVENT",
                },
                "dispatched": dict(self._parent_counts),
                "processing_rate_per_s": {
                    name: round(sum(item >= cutoff for item in values) / 10.0, 3)
                    for name, values in self._parent_dispatch_times.items()
                },
                "queue_wait_ms": {
                    name: _distribution(values)
                    for name, values in self._parent_queue_wait_ms.items()
                },
                "callback_ms": {
                    name: _distribution(values)
                    for name, values in self._parent_callback_ms.items()
                },
            }
        return value

    def transport_snapshot(self) -> dict[str, Any]:
        """Return child transport truth without parent telemetry sorting.

        Fusion needs current basket/session truth, not parent lane latency
        percentiles. Calculating those percentiles sorts multiple bounded
        deques and must not run for every Flow publication callback.
        """

        self._drain_health()
        with self._state_lock:
            return deepcopy(self._health)


def _distribution(values: deque[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}

    def pick(percentile: float) -> float:
        return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile))], 3)

    return {
        "count": len(ordered),
        "p50": pick(0.50),
        "p95": pick(0.95),
        "p99": pick(0.99),
        "max": round(ordered[-1], 3),
    }
