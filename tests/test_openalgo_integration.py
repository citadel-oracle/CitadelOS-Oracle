import pytest
from src.broker.live_foundation import LiveFoundationError, BrokerRuntimeConfig, RuntimeMode
from src.broker.openalgo_client import OpenAlgoClient
from src.broker.openalgo_adapter import OpenAlgoBrokerAdapter

class FakeOpenAlgoClient:
    def __init__(self):
        self.analyzer_mode = True
        self.mode = "analyze"
        self.orders_list = []
        self.positions_list = []
        self.placed_orders = []
        self.api_key = "aa6d111516a9ab0a4aa6d98cc2f645dbca57d2d8da2f666b4e22402078d317ef"

    def get_analyzer_status(self):
        return {"analyze_mode": self.analyzer_mode, "mode": self.mode}

    def toggle_analyzer(self, mode: bool):
        self.analyzer_mode = mode
        self.mode = "analyze" if mode else "live"
        return {"status": "success", "analyze_mode": self.analyzer_mode}

    def place_order(self, order_payload):
        self.placed_orders.append(order_payload)
        return {"status": "success", "orderid": f"openalgo-order-{len(self.placed_orders)}"}

    def modify_order(self, order_payload):
        return {"status": "success", "orderid": order_payload["orderid"]}

    def cancel_order(self, order_payload):
        return {"status": "success", "orderid": order_payload["orderid"]}

    def get_positions(self):
        return {"data": self.positions_list, "status": "success"}

    def get_orders(self):
        return {"data": {"orders": self.orders_list}, "status": "success"}

class FakeDhanAdapter:
    def __init__(self):
        self.quotes_connected = False
        self.session_state = "CONNECTED"

    def connect_quotes(self, instruments, handler):
        self.quotes_connected = True

    def disconnect_quotes(self):
        self.quotes_connected = False

def test_openalgo_adapter_auth_success():
    client = FakeOpenAlgoClient()
    dhan = FakeDhanAdapter()
    adapter = OpenAlgoBrokerAdapter(dhan, client)
    
    res = adapter.authenticate()
    assert res["status"] == "CONNECTED"
    assert adapter.session_state == "AUTHENTICATED"

def test_openalgo_adapter_auth_fail_closed_if_live():
    client = FakeOpenAlgoClient()
    client.analyzer_mode = False
    client.mode = "live"
    dhan = FakeDhanAdapter()
    adapter = OpenAlgoBrokerAdapter(dhan, client)
    
    # Must fail closed with error, instead of automatically toggling
    with pytest.raises(LiveFoundationError) as exc:
        adapter.authenticate()
    assert "NOT running in Analyzer Mode" in str(exc.value)
    assert adapter.session_state == "AUTHENTICATION_FAILED"

def test_openalgo_adapter_auth_fail_closed_missing_key():
    client = FakeOpenAlgoClient()
    client.api_key = ""
    dhan = FakeDhanAdapter()
    with pytest.raises(LiveFoundationError) as exc:
        OpenAlgoBrokerAdapter(dhan, client)
    assert "Empty or placeholder" in str(exc.value)

def test_openalgo_adapter_auth_fail_closed_placeholder_key():
    client = FakeOpenAlgoClient()
    client.api_key = "dummy_analyzer_key"
    dhan = FakeDhanAdapter()
    with pytest.raises(LiveFoundationError) as exc:
        OpenAlgoBrokerAdapter(dhan, client)
    assert "Empty or placeholder" in str(exc.value)

def test_openalgo_adapter_quotes_delegation():
    client = FakeOpenAlgoClient()
    dhan = FakeDhanAdapter()
    adapter = OpenAlgoBrokerAdapter(dhan, client)
    
    adapter.connect_quotes([], lambda x: None)
    assert dhan.quotes_connected is True
    
    adapter.disconnect_quotes()
    assert dhan.quotes_connected is False

def test_openalgo_adapter_zero_startup_orders():
    client = FakeOpenAlgoClient()
    dhan = FakeDhanAdapter()
    adapter = OpenAlgoBrokerAdapter(dhan, client)
    
    # Authenticating/initializing the adapter must not trigger any order placements
    adapter.authenticate()
    assert len(client.placed_orders) == 0

def test_openalgo_adapter_restart_persistence():
    client = FakeOpenAlgoClient()
    client.orders_list = [
        {
            "orderid": "26072402831148",
            "order_status": "complete",
            "strategy": "Citadel:corr-smoke-validation-999",
            "symbol": "RELIANCE",
            "price": 2400.0,
            "quantity": 1,
            "action": "BUY"
        }
    ]
    dhan = FakeDhanAdapter()
    adapter = OpenAlgoBrokerAdapter(dhan, client)
    
    # Retrieve orders list and verify they map and persist correctly
    orders = adapter.orders()
    assert len(orders) == 1
    assert orders[0]["orderId"] == "26072402831148"
    assert orders[0]["correlationId"] == "corr-smoke-validation-999"
    assert orders[0]["tradingSymbol"] == "RELIANCE"

