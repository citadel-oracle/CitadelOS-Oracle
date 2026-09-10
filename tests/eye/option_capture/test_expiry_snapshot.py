"""E4A-E Test for Expiry List Snapshot Manager."""

import json
from datetime import date
import pytest
from src.eye.option_capture.expiry_snapshot import ExpirySnapshotManager


def test_expiry_snapshot_parsing():
    data = {"status": "success", "data": ["2026-08-13", "2026-08-20", "2026-08-27"]}
    raw_bytes = json.dumps(data).encode("utf-8")
    mgr = ExpirySnapshotManager(raw_bytes)
    expiries = mgr.parse_expiries()

    assert len(expiries) == 3
    assert expiries[0] == date(2026, 8, 13)
