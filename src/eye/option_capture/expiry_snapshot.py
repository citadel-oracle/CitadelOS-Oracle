"""Expiry List Snapshot Manager for Eye Engine Option Capture."""

import json
import hashlib
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional


class ExpirySnapshotManager:
    def __init__(self, raw_metadata: bytes):
        self.raw_bytes = raw_metadata
        self.fingerprint = hashlib.sha256(raw_metadata).hexdigest()
        self.expiry_dates: List[date] = []

    def parse_expiries(self) -> List[date]:
        """Parses expiry list response, extracting sorted list of valid expiry dates."""
        self.expiry_dates.clear()
        try:
            data = json.loads(self.raw_bytes.decode("utf-8"))
        except Exception:
            data = []

        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        raw_dates = set()
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    raw_dates.add(item)
                elif isinstance(item, dict) and "expiry" in item:
                    raw_dates.add(item["expiry"])

        parsed = []
        for d_str in raw_dates:
            try:
                dt = datetime.strptime(d_str, "%Y-%m-%d").date()
                parsed.append(dt)
            except Exception:
                pass

        self.expiry_dates = sorted(parsed)
        return self.expiry_dates

    def filter_expiry_horizon(self, start_date: date, horizon_days: int) -> List[date]:
        """Filters expiries within start_date and start_date + horizon_days."""
        max_date = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        max_date_plus = (max_date + timedelta(days=horizon_days)).date()
        return [d for d in self.expiry_dates if start_date <= d <= max_date_plus]
