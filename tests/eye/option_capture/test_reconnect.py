"""E4A-E Test for Reconnect Epoch Management."""

import pytest
from src.eye.option_capture.websocket_collector import WebSocketCollector


def test_reconnect_increments_epoch():
    collector = WebSocketCollector("wss://api-feed.dhan.co")
    assert collector.connection_epoch == 1

    epoch2 = collector.increment_epoch()
    assert epoch2 == 2
    assert collector.connection_epoch == 2
