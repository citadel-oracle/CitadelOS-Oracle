"""E4A-D Test for Explicit Session Selection Truth."""

import json
from pathlib import Path
from datetime import datetime, timezone
import pytest


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "e4ad"


def test_twenty_complete_sessions_selection():
    snap_path = FIXTURE_DIR / "vob_1m_candles_snapshot_20260806.json"
    raw = json.loads(snap_path.read_text())
    candles = raw["candles"]

    session_map = {}
    for c in candles:
        dt = datetime.fromtimestamp(c["time"], tz=timezone.utc).date()
        session_map[dt] = session_map.get(dt, 0) + 1

    complete_dates = sorted([d for d, cnt in session_map.items() if cnt == 375])
    assert len(complete_dates) >= 20

    sel_dates = complete_dates[:20]
    total_selected_candles = sum(session_map[d] for d in sel_dates)
    assert total_selected_candles == 7500  # 20 * 375
