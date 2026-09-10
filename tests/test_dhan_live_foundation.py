from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import struct

import pytest

from src.broker.instrument_resolution import DhanOptionResolver, UnderlyingDefinition
from src.broker.live_foundation import (
    AtomicJsonStore,
    BrokerRuntimeConfig,
    DhanBrokerAdapter,
    DhanFeedDecoder,
    LiveExecutionDisabled,
    LiveFoundationError,
    LiveOrderEngine,
    LiveQuoteProvider,
    ModeIsolationPaths,
    OrderExecutionPolicy,
    PositionReconciler,
    ReconciliationMismatch,
    RestartRecovery,
    RuntimeMode,
    StaleQuoteError,
)
from src.paper_trading.contracts import ContractResolutionError


pytestmark = [pytest.mark.unit, pytest.mark.safety]
NOW = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)


class FakeClient:
    access_token = "secret-token"
    client_id = "client"

    def __init__(self):
        self.placed = []
        self.by_correlation = {}
        self.position_rows = []
        self.order_rows = []

    def get_profile(self):
        return {"dhanClientId": "client", "tokenValidity": "valid"}

    def renew_token(self):
        self.access_token = "new-secret-token"
        return {"accessToken": self.access_token, "dhanClientId": "client", "expiryTime": "later"}

    def place_order(self, payload, risk_context=None):
        self.placed.append(dict(payload))
        return {"orderId": f"order-{len(self.placed)}", "orderStatus": "PENDING"}

    def modify_order(self, order_id, payload, risk_context=None):
        return {"orderId": order_id, "orderStatus": "TRANSIT"}

    def cancel_order(self, order_id, risk_context=None):
        return {"orderId": order_id, "orderStatus": "CANCELLED"}

    def get_order(self, order_id):
        return {"orderId": order_id, "orderStatus": "PENDING"}

    def get_order_by_correlation_id(self, correlation_id):
        return self.by_correlation.get(correlation_id, {"error": "not found"})

    def get_positions(self):
        return self.position_rows

    def get_orders(self):
        return self.order_rows


class FakeWebSocket:
    def __init__(self, fail_connections=0):
        self.fail_connections = fail_connections
        self.connections = 0
        self.subscriptions = []
        self.on_disconnect = None

    def connect(self, url, on_message, on_disconnect):
        self.connections += 1
        if self.connections <= self.fail_connections:
            raise ConnectionError("offline")
        assert "token=secret-token" in url
        self.on_disconnect = on_disconnect

    def subscribe(self, instruments):
        self.subscriptions = list(instruments)

    def close(self):
        pass


def live_adapter(client=None, websocket=None):
    return DhanBrokerAdapter(
        client or FakeClient(),
        config=BrokerRuntimeConfig(RuntimeMode.LIVE, True, True),
        websocket=websocket,
    )


def fresh_quotes():
    provider = LiveQuoteProvider(clock=lambda: NOW)
    provider.ingest({"exchange_segment": "NSE_FNO", "security_id": "999", "ltp": 100, "bid": 99, "ask": 101, "timestamp": NOW})
    return provider


def order_payload():
    return {"exchangeSegment": "NSE_FNO", "securityId": "999", "transactionType": "BUY", "quantity": 25}


def test_live_is_disabled_by_default_before_client_mutation():
    client = FakeClient()
    adapter = DhanBrokerAdapter(client)
    with pytest.raises(LiveExecutionDisabled):
        adapter.place_order(order_payload())
    assert client.placed == []


def test_mode_paths_isolate_every_live_ledger(tmp_path):
    paper = ModeIsolationPaths(tmp_path, RuntimeMode.PAPER)
    live = ModeIsolationPaths(tmp_path, RuntimeMode.LIVE)
    assert {paper.orders, paper.recovery, paper.journal, paper.replay}.isdisjoint(
        {live.orders, live.recovery, live.journal, live.replay}
    )


def test_quote_duplicate_suppression_and_staleness():
    clock = [NOW]
    provider = LiveQuoteProvider(maximum_age_seconds=3, clock=lambda: clock[0])
    quote = {"exchange_segment": "NSE_FNO", "security_id": "999", "ltp": 100, "bid": 99, "ask": 101, "timestamp": NOW}
    assert provider.ingest(quote) is True
    assert provider.ingest(quote) is False
    assert provider.quote("NSE_FNO", "999").spread == 2
    clock[0] += timedelta(seconds=4)
    with pytest.raises(StaleQuoteError):
        provider.quote("NSE_FNO", "999")


