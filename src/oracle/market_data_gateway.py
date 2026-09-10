import asyncio
import json
import logging
import os
import queue
import random
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional, List, Dict, Any, Mapping
from zoneinfo import ZoneInfo
import websockets
from websockets.exceptions import ConnectionClosed

from src.broker.dhan_full_packet import DhanFullPacketDecoder, DhanPacketError
from src.broker.dhan_time import normalize_dhan_ltt

logger = logging.getLogger(__name__)


class MarketDataGateway:
    """
    Connects to Dhan's Live Market Data WebSocket API.
    Handles Dhan binary protocol, automatic pong/reconnect, and health exposure.
    Emits normalized ticks to subscribers.
    """

    WSS_URL = "wss://api-feed.dhan.co"
    # A provider admission rejection is not evidence that the backend process
    # is dead.  Start conservatively so a temporary 429 cannot turn into a
    # self-inflicted reconnect burst.
    RECONNECT_INITIAL_DELAY_SECONDS = 1.0
    RECONNECT_MAX_DELAY_SECONDS = 60.0
    RECONNECT_JITTER_FRACTION = 0.20

    def __init__(
        self,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
        on_tick: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_raw_packet: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_transport_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        queue_size: int = 2048,
        lossless_tick_delivery: bool = False,
    ):
        self.client_id = client_id or os.getenv("DHAN_CLIENT_ID", "")
        self.access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN", "")
        self.on_tick = on_tick
        self.on_raw_packet = on_raw_packet
        self.on_transport_event = on_transport_event
        self._lossless_tick_delivery = bool(lossless_tick_delivery)

        self.ws = None
        self._connection_state_lock = threading.RLock()
        self._is_running = False
        self._reconnect_delay = self.RECONNECT_INITIAL_DELAY_SECONDS
        self._last_message_time: Optional[datetime] = None
        self._last_response_code: Optional[int] = None
        self._generation = 0
        self._binary_buffer = b""
        self._subscription_revision = 0
        self._sent_subscription_revision = -1
        self._sent_instruments: list[dict[str, Any]] = []
        self._transport_gap_count = 0
        self._coalesced_quote_updates = 0
        self._flow_required_drops = 0
        self._malformed_packets = 0
        self._ws_received_packet_count = 0
        self._session_accepted_packet_count = 0
        self._session_rejected_packet_count = 0
        self._ltt_receive_time_substitution_count = 0
        self._latest_ltt = None
        self._last_any_packet_time: Optional[datetime] = None
        self._packet_state: dict[tuple[str, str], dict[str, Any]] = {}
        self._packet_lock = threading.RLock()
        self._reconnect_count = 0
        self._last_reconnect_reason: str | None = None
        self._connection_attempt_count = 0
        self._connection_attempt_active = False
        self._last_connection_attempt_at: str | None = None
        self._last_connection_result = "NOT_ATTEMPTED"
        self._last_connection_http_status: int | None = None
        self._last_successful_connection_at: str | None = None
        self._last_backoff_seconds: float | None = None
        self._receive_loop_alive = False
        self._connection_state = "DISCONNECTED"
        self._last_socket_activity_at: str | None = None
        self._last_binary_packet_at: str | None = None
        self._last_disconnect_exception_class: str | None = None
        self._last_close_code: int | None = None
        self._last_close_reason: str | None = None
        # Dhan's documented binary subscription flow has no per-instrument
        # acknowledgement that this runtime can verify.  First Full packet is
        # therefore intentionally exposed as receipt evidence, not an ACK.
        self._ack_status = "NOT_AVAILABLE"
        self._queued_volume: dict[tuple[Any, Any], int | None] = {}
        self._queue_state_lock = threading.RLock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscription_event: Optional[asyncio.Event] = None
        self._subscription_send_lock: Optional[asyncio.Lock] = None
        self._connection_lock: Optional[asyncio.Lock] = None
        self._background_thread: Optional[threading.Thread] = None
        self._background_lock = threading.Lock()
        self._subscription_lock = threading.RLock()
        # Injection points keep reconnect/backoff certification deterministic;
        # production continues to use asyncio.sleep and bounded random jitter.
        self._sleep = asyncio.sleep
        self._backoff_jitter: Callable[[float], float] = lambda delay: delay * random.uniform(
            1.0 - self.RECONNECT_JITTER_FRACTION,
            1.0 + self.RECONNECT_JITTER_FRACTION,
        )

        self.instruments: List[Dict[str, Any]] = []
        # The Dhan loop owns only socket I/O, bounded decode, canonical receipt
        # state, and non-blocking handoff.  No application callback may run on
        # that loop: Order Flow/Fusion can be expensive, while recorder disk
        # pressure must never delay a Ping/Pong or the next recv().  The two
        # lanes deliberately have different policies:
        #
        # * record ingress is loss-visible and never coalesces raw packets;
        # * the legacy display fanout may coalesce superseded quote-only ticks
        #   under pressure;
        # * the isolated Oracle Flow owner opts into lossless delivery.  Any
        #   exhaustion is surfaced as a required-event drop, never relabelled
        #   as coalescing or silently evicted.
        capacity = max(16, int(queue_size))
        self._tick_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=capacity)
        self._recorder_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=max(16_384, capacity * 8))
        self._fanout_thread: Optional[threading.Thread] = None
        self._recorder_dispatch_thread: Optional[threading.Thread] = None
        self._fanout_stop = threading.Event()
        self._recorder_dispatch_stop = threading.Event()
        self._fanout_callback_failures = 0
        self._recorder_callback_failures = 0
        self._recorder_ingress_drops = 0
        self._recorder_ingress_high_water = 0
        self._fanout_high_water = 0
        self._event_loop_lag_ms: deque[float] = deque(maxlen=512)
        self._callback_ms: deque[float] = deque(maxlen=512)
        self._recorder_callback_ms: deque[float] = deque(maxlen=512)
        self._slow_callback_count = 0
        self._max_slow_callback_ms = 0.0
        self._loop_lag_task: Optional[asyncio.Task] = None
        # Kept as an explicit compatibility marker for callers that inspect
        # the old field.  It is intentionally always None: downstream workers
        # are threads and never asyncio tasks on the websocket loop.
        self._worker_task: Optional[asyncio.Task] = None

    def subscribe(self, instruments: List[Dict[str, Any]]):
        """Replace the authoritative basket; resubscription is generation-safe."""
        canonical = {
            (str(item.get("exchange_segment")), str(item.get("security_id"))): dict(item)
            for item in instruments
            if item.get("security_id") is not None
        }
        values = [canonical[key] for key in sorted(canonical)]
        with self._subscription_lock:
            if values != self.instruments:
                self.instruments = values
                self._subscription_revision += 1
                loop = self._loop
                event = self._subscription_event
                if loop is not None and loop.is_running() and event is not None:
                    loop.call_soon_threadsafe(event.set)

    def _start_dispatch_workers(self) -> None:
        """Start the two non-async callback lanes exactly once per gateway."""

        self._fanout_stop.clear()
        self._recorder_dispatch_stop.clear()
        if self._fanout_thread is None or not self._fanout_thread.is_alive():
            self._fanout_thread = threading.Thread(
                target=self._run_fanout_dispatch,
                name="oracle-dhan-analytical-fanout",
                daemon=True,
            )
            self._fanout_thread.start()
        if self._recorder_dispatch_thread is None or not self._recorder_dispatch_thread.is_alive():
            self._recorder_dispatch_thread = threading.Thread(
                target=self._run_recorder_dispatch,
                name="oracle-dhan-recorder-ingress",
                daemon=True,
            )
            self._recorder_dispatch_thread.start()

    async def _worker_lifecycle_waiter(self) -> None:
        """Compatibility lifecycle task; callbacks never execute on this loop."""

        while self._is_running:
            await asyncio.sleep(0.1)

    def _stop_dispatch_workers(self) -> None:
        self._fanout_stop.set()
        self._recorder_dispatch_stop.set()
        for worker in (self._fanout_thread, self._recorder_dispatch_thread):
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=1.0)

    def _run_fanout_dispatch(self) -> None:
        while not self._fanout_stop.is_set() or not self._tick_queue.empty():
            try:
                tick = self._tick_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                tick["gateway_queue_lag_ns"] = max(
                    0, time.perf_counter_ns() - int(tick.get("decode_done_ns") or time.perf_counter_ns())
                )
                key = (tick.get("exchange_segment"), tick.get("security_id"))
                with self._queue_state_lock:
                    self._queued_volume.pop(key, None)
                if int(tick.get("response_code") or 0) == 8:
                    if bool(tick.get("ltt_session_accepted")):
                        self._session_accepted_packet_count += 1
                    else:
                        self._session_rejected_packet_count += 1
                callback = self.on_tick
                if callback is not None:
                    started_ns = time.perf_counter_ns()
                    try:
                        # Production fanout is synchronous.  An async callback
                        # is not permitted to migrate execution back onto the
                        # Dhan loop; record the contract violation visibly.
                        if asyncio.iscoroutinefunction(callback):
                            raise TypeError("async on_tick callbacks are not supported on the isolated fanout lane")
                        callback(tick)
                    except Exception:
                        self._fanout_callback_failures += 1
                        logger.exception("Oracle downstream tick fanout failed")
                    finally:
                        elapsed_ms = max(0.0, (time.perf_counter_ns() - started_ns) / 1_000_000.0)
                        self._callback_ms.append(elapsed_ms)
                        if elapsed_ms >= 100.0:
                            self._slow_callback_count += 1
                            self._max_slow_callback_ms = max(self._max_slow_callback_ms, elapsed_ms)
            finally:
                self._tick_queue.task_done()

    def _run_recorder_dispatch(self) -> None:
        while not self._recorder_dispatch_stop.is_set() or not self._recorder_queue.empty():
            try:
                kind, payload = self._recorder_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                started_ns = time.perf_counter_ns()
                if kind == "RAW":
                    callback = self.on_raw_packet
                    if callback is not None:
                        callback(payload)
                else:
                    callback = self.on_transport_event
                    if callback is not None:
                        event_type, event_payload = payload
                        callback(event_type, event_payload)
                self._recorder_callback_ms.append(
                    max(0.0, (time.perf_counter_ns() - started_ns) / 1_000_000.0)
                )
            except Exception:
                self._recorder_callback_failures += 1
                logger.exception("Oracle recorder ingress callback failed")
            finally:
                self._recorder_queue.task_done()

    async def start(self):
        """Start the WebSocket connection loop with auto-reconnect."""
        if self._is_running:
            return
        self._is_running = True
        self._loop = asyncio.get_running_loop()
        self._subscription_event = asyncio.Event()
        self._subscription_send_lock = asyncio.Lock()
        self._connection_lock = asyncio.Lock()
        self._start_dispatch_workers()
        self._worker_task = asyncio.create_task(self._worker_lifecycle_waiter())

        while self._is_running:
            try:
                await self._connect_once()
            except asyncio.CancelledError:
                self._is_running = False
                logger.info("MarketDataGateway stopped via cancellation.")
                break
            except Exception as e:
                self._record_connection_failure(e)
                delay = self._next_reconnect_delay()
                logger.error("WebSocket connection error: %s. Reconnecting in %.3fs...", e, delay)
            finally:
                if self._is_running:
                    # A clean disconnect follows the same bounded policy; an
                    # exception has already selected and recorded its delay.
                    delay = self._last_backoff_seconds
                    if delay is None:
                        delay = self._next_reconnect_delay()
                    await self._sleep(delay)
                    self._last_backoff_seconds = None

        if self._worker_task is not None:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
        self._stop_dispatch_workers()

    async def _connect_once(self) -> None:
        """Run one connection attempt under the gateway's single-flight lock."""

        if self._connection_lock is None:
            self._connection_lock = asyncio.Lock()
        async with self._connection_lock:
            self._connection_attempt_active = True
            self._connection_attempt_count += 1
            self._last_connection_attempt_at = datetime.now(timezone.utc).isoformat()
            self._last_connection_result = "CONNECTING"
            self._last_connection_http_status = None
            try:
                await self._connect_and_run()
            finally:
                self._connection_attempt_active = False

    def _record_connection_success(self) -> None:
        self._reconnect_delay = self.RECONNECT_INITIAL_DELAY_SECONDS
        self._last_backoff_seconds = None
        self._last_connection_result = "CONNECTED"
        self._last_connection_http_status = None
        self._last_successful_connection_at = datetime.now(timezone.utc).isoformat()
        with self._connection_state_lock:
            self._connection_state = "CONNECTED"

    def _record_connection_failure(self, error: Exception) -> None:
        reason = f"{type(error).__name__}:{error}"
        self._last_reconnect_reason = reason
        status = self._http_status_from_error(error)
        self._last_connection_http_status = status
        self._last_connection_result = f"REJECTED_HTTP_{status}" if status is not None else "FAILED"
        with self._connection_state_lock:
            self._connection_state = "RECONNECT_WAIT" if self._is_running else "DISCONNECTED"
            self._last_disconnect_exception_class = type(error).__name__

    @staticmethod
    def _http_status_from_error(error: Exception) -> int | None:
        """Best-effort provider status extraction without inferring a cause."""

        for value in (
            getattr(error, "status_code", None),
            getattr(getattr(error, "response", None), "status_code", None),
        ):
            if isinstance(value, int) and 100 <= value <= 599:
                return value
        match = re.search(r"\bHTTP\s+(\d{3})\b", str(error))
        return int(match.group(1)) if match else None

    def _next_reconnect_delay(self) -> float:
        base = min(self.RECONNECT_MAX_DELAY_SECONDS, max(
            self.RECONNECT_INITIAL_DELAY_SECONDS,
            self._reconnect_delay,
        ))
        jittered = self._backoff_jitter(base)
        delay = min(self.RECONNECT_MAX_DELAY_SECONDS, max(0.0, float(jittered)))
        self._last_backoff_seconds = delay
        self._reconnect_delay = min(self.RECONNECT_MAX_DELAY_SECONDS, base * 2.0)
        return delay

    async def _connect_and_run(self):
        import urllib.parse
        url = f"wss://api-feed.dhan.co?version=2&token={urllib.parse.quote(self.access_token)}&clientId={self.client_id}&authType=2"
        logger.info(f"Connecting to Dhan WebSocket for clientId={self.client_id} (authType=2)...")

        async with websockets.connect(
            url,
            ping_interval=10,
            ping_timeout=40,
            max_queue=256,
        ) as ws:
            with self._connection_state_lock:
                self._generation += 1
                generation = self._generation
                if generation > 1:
                    self._reconnect_count += 1
                self.ws = ws
                self._binary_buffer = b""
                # A connection cannot unsubscribe a prior dead socket.  Its
                # first subscription is one exact RequestCode 21 per basket.
                self._sent_instruments = []
                self._sent_subscription_revision = -1
                self._connection_state = "CONNECTED"
                self._receive_loop_alive = True
                self._last_disconnect_exception_class = None
                self._last_close_code = None
                self._last_close_reason = None
            self._record_connection_success()
            logger.info("Connected to Dhan WebSocket.")
            self._emit_transport_event(
                "FEED_CONNECTED" if generation == 1 else "FEED_RECONNECTED",
                instrument_count=len(self.instruments),
            )

            await self._send_subscriptions(ws=ws, generation=generation)
            subscription_watcher = asyncio.create_task(self._watch_subscriptions(ws, generation))
            loop_lag_probe = asyncio.create_task(self._measure_event_loop_lag(ws, generation))
            try:
                async for message in ws:
                    if not self._is_current_generation(ws, generation):
                        # A delayed old socket may never mutate canonical
                        # transport state after a newer connection exists.
                        break
                    if isinstance(message, bytes):
                        self._handle_binary_message(message, generation=generation)
                    else:
                        self._handle_text_message(message, generation=generation)
            except Exception as error:
                self._record_disconnect(ws, generation, error)
                raise
            finally:
                subscription_watcher.cancel()
                loop_lag_probe.cancel()
                await asyncio.gather(subscription_watcher, loop_lag_probe, return_exceptions=True)
                self._finish_generation(ws, generation)

    def _is_current_generation(self, ws: Any, generation: int) -> bool:
        with self._connection_state_lock:
            return self.ws is ws and self._generation == generation

    def _finish_generation(self, ws: Any, generation: int) -> None:
        """Only the live generation may clear its own connection state."""

        with self._connection_state_lock:
            if self.ws is not ws or self._generation != generation:
                return
            self._receive_loop_alive = False
            self.ws = None
            self._connection_state = "RECONNECT_WAIT" if self._is_running else "DISCONNECTED"
            self._last_close_code = getattr(ws, "close_code", None)
            self._last_close_reason = getattr(ws, "close_reason", None)

    def _record_disconnect(self, ws: Any, generation: int, error: Exception) -> None:
        if not self._is_current_generation(ws, generation):
            return
        with self._connection_state_lock:
            self._last_disconnect_exception_class = type(error).__name__
            self._last_close_code = getattr(error, "code", None) or getattr(ws, "close_code", None)
            self._last_close_reason = str(getattr(error, "reason", "") or getattr(ws, "close_reason", "") or "") or None
            self._connection_state = "DEGRADED"

    async def _measure_event_loop_lag(self, ws: Any, generation: int) -> None:
        """Cheap lag sampler; it never calls providers or serializes a view."""

        interval_seconds = 0.25
        expected = time.perf_counter()
        while self._is_running and self._is_current_generation(ws, generation):
            await asyncio.sleep(interval_seconds)
            now = time.perf_counter()
            lag_ms = max(0.0, (now - expected - interval_seconds) * 1_000.0)
            self._event_loop_lag_ms.append(lag_ms)
            expected = now

    async def _watch_subscriptions(self, ws: Any = None, generation: int | None = None) -> None:
        """Push basket revisions even when the current basket has no traffic."""
        event = self._subscription_event
        if event is None:
            return
        target = self.ws if ws is None else ws
        current_generation = self._generation if generation is None else generation
        while self._is_running and self._is_current_generation(target, current_generation):
            await event.wait()
            event.clear()
            if (
                self._is_current_generation(target, current_generation)
                and self._sent_subscription_revision != self._subscription_revision
            ):
                await self._send_subscriptions(ws=target, generation=current_generation)

    async def _send_subscriptions(self, *, ws: Any = None, generation: int | None = None):
        """Send official DhanHQ v2 JSON subscription request."""
        target = self.ws if ws is None else ws
        current_generation = self._generation if generation is None else generation
        if target is None or not self._is_current_generation(target, current_generation):
            return
        send_lock = self._subscription_send_lock
        if send_lock is not None:
            async with send_lock:
                await self._send_subscriptions_unlocked(target, current_generation)
            return
        await self._send_subscriptions_unlocked(target, current_generation)

    async def _send_subscriptions_unlocked(self, ws: Any, generation: int):
        with self._subscription_lock:
            instruments = [dict(item) for item in self.instruments]
            revision = self._subscription_revision
        if not instruments or not self._is_current_generation(ws, generation):
            return

        inst_list = []
        for inst in instruments:
            seg = str(inst.get("exchange_segment", "IDX_I"))
            sec_id = str(inst.get("security_id", "13"))
            inst_list.append({
                "ExchangeSegment": seg,
                "SecurityId": sec_id
            })

        if self._sent_instruments:
            for start in range(0, len(self._sent_instruments), 100):
                if not self._is_current_generation(ws, generation):
                    return
                batch = self._sent_instruments[start:start + 100]
                await ws.send(json.dumps({
                    "RequestCode": 22,
                    "InstrumentCount": len(batch),
                    "InstrumentList": batch,
                }))
        logger.info(f"Sending Dhan Full subscription payload for {len(inst_list)} instruments...")
        for start in range(0, len(inst_list), 100):
            if not self._is_current_generation(ws, generation):
                return
            batch = inst_list[start:start + 100]
            await ws.send(json.dumps({
                "RequestCode": 21,
                "InstrumentCount": len(batch),
                "InstrumentList": batch,
            }))
        if not self._is_current_generation(ws, generation):
            return
        self._sent_instruments = inst_list
        self._sent_subscription_revision = revision
        with self._connection_state_lock:
            if self._generation == generation:
                self._connection_state = "LIVE"
        self._emit_transport_event("BASKET_RESET", instrument_count=len(inst_list))

    def _handle_binary_message(self, message: bytes, *, generation: int | None = None):
        """
        Parse Little-Endian 8-Byte DhanHQ v2 Header:
        - Byte 0: Feed/Response Code (uint8)
        - Bytes 1..2: Message Length (uint16)
        - Byte 3: Exchange Segment (uint8)
        - Bytes 4..7: Security ID (int32)
        """
        if generation is not None:
            with self._connection_state_lock:
                if generation != self._generation:
                    return
        if not message:
            return
        receive_ns = time.perf_counter_ns()
        receive_wall = datetime.now(timezone.utc)
        self._last_socket_activity_at = receive_wall.isoformat()
        self._last_binary_packet_at = receive_wall.isoformat()
        # Preserve the pre-existing header-only disconnect compatibility at
        # the transport boundary.  The strict broker decoder still rejects it
        # as a truncated official 12-byte control packet.
        if len(message) == 8 and message[0] == 50:
            self._last_message_time = receive_wall
            self._last_response_code = 50
            self._enqueue_tick({
                "security_id": str(int.from_bytes(message[4:8], "little", signed=True)),
                "exchange_segment": message[3],
                "response_code": 50,
                "feed_code": 50,
                "disconnect_code": 50,
                "source_timestamp": receive_wall.isoformat(),
            })
            return
        try:
            packets, remaining = DhanFullPacketDecoder.decode_stream(self._binary_buffer + message)
            self._binary_buffer = remaining
            for packet in packets:
                self._last_message_time = receive_wall
                self._last_response_code = packet.response_code
                tick = packet.to_dict()
                tick.update({
                    "feed_code": packet.response_code,
                    "feed_generation": self._generation or 1,
                    "feed_receive_ns": receive_ns,
                    "decode_done_ns": time.perf_counter_ns(),
                    "receive_wall_utc": receive_wall.isoformat(),
                    "source_timestamp": receive_wall.isoformat(),
                    "transport_gap_count": self._transport_gap_count,
                })
                if "ltt" in tick:
                    try:
                        normalized = normalize_dhan_ltt(tick["ltt"], receive_wall)
                        tick.update({
                            "ltt_raw_epoch": normalized.raw_epoch,
                            "ltt_raw_utc": normalized.raw_utc.isoformat(),
                            "ltt_raw_ist": normalized.raw_ist.isoformat(),
                            "ltt_normalized_epoch": normalized.normalized_epoch,
                            "ltt_utc": normalized.utc.isoformat(),
                            "ltt_ist": normalized.ist.isoformat(),
                            "receive_time_ist": normalized.receive_ist.isoformat() if normalized.receive_ist else None,
                            "ltt_raw_receive_skew_ms": normalized.raw_receive_skew_ms,
                            "ltt_receive_skew_ms": normalized.receive_skew_ms,
                            "ltt_session_accepted": normalized.session_accepted,
                            "ltt_event_session_accepted": normalized.event_session_accepted,
                            "DHAN_LTT_RAW_SUSPICIOUS": normalized.raw_ltt_suspicious,
                            "DHAN_LTT_RECEIVE_TIME_SUBSTITUTED": normalized.receive_time_substituted,
                        })
                        if normalized.receive_time_substituted:
                            self._ltt_receive_time_substitution_count += 1
                        self._latest_ltt = {
                            key: tick.get(key)
                            for key in (
                                "ltt_raw_epoch", "ltt_raw_utc", "ltt_raw_ist",
                                "ltt_normalized_epoch", "ltt_utc", "ltt_ist",
                                "receive_time_ist", "ltt_raw_receive_skew_ms",
                                "ltt_receive_skew_ms", "ltt_session_accepted",
                                "ltt_event_session_accepted", "DHAN_LTT_RAW_SUSPICIOUS",
                                "DHAN_LTT_RECEIVE_TIME_SUBSTITUTED",
                            )
                        }
                    except (TypeError, ValueError, OverflowError):
                        tick["ltt_session_accepted"] = False
                if packet.response_code == 8:
                    self._ws_received_packet_count += 1
                    self._record_packet_receipt(tick, receive_wall)
                if "cumulative_volume" in tick:
                    tick["volume"] = tick["cumulative_volume"]
                if packet.response_code == 50:
                    tick["disconnect_code"] = 50
                    logger.warning("Received Dhan feed disconnect notification")
                    self._emit_transport_event("FEED_DISCONNECTED", reason="DHAN_DISCONNECT_PACKET")
                self._enqueue_tick(tick)
        except DhanPacketError as error:
            self._malformed_packets += 1
            logger.error("Rejected malformed Dhan packet: %s", error)

    def _enqueue_tick(self, tick: Dict[str, Any]) -> None:
        """Handoff only: never wait for analytics or disk from the WS loop."""

        self._enqueue_recorder_tick(tick)
        key = (tick.get("exchange_segment"), tick.get("security_id"))
        volume = tick.get("cumulative_volume")
        with self._queue_state_lock:
            if self._tick_queue.full():
                if self._lossless_tick_delivery:
                    self._flow_required_drops += 1
                    self._transport_gap_count += 1
                    self._emit_transport_event("FEED_GAP", reason="FLOW_REQUIRED_BACKPRESSURE")
                    logger.error("Lossless Flow handoff queue full; required packet rejected")
                    return
                if volume is not None and self._queued_volume.get(key) == volume:
                    self._coalesced_quote_updates += 1
                    return
                try:
                    dropped = self._tick_queue.get_nowait()
                    self._tick_queue.task_done()
                    self._queued_volume.pop((dropped.get("exchange_segment"), dropped.get("security_id")), None)
                    self._transport_gap_count += 1
                    tick["transport_gap_count"] = self._transport_gap_count
                    self._emit_transport_event("FEED_GAP", reason="ANALYTICAL_FANOUT_BACKPRESSURE")
                except queue.Empty:
                    pass
            self._queued_volume[key] = volume
            self._tick_queue.put_nowait(tick)
            self._fanout_high_water = max(self._fanout_high_water, self._tick_queue.qsize())

    def _enqueue_recorder_tick(self, tick: Mapping[str, Any]) -> None:
        """Queue immutable raw evidence separately from coalescible analytics."""

        if self.on_raw_packet is None:
            return
        try:
            self._recorder_queue.put_nowait(("RAW", dict(tick)))
            self._recorder_ingress_high_water = max(
                self._recorder_ingress_high_water,
                self._recorder_queue.qsize(),
            )
        except queue.Full:
            # Raw evidence may never disappear silently.  The authoritative
            # recorder's own health shows any downstream rejection as well.
            self._recorder_ingress_drops += 1
            self._transport_gap_count += 1
            logger.error("Recorder ingress queue full; raw packet handoff rejected")

    @staticmethod
    def _canonical_segment(value: Any) -> str:
        return {
            0: "IDX_I",
            1: "NSE_EQ",
            2: "NSE_FNO",
            3: "NSE_CURRENCY",
            4: "BSE_EQ",
            5: "MCX_COMM",
            7: "BSE_CURRENCY",
            8: "BSE_FNO",
        }.get(value, str(value))

    def _record_packet_receipt(self, tick: Mapping[str, Any], received_at: datetime) -> None:
        """Record Full-packet receipt independently of socket/text traffic."""

        key = (
            self._canonical_segment(tick.get("exchange_segment")),
            str(tick.get("security_id") or ""),
        )
        if not key[1]:
            return
        with self._packet_lock:
            state = self._packet_state.setdefault(key, {"packet_count": 0})
            state["packet_count"] = int(state.get("packet_count") or 0) + 1
            state["last_packet_timestamp"] = received_at.isoformat()
            state["last_response_code"] = int(tick.get("response_code") or 8)
            self._last_any_packet_time = received_at

    def _emit_transport_event(
        self,
        event_type: str,
        *,
        instrument_count: int | None = None,
        reason: str | None = None,
    ) -> None:
        if self.on_transport_event is None:
            return
        payload = {
            "feed_generation": self._generation,
            "subscription_revision": self._subscription_revision,
            "transport_gap_count": self._transport_gap_count,
            "instrument_count": len(self.instruments) if instrument_count is None else instrument_count,
            "receive_wall_utc": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        try:
            self._recorder_queue.put_nowait(("TRANSPORT", (event_type, payload)))
            self._recorder_ingress_high_water = max(
                self._recorder_ingress_high_water,
                self._recorder_queue.qsize(),
            )
        except queue.Full:
            self._recorder_ingress_drops += 1
            logger.error("Recorder ingress queue full; transport event rejected")

    def _handle_text_message(self, message: str, *, generation: int | None = None):
        """Handle JSON or plain text messages (e.g. errors, ACKs)."""
        if generation is not None:
            with self._connection_state_lock:
                if generation != self._generation:
                    return
        self._last_socket_activity_at = datetime.now(timezone.utc).isoformat()
        try:
            data = json.loads(message)
            self._last_message_time = datetime.now(timezone.utc)
            logger.info(f"Received Dhan text message: {data}")
        except json.JSONDecodeError:
            logger.info(f"Received Dhan raw text message: {message}")

    async def stop(self):
        """Stop the gateway and close connections."""
        self._is_running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
        self._stop_dispatch_workers()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        with self._connection_state_lock:
            self.ws = None
            self._connection_state = "DISCONNECTED"
        if self._subscription_event is not None:
            self._subscription_event.set()

    def start_background(self) -> None:
        """Own one daemon asyncio loop for the canonical Oracle feed."""
        with self._background_lock:
            if self._background_thread is not None and self._background_thread.is_alive():
                return
            self._background_thread = threading.Thread(
                target=lambda: asyncio.run(self.start()),
                name="oracle-dhan-full-feed",
                daemon=True,
            )
            self._background_thread.start()

    def stop_background(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self.stop(), loop)
            try:
                future.result(timeout=3.0)
            except Exception:
                pass

    def health(self) -> Dict[str, Any]:
        """Expose socket, requested-basket, and actual packet health separately."""
        with self._connection_state_lock:
            ws = self.ws
            generation = self._generation
            connection_state = self._connection_state
            receive_loop_alive = self._receive_loop_alive
            last_socket_activity = self._last_socket_activity_at
            last_binary_packet = self._last_binary_packet_at
            disconnect_exception_class = self._last_disconnect_exception_class
            close_code = self._last_close_code
            close_reason = self._last_close_reason
        is_connected = ws is not None and not bool(getattr(ws, "closed", False))
        last_msg = self._last_message_time.isoformat() if self._last_message_time else None
        now = datetime.now(timezone.utc)
        with self._subscription_lock:
            instruments = [dict(item) for item in self.instruments]
            requested_count = len(self._sent_instruments)
        with self._packet_lock:
            packet_state = {key: dict(value) for key, value in self._packet_state.items()}
            last_any_packet_time = self._last_any_packet_time

        per_instrument = []
        fresh = late = degraded = stale = ever_received = currently_receiving = 0
        for instrument in instruments:
            segment = self._canonical_segment(instrument.get("exchange_segment"))
            security_id = str(instrument.get("security_id") or "")
            receipt = packet_state.get((segment, security_id), {})
            timestamp = receipt.get("last_packet_timestamp")
            try:
                received = datetime.fromisoformat(str(timestamp)) if timestamp else None
                age_ms = max(0.0, (now - received.astimezone(timezone.utc)).total_seconds() * 1000.0) if received else None
            except (TypeError, ValueError):
                age_ms = None
            if age_ms is None:
                freshness = "STALE"
            elif age_ms <= 3_000.0:
                freshness = "FRESH"
                fresh += 1
                currently_receiving += 1
            elif age_ms <= 15_000.0:
                freshness = "LATE"
                late += 1
                currently_receiving += 1
            elif age_ms <= 45_000.0:
                freshness = "DEGRADED"
                degraded += 1
                currently_receiving += 1
            else:
                freshness = "STALE"
            if receipt:
                ever_received += 1
            if freshness == "STALE":
                stale += 1
            per_instrument.append({
                "security_id": security_id,
                "role": instrument.get("role") or "UNSPECIFIED",
                "exchange_segment": segment,
                "last_packet_timestamp": timestamp,
                "last_packet_age_ms": round(age_ms, 3) if age_ms is not None else None,
                "packet_count": int(receipt.get("packet_count") or 0),
                "ever_received": bool(receipt),
                "freshness_state": freshness,
            })

        futures = next((row for row in per_instrument if row["role"] == "NIFTY_FUTURE"), None)
        futures_state = str((futures or {}).get("freshness_state") or "STALE")
        market_open = _nse_market_open(now)
        if not is_connected:
            basket_health = "DISCONNECTED"
        elif not instruments:
            basket_health = "UNCONFIGURED"
        elif not market_open:
            basket_health = "MARKET_CLOSED"
        elif ever_received == 0 or currently_receiving == 0 or futures_state in {"DEGRADED", "STALE"}:
            basket_health = "DATA_DEGRADED"
        elif fresh == len(instruments):
            basket_health = "FULLY_FRESH"
        else:
            basket_health = "PARTIALLY_RECEIVING"
        last_any_age_ms = (
            round(max(0.0, (now - last_any_packet_time).total_seconds() * 1000.0), 3)
            if last_any_packet_time is not None else None
        )

        with self._queue_state_lock:
            fanout_depth = self._tick_queue.qsize()
            fanout_high_water = self._fanout_high_water
            coalesced = self._coalesced_quote_updates
            gaps = self._transport_gap_count
        return {
            # Legacy aliases remain for existing consumers.  The uppercase
            # fields are the truthful P0 contract and must not be conflated.
            "status": "UP" if is_connected else "DOWN",
            "WS_CONNECTED": is_connected,
            "ACK_STATUS": self._ack_status,
            "EXPECTED_INSTRUMENTS": len(instruments),
            "REQUESTED_INSTRUMENTS": requested_count,
            "ACKNOWLEDGED_INSTRUMENTS": None,
            "EVER_RECEIVED_INSTRUMENTS": ever_received,
            "CURRENTLY_RECEIVING_INSTRUMENTS": currently_receiving,
            "FRESH_INSTRUMENTS": fresh,
            "LATE_INSTRUMENTS": late,
            "DEGRADED_INSTRUMENTS": degraded,
            "STALE_INSTRUMENTS": stale,
            "LAST_ANY_PACKET_TS": last_any_packet_time.isoformat() if last_any_packet_time else None,
            "LAST_ANY_PACKET_AGE_MS": last_any_age_ms,
            "FEED_GENERATION": generation,
            "RECONNECT_COUNT": self._reconnect_count,
            "RECONNECT_REASON": self._last_reconnect_reason,
            "CONNECTION_ATTEMPTS": self._connection_attempt_count,
            "CONNECTION_ATTEMPT_ACTIVE": self._connection_attempt_active,
            "LAST_CONNECTION_ATTEMPT_TS": self._last_connection_attempt_at,
            "LAST_CONNECT_RESULT": self._last_connection_result,
            "LAST_CONNECT_HTTP_STATUS": self._last_connection_http_status,
            "LAST_SUCCESSFUL_CONNECTION_TS": self._last_successful_connection_at,
            "LAST_BACKOFF_MS": (
                round(self._last_backoff_seconds * 1000.0, 3)
                if self._last_backoff_seconds is not None else None
            ),
            "SUBSCRIPTION_REVISION": self._subscription_revision,
            "SENT_SUBSCRIPTION_REVISION": self._sent_subscription_revision,
            "BASKET_HEALTH": basket_health,
            "RECEIVE_LOOP_ALIVE": receive_loop_alive,
            "DHAN_CONNECTION_STATE": connection_state,
            "CONNECTION_GENERATION": generation,
            "LAST_RAW_SOCKET_ACTIVITY": last_socket_activity,
            "LAST_BINARY_PACKET": last_binary_packet,
            "PING_INTERVAL_MS": 10_000.0,
            "PONG_LATENCY_MS": _websocket_latency_ms(ws),
            "DISCONNECT_EXCEPTION_CLASS": disconnect_exception_class,
            "CLOSE_CODE": close_code,
            "CLOSE_REASON": close_reason,
            "EVENT_LOOP_LAG_MS": _distribution(self._event_loop_lag_ms),
            "SLOW_CALLBACK_COUNT": self._slow_callback_count,
            "MAX_SLOW_CALLBACK_MS": round(self._max_slow_callback_ms, 3),
            "ANALYTICAL_CALLBACK_MS": _distribution(self._callback_ms),
            "RECORDER_CALLBACK_MS": _distribution(self._recorder_callback_ms),
            "instruments": per_instrument,
            "last_message_time": last_msg,
            "is_running": self._is_running,
            "reconnect_delay": self._reconnect_delay,
            "subscribed_instruments": len(self.instruments),
            "feed_generation": generation,
            "queue_depth": fanout_depth,
            "queue_capacity": self._tick_queue.maxsize,
            "queue_high_water": fanout_high_water,
            "transport_gap_count": gaps,
            "coalesced_quote_updates": coalesced,
            "FLOW_DELIVERY_SEMANTICS": "LOSSLESS_EVENT" if self._lossless_tick_delivery else "LEGACY_COALESCIBLE",
            "FLOW_REQUIRED_DROPS": self._flow_required_drops,
            "RECORDER_INGRESS_QUEUE_DEPTH": self._recorder_queue.qsize(),
            "RECORDER_INGRESS_QUEUE_CAPACITY": self._recorder_queue.maxsize,
            "RECORDER_INGRESS_QUEUE_HIGH_WATER": self._recorder_ingress_high_water,
            "RECORDER_INGRESS_DROPS": self._recorder_ingress_drops,
            "FANOUT_CALLBACK_FAILURES": self._fanout_callback_failures,
            "RECORDER_CALLBACK_FAILURES": self._recorder_callback_failures,
            "malformed_packets": self._malformed_packets,
            "ws_received_packet_count": self._ws_received_packet_count,
            "session_accepted_packet_count": self._session_accepted_packet_count,
            "session_rejected_packet_count": self._session_rejected_packet_count,
            "ltt_receive_time_substitution_count": self._ltt_receive_time_substitution_count,
            "latest_ltt": dict(self._latest_ltt or {}),
            "request_code": 21,
        }


def _nse_market_open(now: datetime) -> bool:
    value = now.astimezone(ZoneInfo("Asia/Kolkata"))
    return value.weekday() < 5 and (value.hour, value.minute) >= (9, 15) and (value.hour, value.minute) < (15, 30)


def _websocket_latency_ms(ws: Any) -> float | None:
    """Read the official websockets latency attribute without issuing a ping."""

    try:
        value = getattr(ws, "latency", None)
        if value is None:
            return None
        return round(max(0.0, float(value) * 1_000.0), 3)
    except (TypeError, ValueError):
        return None


def _distribution(values: Any) -> dict[str, float | int]:
    """Small bounded telemetry summary; never allocates from an unbounded stream."""

    ordered = sorted(float(value) for value in tuple(values))
    if not ordered:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    def percentile(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
        return round(ordered[index], 3)

    return {
        "count": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": round(ordered[-1], 3),
    }
