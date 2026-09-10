"""Fail-closed Dhan live-broker foundation.

This module intentionally exposes no scheduler or strategy activation surface.  A
caller must select LIVE explicitly and pass both independent enablement gates
before any mutation can reach the already-authorized Dhan client.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Protocol
from urllib.parse import urlencode

from .dhan_client import DhanClient


class LiveFoundationError(RuntimeError):
    pass


class LiveExecutionDisabled(LiveFoundationError):
    pass


class ReconciliationMismatch(LiveFoundationError):
    pass


class StaleQuoteError(LiveFoundationError):
    pass


class RuntimeMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass(frozen=True)
class BrokerRuntimeConfig:
    mode: RuntimeMode = RuntimeMode.PAPER
    live_execution_enabled: bool = False
    broker_submission_enabled: bool = False

    def assert_live_mutation_allowed(self) -> None:
        if self.mode is not RuntimeMode.LIVE:
            raise LiveExecutionDisabled("runtime mode is not explicitly LIVE")
        if not self.live_execution_enabled or not self.broker_submission_enabled:
            raise LiveExecutionDisabled("LIVE execution and broker submission remain disabled")


@dataclass(frozen=True)
class ModeIsolationPaths:
    root: Path
    mode: RuntimeMode

    @property
    def directory(self) -> Path:
        return self.root / self.mode.value.lower()

    @property
    def orders(self) -> Path:
        return self.directory / "orders.json"

    @property
    def recovery(self) -> Path:
        return self.directory / "recovery.json"

    @property
    def journal(self) -> Path:
        return self.directory / "journal.json"

    @property
    def replay(self) -> Path:
        return self.directory / "replay.json"


class AtomicJsonStore:
    """Small durable store used for idempotency and restart recovery."""

    SECRET_KEYS = {"access_token", "accessToken", "api_secret", "password", "pin", "totp"}

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = RLock()

    def read(self, default: Any) -> Any:
        with self._lock:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return default

    def write(self, value: Any) -> None:
        sanitized = self._sanitize(value)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(sanitized, handle, sort_keys=True, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): cls._sanitize(item) for key, item in value.items() if str(key) not in cls.SECRET_KEYS}
        if isinstance(value, (list, tuple)):
            return [cls._sanitize(item) for item in value]
        return value


class DhanWebSocket(Protocol):
    def connect(self, url: str, on_message: Callable[[Any], None], on_disconnect: Callable[[Any], None]) -> None: ...
    def subscribe(self, instruments: Iterable[Mapping[str, str]]) -> None: ...
    def close(self) -> None: ...


class DhanFeedDecoder:
    """Decode Dhan v2 little-endian Full packets into canonical top-of-book quotes."""

    EXCHANGE_SEGMENTS = {
        0: "IDX_I",
        1: "NSE_EQ",
        2: "NSE_FNO",
        3: "NSE_CURRENCY",
        4: "BSE_EQ",
        5: "MCX_COMM",
        7: "BSE_CURRENCY",
        8: "BSE_FNO",
    }

    @classmethod
    def decode_full_quote(cls, packet: bytes) -> Mapping[str, Any]:
        if not isinstance(packet, (bytes, bytearray)) or len(packet) < 82:
            raise LiveFoundationError("Dhan full quote packet is incomplete")
        response_code = packet[0]
        declared_length = struct.unpack_from("<H", packet, 1)[0]
        if response_code != 8 or declared_length > len(packet):
            raise LiveFoundationError("Dhan packet is not a complete Full packet")
        segment = cls.EXCHANGE_SEGMENTS.get(packet[3])
        if segment is None:
            raise LiveFoundationError("Dhan exchange segment is unsupported")
        security_id = struct.unpack_from("<I", packet, 4)[0]
        ltp = struct.unpack_from("<f", packet, 8)[0]
        timestamp = struct.unpack_from("<I", packet, 14)[0]
        bid = struct.unpack_from("<f", packet, 74)[0]
        ask = struct.unpack_from("<f", packet, 78)[0]
        return {
            "exchange_segment": segment,
            "security_id": str(security_id),
            "ltp": float(ltp),
            "bid": float(bid) if bid > 0 else None,
            "ask": float(ask) if ask > 0 else None,
            "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc),
        }


class WebsocketsDhanTransport:
    """Concrete Dhan v2 websocket transport; imports the dependency lazily."""

    def __init__(self):
        self._connection = None
        self._receiver: Optional[Thread] = None
        self._closed = True

    def connect(self, url: str, on_message: Callable[[Any], None], on_disconnect: Callable[[Any], None]) -> None:
        try:
            from websockets.sync.client import connect
        except ImportError as error:
            raise LiveFoundationError("websockets dependency is unavailable") from error
        self._connection = connect(url, open_timeout=10, close_timeout=5)
        self._closed = False

        def receive() -> None:
            try:
                assert self._connection is not None
                for message in self._connection:
                    on_message(message)
            except Exception as error:
                if not self._closed:
                    on_disconnect(error)

        self._receiver = Thread(target=receive, name="dhan-market-feed", daemon=True)
        self._receiver.start()

    def subscribe(self, instruments: Iterable[Mapping[str, str]]) -> None:
        if self._connection is None:
            raise LiveFoundationError("Dhan websocket is not connected")
        values = [dict(item) for item in instruments]
        for start in range(0, len(values), 100):
            batch = values[start:start + 100]
            self._connection.send(json.dumps({"RequestCode": 21, "InstrumentCount": len(batch), "InstrumentList": batch}))

    def close(self) -> None:
        self._closed = True
        if self._connection is not None:
            try:
                self._connection.send(json.dumps({"RequestCode": 12}))
            finally:
                self._connection.close()
        self._connection = None


class DhanBrokerAdapter:
    """Production API façade over the existing guarded Dhan client."""

    provider_name = "DHAN"

    def __init__(
        self,
        client: Optional[DhanClient] = None,
        *,
        config: Optional[BrokerRuntimeConfig] = None,
        websocket: Optional[DhanWebSocket] = None,
        reconnect_attempts: int = 3,
    ):
        self.client = client or DhanClient()
        self.config = config or BrokerRuntimeConfig()
        self.websocket = websocket or WebsocketsDhanTransport()
        self.reconnect_attempts = max(0, int(reconnect_attempts))
        self.session_state = "DISCONNECTED"
        self.last_error: Optional[str] = None
        self._subscriptions: list[Mapping[str, str]] = []
        self._message_handler: Optional[Callable[[Any], None]] = None

    def authenticate(self) -> Mapping[str, Any]:
        profile = self.client.get_profile()
        if not isinstance(profile, Mapping) or profile.get("error") or not profile.get("dhanClientId"):
            self.session_state = "AUTHENTICATION_FAILED"
            self.last_error = "Dhan profile validation failed"
            raise LiveFoundationError(self.last_error)
        self.session_state = "AUTHENTICATED"
        self.last_error = None
        return dict(profile)

    def refresh_token(self) -> Mapping[str, Any]:
        response = self.client.renew_token()
        if not isinstance(response, Mapping) or not response.get("accessToken"):
            self.session_state = "TOKEN_REFRESH_FAILED"
            raise LiveFoundationError("Dhan token refresh failed")
        self.session_state = "AUTHENTICATED"
        return {"dhanClientId": response.get("dhanClientId"), "expiryTime": response.get("expiryTime")}

    def place_order(self, payload: Mapping[str, Any], risk_context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        self.config.assert_live_mutation_allowed()
        return self._checked(self.client.place_order(dict(payload), risk_context=risk_context), "order placement")

    def modify_order(self, order_id: str, payload: Mapping[str, Any], risk_context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        self.config.assert_live_mutation_allowed()
        return self._checked(self.client.modify_order(order_id, dict(payload), risk_context=risk_context), "order modification")

    def cancel_order(self, order_id: str, risk_context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        self.config.assert_live_mutation_allowed()
        return self._checked(self.client.cancel_order(order_id, risk_context=risk_context), "order cancellation")

    def order(self, order_id: str) -> Mapping[str, Any]:
        return self._checked(self.client.get_order(order_id), "order status")

    def order_by_correlation_id(self, correlation_id: str) -> Optional[Mapping[str, Any]]:
        response = self.client.get_order_by_correlation_id(correlation_id)
        if isinstance(response, Mapping) and not response.get("error") and response.get("orderId"):
            return dict(response)
        return None

    def orders(self) -> list[Mapping[str, Any]]:
        response = self.client.get_orders()
        if not isinstance(response, list):
            raise LiveFoundationError("Dhan order book unavailable")
        return [dict(item) for item in response if isinstance(item, Mapping)]

    def positions(self) -> list[Mapping[str, Any]]:
        response = self.client.get_positions()
        if not isinstance(response, list):
            raise LiveFoundationError("Dhan positions unavailable")
        return [dict(item) for item in response if isinstance(item, Mapping)]

    def connect_quotes(self, instruments: Iterable[Mapping[str, str]], handler: Callable[[Any], None]) -> None:
        if self.websocket is None:
            raise LiveFoundationError("Dhan websocket transport is not configured")
        self._subscriptions = [dict(item) for item in instruments]
        self._message_handler = lambda message: handler(
            DhanFeedDecoder.decode_full_quote(message) if isinstance(message, (bytes, bytearray)) else message
        )
        self._connect_websocket()

    def disconnect_quotes(self) -> None:
        if self.websocket is not None:
            self.websocket.close()
        self.session_state = "DISCONNECTED"

    def _connect_websocket(self) -> None:
        assert self.websocket is not None
        query = urlencode({"version": 2, "token": self.client.access_token, "clientId": self.client.client_id, "authType": 2})
        self.websocket.connect(f"wss://api-feed.dhan.co?{query}", self._message_handler or (lambda _: None), self._on_disconnect)
        self.websocket.subscribe(self._subscriptions)
        self.session_state = "CONNECTED"

    def _on_disconnect(self, error: Any) -> None:
        self.session_state = "RECONNECTING"
        self.last_error = type(error).__name__
        for _ in range(self.reconnect_attempts):
            try:
                self._connect_websocket()
                self.last_error = None
                return
            except Exception as reconnect_error:
                self.last_error = type(reconnect_error).__name__
        self.session_state = "RECONNECT_FAILED"

    @staticmethod
    def _checked(response: Any, operation: str) -> Mapping[str, Any]:
        if not isinstance(response, Mapping) or response.get("error") or response.get("errorCode"):
            raise LiveFoundationError(f"Dhan {operation} failed")
        return dict(response)


@dataclass(frozen=True)
class LiveQuote:
    exchange_segment: str
    security_id: str
    ltp: float
    bid: Optional[float]
    ask: Optional[float]
    timestamp: datetime
    received_at: datetime

    @property
    def spread(self) -> Optional[float]:
        return None if self.bid is None or self.ask is None else round(self.ask - self.bid, 8)

    def is_fresh(self, now: datetime, maximum_age_seconds: float) -> bool:
        return 0 <= (now - self.timestamp).total_seconds() <= maximum_age_seconds


class LiveQuoteProvider:
    """Canonical quote cache with duplicate suppression and freshness checks."""

    def __init__(self, *, maximum_age_seconds: float = 3.0, clock: Optional[Callable[[], datetime]] = None):
        self.maximum_age_seconds = float(maximum_age_seconds)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._quotes: Dict[tuple[str, str], LiveQuote] = {}
        self.duplicates_suppressed = 0

    def ingest(self, value: Mapping[str, Any]) -> bool:
        now = self.clock()
        timestamp = _datetime(value.get("timestamp"))
        quote = LiveQuote(
            exchange_segment=str(value["exchange_segment"]),
            security_id=str(value["security_id"]),
            ltp=float(value["ltp"]),
            bid=_optional_float(value.get("bid")),
            ask=_optional_float(value.get("ask")),
            timestamp=timestamp,
            received_at=now,
        )
        key = (quote.exchange_segment, quote.security_id)
        previous = self._quotes.get(key)
        if previous and (previous.ltp, previous.bid, previous.ask, previous.timestamp) == (quote.ltp, quote.bid, quote.ask, quote.timestamp):
            self.duplicates_suppressed += 1
            return False
        if previous and quote.timestamp < previous.timestamp:
            self.duplicates_suppressed += 1
            return False
        self._quotes[key] = quote
        return True

    def quote(self, exchange_segment: str, security_id: str, *, require_fresh: bool = True) -> LiveQuote:
        quote = self._quotes.get((str(exchange_segment), str(security_id)))
        if quote is None:
            raise StaleQuoteError("live quote is unavailable")
        if require_fresh and not quote.is_fresh(self.clock(), self.maximum_age_seconds):
            raise StaleQuoteError("live quote is stale")
        return quote


@dataclass(frozen=True)
class OrderExecutionPolicy:
    request_timeout_seconds: float = 10.0
    status_poll_attempts: int = 3
    mutation_attempts: int = 1

    def __post_init__(self) -> None:
        if self.request_timeout_seconds <= 0 or self.status_poll_attempts <= 0:
            raise ValueError("order timeout and polling attempts must be positive")
        if self.mutation_attempts != 1:
            raise ValueError("broker mutations permit exactly one submission attempt")


class LiveOrderEngine:
    """Durable correlation-id based exactly-once submission boundary."""

    TERMINAL_STATUSES = {"TRADED", "REJECTED", "CANCELLED", "EXPIRED"}

    def __init__(
        self,
        adapter: DhanBrokerAdapter,
        store: AtomicJsonStore,
        quotes: LiveQuoteProvider,
        policy: Optional[OrderExecutionPolicy] = None,
    ):
        self.adapter = adapter
        self.store = store
        self.quotes = quotes
        self.policy = policy or OrderExecutionPolicy()
        self._lock = RLock()
        if hasattr(self.adapter.client, "request_timeout"):
            self.adapter.client.request_timeout = self.policy.request_timeout_seconds

    def submit_action(
        self,
        action: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        risk_context: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        action = str(action).upper()
        if action not in {"BUY", "SELL", "EXIT"}:
            raise LiveFoundationError("order action must be BUY, SELL, or EXIT")
        request = dict(payload)
        transaction = str(request.get("transactionType") or "").upper()
        if action in {"BUY", "SELL"}:
            if transaction and transaction != action:
                raise LiveFoundationError("order action and transaction type disagree")
            request["transactionType"] = action
        elif transaction not in {"BUY", "SELL"}:
            raise LiveFoundationError("EXIT requires an explicit closing transaction type")
        return self.submit(request, idempotency_key=idempotency_key, risk_context=risk_context)

    def submit(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        risk_context: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        with self._lock:
            return self._submit_locked(payload, idempotency_key=idempotency_key, risk_context=risk_context)

    def _submit_locked(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        risk_context: Optional[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        self.adapter.config.assert_live_mutation_allowed()
        if not idempotency_key:
            raise LiveFoundationError("idempotency key is required")
        request = dict(payload)
        request["correlationId"] = idempotency_key
        self.quotes.quote(str(request["exchangeSegment"]), str(request["securityId"]))
        fingerprint = _fingerprint(request)
        document = self.store.read({"schema_version": 1, "orders": {}})
        records = document.setdefault("orders", {})
        existing = records.get(idempotency_key)
        if existing:
            if existing.get("fingerprint") != fingerprint:
                raise LiveFoundationError("idempotency key reused with different order")
            if existing.get("status") in {"SUBMITTED", "RECOVERED"}:
                return dict(existing["response"])
            raise LiveFoundationError("prior submission outcome is unresolved; reconciliation required")
        broker_existing = self.adapter.order_by_correlation_id(idempotency_key)
        if broker_existing:
            records[idempotency_key] = self._record(fingerprint, "RECOVERED", broker_existing)
            self.store.write(document)
            return broker_existing
        records[idempotency_key] = self._record(fingerprint, "SUBMITTING", None)
        self.store.write(document)
        try:
            response = self.adapter.place_order(request, risk_context=risk_context)
        except Exception:
            records[idempotency_key] = self._record(fingerprint, "UNKNOWN", None)
            self.store.write(document)
            raise
        records[idempotency_key] = self._record(fingerprint, "SUBMITTED", response)
        self.store.write(document)
        return response

    def modify(self, order_id: str, payload: Mapping[str, Any], *, operation_key: str, risk_context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        return self._mutate("MODIFY", operation_key, {"order_id": order_id, **dict(payload)}, lambda: self.adapter.modify_order(order_id, payload, risk_context))

    def cancel(self, order_id: str, *, operation_key: str, risk_context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        return self._mutate("CANCEL", operation_key, {"order_id": order_id}, lambda: self.adapter.cancel_order(order_id, risk_context))

    def poll_status(self, order_id: str) -> Mapping[str, Any]:
        last: Optional[Mapping[str, Any]] = None
        for _ in range(self.policy.status_poll_attempts):
            last = self.adapter.order(order_id)
            if str(last.get("orderStatus") or "").upper() in self.TERMINAL_STATUSES:
                return last
        if last is None:
            raise LiveFoundationError("order status polling produced no response")
        return {**dict(last), "pollingTimedOut": True}

    def _mutate(self, kind: str, key: str, request: Mapping[str, Any], operation: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]:
        with self._lock:
            self.adapter.config.assert_live_mutation_allowed()
            document = self.store.read({"schema_version": 1, "orders": {}, "operations": {}})
            operations = document.setdefault("operations", {})
            fingerprint = _fingerprint({"kind": kind, **dict(request)})
            existing = operations.get(key)
            if existing:
                if existing.get("fingerprint") != fingerprint:
                    raise LiveFoundationError("operation key reused with different mutation")
                if existing.get("status") == "SUBMITTED":
                    return dict(existing["response"])
                raise LiveFoundationError("prior mutation outcome is unresolved")
            operations[key] = self._record(fingerprint, "SUBMITTING", None)
            self.store.write(document)
            try:
                response = operation()
            except Exception:
                operations[key] = self._record(fingerprint, "UNKNOWN", None)
                self.store.write(document)
                raise
            operations[key] = self._record(fingerprint, "SUBMITTED", response)
            self.store.write(document)
            return response

    @staticmethod
    def _record(fingerprint: str, status: str, response: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
        return {"fingerprint": fingerprint, "status": status, "response": dict(response) if response else None}


class PositionReconciler:
    """Single-shot reconciliation primitive; scheduling belongs to a later phase."""

    def __init__(self, *, pause_strategy: Callable[[str], None], event_sink: Callable[[Mapping[str, Any]], None]):
        self.pause_strategy = pause_strategy
        self.event_sink = event_sink

    def reconcile(
        self,
        *,
        broker_positions: Iterable[Mapping[str, Any]],
        runtime_positions: Iterable[Mapping[str, Any]],
        dashboard_positions: Iterable[Mapping[str, Any]],
        journal_positions: Iterable[Mapping[str, Any]],
        replay_positions: Iterable[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        sources = {
            "broker": _positions(broker_positions),
            "runtime": _positions(runtime_positions),
            "dashboard": _positions(dashboard_positions),
            "journal": _positions(journal_positions),
            "replay": _positions(replay_positions),
        }
        baseline = sources["broker"]
        mismatches = sorted(name for name, value in sources.items() if value != baseline)
        if mismatches:
            reason = "POSITION_RECONCILIATION_MISMATCH:" + ",".join(mismatches)
            self.pause_strategy(reason)
            event = {"event": "PositionReconciliationFailed", "reason": reason, "fail_closed": True}
            self.event_sink(event)
            raise ReconciliationMismatch(reason)
        return {"status": "MATCHED", "position_count": len(baseline), "fail_closed": False}


class RestartRecovery:
    """Restores durable runtime state and reconciles uncertain broker intents."""

    def __init__(self, adapter: DhanBrokerAdapter, order_store: AtomicJsonStore, recovery_store: AtomicJsonStore):
        self.adapter = adapter
        self.order_store = order_store
        self.recovery_store = recovery_store

    def checkpoint(self, state: Mapping[str, Any]) -> None:
        required = {"targets", "stops", "trailing_stops", "journal", "replay", "processed_candles"}
        missing = required.difference(state)
        if missing:
            raise LiveFoundationError("recovery checkpoint is incomplete: " + ",".join(sorted(missing)))
        self.recovery_store.write({"schema_version": 1, **dict(state)})

    def recover(self) -> Mapping[str, Any]:
        state = self.recovery_store.read({})
        if state.get("schema_version") != 1:
            raise LiveFoundationError("recovery state is unavailable")
        orders = self.order_store.read({"schema_version": 1, "orders": {}})
        unresolved = []
        for correlation_id, record in orders.get("orders", {}).items():
            if record.get("status") not in {"SUBMITTING", "UNKNOWN"}:
                continue
            broker_order = self.adapter.order_by_correlation_id(correlation_id)
            if broker_order:
                record.update({"status": "RECOVERED", "response": dict(broker_order)})
            else:
                unresolved.append(correlation_id)
        self.order_store.write(orders)
        return {
            "state": state,
            "broker_positions": self.adapter.positions(),
            "broker_orders": self.adapter.orders(),
            "unresolved_submissions": unresolved,
            "trading_allowed": not unresolved,
        }


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("quote timestamp is required")
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    return number if number > 0 else None


def _positions(values: Iterable[Mapping[str, Any]]) -> tuple[tuple[str, str, int], ...]:
    normalized = []
    for item in values:
        security_id = str(item.get("securityId") or item.get("security_id") or item.get("instrument_id") or "")
        segment = str(item.get("exchangeSegment") or item.get("exchange_segment") or "")
        quantity = item.get("netQty", item.get("net_quantity", item.get("quantity", 0)))
        quantity = int(quantity or 0)
        if security_id and quantity:
            normalized.append((segment, security_id, quantity))
    return tuple(sorted(normalized))