def test_dhan_full_packet_decodes_ltp_bid_ask_and_exchange_timestamp():
    packet = bytearray(162)
    packet[0] = 8
    struct.pack_into("<H", packet, 1, len(packet))
    packet[3] = 2
    struct.pack_into("<I", packet, 4, 999)
    struct.pack_into("<f", packet, 8, 100.5)
    struct.pack_into("<I", packet, 14, int(NOW.timestamp()))
    struct.pack_into("<f", packet, 74, 100.0)
    struct.pack_into("<f", packet, 78, 101.0)
    quote = DhanFeedDecoder.decode_full_quote(bytes(packet))
    assert quote == {
        "exchange_segment": "NSE_FNO",
        "security_id": "999",
        "ltp": 100.5,
        "bid": 100.0,
        "ask": 101.0,
        "timestamp": NOW,
    }


def test_exactly_once_order_submission_survives_engine_restart(tmp_path):
    client = FakeClient()
    adapter = live_adapter(client)
    store = AtomicJsonStore(tmp_path / "live" / "orders.json")
    first = LiveOrderEngine(adapter, store, fresh_quotes()).submit(order_payload(), idempotency_key="runtime:candle:signal")
    second = LiveOrderEngine(adapter, store, fresh_quotes()).submit(order_payload(), idempotency_key="runtime:candle:signal")
    assert first == second
    assert len(client.placed) == 1


def test_exactly_once_suppresses_concurrent_duplicate_submission(tmp_path):
    client = FakeClient()
    engine = LiveOrderEngine(live_adapter(client), AtomicJsonStore(tmp_path / "orders.json"), fresh_quotes())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: engine.submit(order_payload(), idempotency_key="concurrent"), range(4)))
    assert len(client.placed) == 1
    assert len({item["orderId"] for item in results}) == 1


def test_idempotency_key_conflict_fails_closed(tmp_path):
    engine = LiveOrderEngine(live_adapter(), AtomicJsonStore(tmp_path / "orders.json"), fresh_quotes())
    engine.submit(order_payload(), idempotency_key="same")
    with pytest.raises(LiveFoundationError, match="different order"):
        engine.submit({**order_payload(), "quantity": 50}, idempotency_key="same")


def test_buy_sell_exit_modify_cancel_and_status_lifecycle(tmp_path):
    client = FakeClient()
    statuses = iter(
        [
            {"orderId": "order-1", "orderStatus": "PENDING"},
            {"orderId": "order-1", "orderStatus": "TRADED"},
        ]
    )
    client.get_order = lambda _: next(statuses)
    engine = LiveOrderEngine(
        live_adapter(client),
        AtomicJsonStore(tmp_path / "orders.json"),
        fresh_quotes(),
        OrderExecutionPolicy(status_poll_attempts=2),
    )
    assert engine.submit_action("BUY", order_payload(), idempotency_key="buy")["orderStatus"] == "PENDING"
    assert engine.submit_action("EXIT", {**order_payload(), "transactionType": "SELL"}, idempotency_key="exit")["orderStatus"] == "PENDING"
    assert engine.modify("order-1", {"quantity": 25}, operation_key="modify-1")["orderStatus"] == "TRANSIT"
    assert engine.cancel("order-1", operation_key="cancel-1")["orderStatus"] == "CANCELLED"
    assert engine.poll_status("order-1")["orderStatus"] == "TRADED"


def test_unknown_submission_is_not_retried(tmp_path):
    client = FakeClient()

    def fail(payload, risk_context=None):
        raise TimeoutError("unknown broker outcome")

    client.place_order = fail
    engine = LiveOrderEngine(live_adapter(client), AtomicJsonStore(tmp_path / "orders.json"), fresh_quotes())
    with pytest.raises(TimeoutError):
        engine.submit(order_payload(), idempotency_key="unknown")
    with pytest.raises(LiveFoundationError, match="unresolved"):
        engine.submit(order_payload(), idempotency_key="unknown")


def test_broker_reconnect_restores_subscriptions():
    websocket = FakeWebSocket()
    adapter = live_adapter(websocket=websocket)
    instruments = [{"ExchangeSegment": "NSE_FNO", "SecurityId": "999"}]
    adapter.connect_quotes(instruments, lambda _: None)
    websocket.fail_connections = 1
    websocket.on_disconnect("network")
    assert adapter.session_state == "CONNECTED"
    assert websocket.connections == 2
    assert websocket.subscriptions == instruments


