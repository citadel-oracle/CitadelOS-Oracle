"""E4A-E Test for Instrument Master Snapshot Manager."""

import json
from datetime import datetime, timezone
import pytest
from src.eye.option_capture.instrument_snapshot import InstrumentSnapshotManager


def test_instrument_snapshot_parsing():
    data = [
        {"security_id": "43210", "trading_symbol": "NIFTY-26AUG2026-24500-CE", "underlying": "NIFTY", "option_type": "CE", "strike": 24500.0, "expiry": "2026-08-26", "lot_size": 25, "tick_size": 0.05},
        {"security_id": "43211", "trading_symbol": "NIFTY-26AUG2026-24500-PE", "underlying": "NIFTY", "option_type": "PE", "strike": 24500.0, "expiry": "2026-08-26", "lot_size": 25, "tick_size": 0.05},
        {"security_id": "99999", "trading_symbol": "BANKNIFTY-26AUG2026-50000-CE", "underlying": "BANKNIFTY", "option_type": "CE", "strike": 50000.0, "expiry": "2026-08-26", "lot_size": 15, "tick_size": 0.05},
    ]
    raw_bytes = json.dumps(data).encode("utf-8")
    mgr = InstrumentSnapshotManager(raw_bytes)
    now = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)

    valid, excluded = mgr.parse_nifty_options(now)

    assert len(valid) == 2
    assert mgr.fingerprint != ""
