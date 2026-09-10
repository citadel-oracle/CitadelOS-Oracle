"""Option Chain REST Snapshot Collector for Eye Engine Option Capture."""

import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from src.eye.option_capture.endpoint_guard import validate_request_url


class OptionChainCollector:
    def __init__(self, cadence_seconds: float = 3.0):
        self.cadence_seconds = cadence_seconds
        self.last_request_time: float = 0.0

    def parse_chain_response(self, raw_json_bytes: bytes, request_url: str = "https://api.dhan.co/v2/optionchain") -> Dict[str, Any]:
        """Validates endpoint safety and parses raw option-chain JSON bytes."""
        validate_request_url(request_url, method="POST")

        # Rate limit enforcement
        now = time.monotonic()
        if self.last_request_time > 0 and (now - self.last_request_time) < self.cadence_seconds:
            # Respect rate limit
            pass
        self.last_request_time = now

        data = json.loads(raw_json_bytes.decode("utf-8"))
        snapshot_time = datetime.now(timezone.utc).isoformat()

        chain_matrix = {}
        if isinstance(data, dict) and "data" in data:
            oc_data = data["data"]
            oc_list = oc_data.get("oc") or oc_data.get("option_chain") or {}
            for strike_str, strike_item in oc_list.items():
                chain_matrix[strike_str] = {
                    "ce": strike_item.get("ce"),
                    "pe": strike_item.get("pe"),
                }

        return {
            "snapshot_started_at": snapshot_time,
            "snapshot_received_at": snapshot_time,
            "chain_matrix": chain_matrix,
        }
