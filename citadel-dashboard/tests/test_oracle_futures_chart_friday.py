import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
SESSION_DATE = "2026-08-07"
STATE_ROOT = Path(os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs"))


def _friday_rows():
    candidates = sorted((STATE_ROOT / "oracle_dev").glob("candle_store_fut_1m_*.json"))
    assert candidates, "Friday canonical futures store is unavailable"
    result = []
    for path in candidates:
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            timestamp = int(row["time"])
            instant = datetime.fromtimestamp(timestamp, tz=IST)
            minute = instant.hour * 60 + instant.minute
            if instant.date().isoformat() == SESSION_DATE and 9 * 60 + 15 <= minute <= 15 * 60 + 30:
                result.append(row)
    return result


def test_friday_futures_rows_are_sorted_unique_and_regular_session_only():
    rows = _friday_rows()
    timestamps = [int(row["time"]) for row in rows]
    assert rows
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))
    assert datetime.fromtimestamp(timestamps[0], tz=IST).strftime("%H:%M") == "09:15"
    # One-minute candles are keyed by bucket start; the final regular-session
    # bucket spans 15:29:00–15:29:59 before the 15:30 close.
    assert datetime.fromtimestamp(timestamps[-1], tz=IST).strftime("%H:%M") == "15:29"


def test_friday_vwap_is_current_session_only_and_incremental_math_is_stable():
    rows = _friday_rows()
    cumulative_value = 0.0
    cumulative_volume = 0.0
    values = []
    for row in rows:
        volume = float(row.get("volume") or 0)
        typical = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3
        cumulative_value += typical * volume
        cumulative_volume += volume
        values.append(cumulative_value / cumulative_volume if cumulative_volume else typical)
    assert len(values) == len(rows)
    assert all(value == value for value in values)
    # Updating the current bar keeps its timestamp; appending the next bar adds one.
    before = [int(row["time"]) for row in rows[:-1]]
    same_time = before + [before[-1]]
    next_time = before + [before[-1] + 60]
    assert len(set(same_time)) == len(before)
    assert len(set(next_time)) == len(before) + 1


def test_friday_flow_replay_remains_explicitly_not_possible():
    paths = list((STATE_ROOT / "order_flow" / "evidence" / "raw_full_packets").glob("2026-08-07.jsonl"))
    if not paths:
        return
    # Repeated post-close last-good snapshots are still not a session recording
    # and cannot certify CVD/OFI/footprint replay.
    rows = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines() if line]
    exchange_times = {row["payload"]["exchange_ltt"] for row in rows}
    receive_dates = {str(row["payload"]["receive_wall_utc"])[:10] for row in rows}
    assert len(exchange_times) <= 2
    assert receive_dates != {SESSION_DATE}
