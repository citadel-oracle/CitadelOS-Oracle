from unittest.mock import Mock

import pytest

from src.broker.dhan_client import BrokerMutationBlockedError, DhanClient


pytestmark = [pytest.mark.unit, pytest.mark.safety]


def make_disabled_client():
    return DhanClient(
        access_token="test-access-token",
        client_id="test-client-id",
    )


def test_place_order_is_blocked_before_network(monkeypatch):
    post = Mock()
    monkeypatch.setattr("src.broker.dhan_client.requests.post", post)
    client = make_disabled_client()

    with pytest.raises(BrokerMutationBlockedError, match="live_trading_enabled must be true"):
        client.place_order({"securityId": "13"})

    post.assert_not_called()


def test_cancel_order_is_blocked_before_network(monkeypatch):
    delete = Mock()
    monkeypatch.setattr("src.broker.dhan_client.requests.delete", delete)
    client = make_disabled_client()

    with pytest.raises(BrokerMutationBlockedError, match="DELETE /orders/test-order"):
        client.cancel_order("test-order")

    delete.assert_not_called()


def test_generic_order_post_cannot_bypass_guard(monkeypatch):
    post = Mock()
    monkeypatch.setattr("src.broker.dhan_client.requests.post", post)
    client = make_disabled_client()

    with pytest.raises(BrokerMutationBlockedError, match="POST /orders"):
        client._post("/orders", {"securityId": "13"})

    post.assert_not_called()


@pytest.mark.parametrize(
    ("method", "endpoint", "request_name"),
    [
        ("PUT", "/orders/test-order", "put"),
        ("DELETE", "/orders/test-order", "delete"),
        ("PATCH", "/orders/test-order", "patch"),
    ],
)
def test_future_mutation_methods_cross_same_guard(monkeypatch, method, endpoint, request_name):
    request_mock = Mock()
    monkeypatch.setattr(f"src.broker.dhan_client.requests.{request_name}", request_mock)
    client = make_disabled_client()

    with pytest.raises(BrokerMutationBlockedError, match=f"{method} {endpoint}"):
        client._request(method, endpoint, {"quantity": 1})

    request_mock.assert_not_called()


def test_read_only_quote_post_remains_available(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "data": {
            "IDX_I": {
                "13": {
                    "last_price": 24100.0,
                    "ohlc": {
                        "open": 24000.0,
                        "close": 23950.0,
                        "high": 24200.0,
                        "low": 23850.0,
                    },
                }
            }
        },
        "status": "success",
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("src.broker.dhan_client.requests.post", post)
    client = make_disabled_client()

    quote = client.get_quote("IDX_I", "13")

    assert quote["ltp"] == 24100.0
    assert quote["updated"] == "LIVE"
    assert quote["change_percent"] == 0.63
    post.assert_called_once()


def test_missing_live_setting_fails_closed(monkeypatch):
    post = Mock()
    monkeypatch.setattr("src.broker.dhan_client.requests.post", post)
    monkeypatch.setattr(DhanClient, "_load_settings", staticmethod(lambda: {}))
    client = DhanClient(
        access_token="test-access-token",
        client_id="test-client-id",
    )

    with pytest.raises(BrokerMutationBlockedError, match="Dhan broker mutation blocked"):
        client.place_order({"securityId": "13"})

    post.assert_not_called()