def test_position_mismatch_pauses_strategy_and_emits_diagnostic():
    pauses, events = [], []
    reconciler = PositionReconciler(pause_strategy=pauses.append, event_sink=events.append)
    broker = [{"exchangeSegment": "NSE_FNO", "securityId": "999", "netQty": 25}]
    with pytest.raises(ReconciliationMismatch):
        reconciler.reconcile(
            broker_positions=broker,
            runtime_positions=[],
            dashboard_positions=broker,
            journal_positions=broker,
            replay_positions=broker,
        )
    assert pauses and events[0]["fail_closed"] is True


def test_restart_recovery_restores_state_and_recovers_correlation(tmp_path):
    client = FakeClient()
    client.by_correlation["uncertain"] = {"orderId": "broker-order", "orderStatus": "PENDING"}
    client.position_rows = [{"securityId": "999", "netQty": 25}]
    client.order_rows = [{"orderId": "broker-order", "orderStatus": "PENDING"}]
    orders = AtomicJsonStore(tmp_path / "live" / "orders.json")
    recovery = AtomicJsonStore(tmp_path / "live" / "recovery.json")
    orders.write({"schema_version": 1, "orders": {"uncertain": {"fingerprint": "x", "status": "UNKNOWN", "response": None}}})
    service = RestartRecovery(live_adapter(client), orders, recovery)
    state = {"targets": {}, "stops": {}, "trailing_stops": {}, "journal": [], "replay": [], "processed_candles": ["c1"]}
    service.checkpoint(state)
    result = service.recover()
    assert result["trading_allowed"] is True
    assert result["state"]["processed_candles"] == ["c1"]
    assert orders.read({})["orders"]["uncertain"]["status"] == "RECOVERED"


class FakeMaster:
    def resolve(self, **kwargs):
        return {"security_id": str(kwargs["security_id"]), "lot_size": 25, "source": "DHAN_INSTRUMENT_MASTER", "exchange_segment": "NSE_FNO"}

    def _rows(self, underlying):
        return [{"SM_EXPIRY_DATE": "2026-07-30", "EXPIRY_FLAG": "M"}]

    @staticmethod
    def _text(row, *keys):
        return next((row[key] for key in keys if row.get(key)), None)


class FakeOptionClient:
    def get_option_expiries(self, segment, security_id):
        return {"data": ["2026-07-16", "2026-07-23", "2026-07-30", "2026-08-06"]}

    def get_option_chain(self, segment, security_id, expiry):
        return {
            "data": {
                "last_price": 24110,
                "oc": {
                    "24000.000000": {"ce": {"security_id": 1, "last_price": 150}},
                    "24100.000000": {"ce": {"security_id": 2, "last_price": 100, "top_ask_price": 101, "top_bid_price": 99}},
                    "24200.000000": {"ce": {"security_id": 3, "last_price": 60}},
                },
            }
        }


def test_instrument_resolution_atm_offset_and_expiry_rollover():
    resolver = DhanOptionResolver(FakeOptionClient(), FakeMaster(), clock=lambda: date(2026, 7, 14))
    weekly = resolver.resolve(underlying="NIFTY", option_type="CE", strike_offset=1)
    monthly = resolver.resolve(underlying="NIFTY", option_type="CE", expiry_kind="MONTHLY")
    assert (weekly.strike, weekly.expiry, weekly.security_id) == (24200, "2026-07-16", "3")
    assert monthly.expiry == "2026-07-30"


def test_future_underlying_requires_authoritative_registry_not_guessing():
    resolver = DhanOptionResolver(FakeOptionClient(), FakeMaster())
    with pytest.raises(ContractResolutionError, match="authoritative Dhan metadata"):
        resolver.resolve(underlying="FINNIFTY", option_type="CE")
    configured = DhanOptionResolver(
        FakeOptionClient(),
        FakeMaster(),
        underlyings={"FINNIFTY": UnderlyingDefinition("FINNIFTY", "27")},
        clock=lambda: date(2026, 7, 14),
    )
    assert configured.resolve(underlying="FINNIFTY", option_type="CE").underlying == "FINNIFTY"


def test_credentials_are_never_persisted(tmp_path):
    store = AtomicJsonStore(tmp_path / "state.json")
    store.write({"access_token": "secret", "nested": {"api_secret": "secret", "safe": True}})
    serialized = (tmp_path / "state.json").read_text()
    assert "secret" not in serialized
    assert store.read({}) == {"nested": {"safe": True}}
