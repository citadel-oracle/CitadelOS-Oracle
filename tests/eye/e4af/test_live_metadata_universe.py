"""E4A-F Test for Dynamic Live Metadata Universe Discovery."""

from datetime import datetime, date, timezone
import pytest
from src.eye.option_capture.instrument_snapshot import InstrumentSnapshotManager
from src.eye.option_capture.universe import UniverseManager, ResearchCoveragePolicy


def test_live_metadata_universe_discovery():
    sample_json = [
        {"security_id": "43210", "trading_symbol": "NIFTY-13AUG2026-24500-CE", "underlying": "NIFTY", "option_type": "CE", "strike": 24500.0, "expiry": "2026-08-13", "lot_size": 25, "tick_size": 0.05},
        {"security_id": "43211", "trading_symbol": "NIFTY-13AUG2026-24500-PE", "underlying": "NIFTY", "option_type": "PE", "strike": 24500.0, "expiry": "2026-08-13", "lot_size": 25, "tick_size": 0.05},
        {"security_id": "99999", "trading_symbol": "BANKNIFTY-13AUG2026-50000-CE", "underlying": "BANKNIFTY", "option_type": "CE", "strike": 50000.0, "expiry": "2026-08-13", "lot_size": 15, "tick_size": 0.05},
    ]
    import json
    mgr = InstrumentSnapshotManager(json.dumps(sample_json).encode("utf-8"))
    now = datetime(2026, 8, 7, 10, 10, tzinfo=timezone.utc)

    contracts, excluded = mgr.parse_nifty_options(now)

    assert len(contracts) == 2
    assert "OPTCONTRACT:NSE:NSE_FO:43210:NSE:NIFTY:UNDERLYING_INDEX:2026-08-13:2450000:CE:OPTIDX" in contracts
