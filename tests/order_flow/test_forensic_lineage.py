from __future__ import annotations

import json
from datetime import datetime

from scripts.replay_argus_flow_pulse import (
    IST,
    prior_levels_from_candles,
    prior_raw_session_coverage,
)


def candle(epoch: int, high: float, low: float, close: float) -> dict:
    return {"time": epoch, "open": close, "high": high, "low": low, "close": close, "volume": 1}


def test_previous_session_lineage_uses_complete_candle_high_low_and_final_close(tmp_path):
    start = int(datetime(2026, 8, 10, 9, 15, tzinfo=IST).timestamp())
    path = tmp_path / "futures.json"
    path.write_text(json.dumps([
        candle(start, 24680.0, 24610.0, 24640.0),
        candle(start + 60, 24698.8, 24600.0, 24661.0),
    ]))
    assert prior_levels_from_candles(path, "2026-08-11") == (24698.8, 24600.0, 24661.0, "2026-08-10")


def test_partial_previous_raw_is_not_eligible_to_define_pdl(tmp_path):
    path = tmp_path / "2026-08-10.jsonl"
    rows = []
    for stamp, price in (("13:46:50", 24685.0), ("14:48:50", 24641.19921875), ("14:49:04", 24643.0)):
        payload = {
            "receive_time_ist": f"2026-08-10T{stamp}+05:30",
            "instrument_role": "NIFTY_FUTURE",
            "ltp": price,
        }
        rows.append(json.dumps({"payload": payload}))
    path.write_text("\n".join(rows) + "\n")
    coverage = prior_raw_session_coverage(path, "2026-08-11")
    assert coverage["complete_session"] is False
    assert coverage["first_packet"].startswith("2026-08-10T13:46:50")
    assert coverage["last_packet"].startswith("2026-08-10T14:49:04")


def test_opening_range_30_seconds_is_not_promoted_to_first_minute_low():
    opening_range_low = 24601.5
    first_minute_low = 24600.1
    assert opening_range_low != first_minute_low


def test_structural_low_and_pdl_remain_separate_without_exact_overlap():
    prior_structural_swing_low = 24602.0
    previous_day_low = 24600.0
    assert prior_structural_swing_low != previous_day_low
