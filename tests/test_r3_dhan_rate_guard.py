import time
import pytest
from unittest.mock import patch, MagicMock

from src.broker.dhan_client import DhanClient


def test_dhan_option_chain_rate_guard_spacing():
    """Prove that DhanClient.get_option_chain() strictly enforces >= 3.0s between consecutive REST requests."""
    client = DhanClient(access_token="mock_token", client_id="mock_id")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": "mock_chain"}
    mock_response.headers = {}

    with patch.object(client, "_post", return_value={"data": "mock_chain"}) as mock_post:
        # Reset state
        with DhanClient._option_chain_lock:
            DhanClient._last_option_chain_request_monotonic = 0.0

        t0 = time.monotonic()
        client.get_option_chain("IDX_I", 13, "2026-08-20")
        t1 = time.monotonic()
        client.get_option_chain("IDX_I", 13, "2026-08-20")
        t2 = time.monotonic()

        # First call is immediate
        assert (t1 - t0) < 0.5
        # Second call is delayed by rate guard to ensure >= 3.0s from first call
        assert (t2 - t0) >= 2.95
        assert mock_post.call_count == 2
