"""E4A-E Test for Read-Only Endpoint Guard & Forbidden Order Blocking."""

import pytest
from src.eye.option_capture.endpoint_guard import validate_request_url, EndpointSafetyError, redact_headers


def test_forbidden_order_endpoint_blocked():
    forbidden_urls = [
        "https://api.dhan.co/v2/orders/place",
        "https://api.dhan.co/v2/orders/modify/123",
        "https://api.dhan.co/v2/orders/cancel/123",
        "https://api.dhan.co/v2/positions/convert",
        "https://api.dhan.co/v2/super-orders",
    ]
    for url in forbidden_urls:
        with pytest.raises(EndpointSafetyError):
            validate_request_url(url, method="POST")


def test_allowlisted_read_only_endpoint_passes():
    allowed_urls = [
        "https://api.dhan.co/v2/optionchain",
        "https://api.dhan.co/v2/optionchain/expirylist",
        "https://api.dhan.co/v2/marketfeed/quote",
        "wss://api-feed.dhan.co",
    ]
    for url in allowed_urls:
        validate_request_url(url, method="POST")


def test_secret_headers_redacted():
    headers = {
        "access-token": "secret_abc_123",
        "client-id": "11002233",
        "Content-Type": "application/json",
    }
    redacted = redact_headers(headers)
    assert redacted["access-token"] == "[REDACTED_SECRET]"
    assert redacted["client-id"] == "[REDACTED_SECRET]"
    assert redacted["Content-Type"] == "application/json"
