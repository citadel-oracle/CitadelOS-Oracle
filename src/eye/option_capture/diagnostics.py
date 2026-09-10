"""Capture Diagnostics & Event Logger for Eye Engine Option Capture."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any


class CaptureDiagnostics:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.diag_file = session_dir / "capture_diagnostics.jsonl"
        self.event_count = 0

    def log_event(self, event_type: str, severity: str, details: Dict[str, Any]) -> Dict[str, Any]:
        """Logs a diagnostic event (e.g. RATE_LIMITED, PACKET_DROPPED, RECONNECT_EVENT)."""
        self.event_count += 1
        rec = {
            "event_id": f"DIAG:{self.event_count}",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "severity": severity,
            "details": details,
        }
        with open(self.diag_file, "a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec
