"""WebSocket Fast-Lane Packet Collector for Eye Engine Option Capture."""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from src.eye.option_capture.endpoint_guard import validate_request_url
from src.eye.option_capture.packet_decoder import DhanPacketDecoder


class WebSocketCollector:
    def __init__(self, feed_url: str = "wss://api-feed.dhan.co"):
        validate_request_url(feed_url)
        self.feed_url = feed_url
        self.connection_epoch: int = 1
        self.subscribed_security_ids: List[str] = []

    def increment_epoch(self) -> int:
        """Increments and returns the connection epoch on reconnect."""
        self.connection_epoch += 1
        return self.connection_epoch

    def chunk_subscriptions(self, security_ids: List[str], chunk_size: int = 100) -> List[List[str]]:
        """Splits subscription list into batches of maximum chunk_size (100 for Dhan)."""
        self.subscribed_security_ids = sorted(security_ids)
        return [security_ids[i:i + chunk_size] for i in range(0, len(security_ids), chunk_size)]

    def parse_packet(self, raw_bytes: bytes) -> Optional[Dict[str, Any]]:
        """Decodes raw WebSocket binary payload using DhanPacketDecoder."""
        return DhanPacketDecoder.decode_packet(raw_bytes)
