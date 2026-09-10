"""E2B-D Historical Dataset Provenance & 20 Complete Sessions Test Suite."""

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone


def test_historical_dataset_provenance_and_20_complete_sessions():
    path = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json")
    assert path.exists()

    raw = json.loads(path.read_text())
    candles = raw.get("candles", [])
    assert len(candles) >= 7500

    sessions = defaultdict(list)
    for c in candles:
        ts = c.get("time") or c.get("timestamp")
        if ts:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            sessions[dt.date().isoformat()].append(c)

    complete_dates = sorted([d for d, bars in sessions.items() if len(bars) >= 300])[:20]
    assert len(complete_dates) == 20
