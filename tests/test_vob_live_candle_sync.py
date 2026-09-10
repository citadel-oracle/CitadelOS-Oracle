from datetime import datetime
import json
from zoneinfo import ZoneInfo

from src.vob.backfill import mark_vob_evaluated, sync_current_session
from src.vob.engine import NiftyVOBEngine


IST = ZoneInfo("Asia/Kolkata")


class FakeDhan:
    def __init__(self, candles):
        self.candles = candles
        self.calls = 0

    def get_intraday_candles(self, **_kwargs):
        self.calls += 1
        return {"success": True, "candles": self.candles}


def test_live_sync_appends_only_completed_nifty_spot_candles(tmp_path):
    def candle(hour, minute, close):
        stamp = datetime(2026, 7, 22, hour, minute, tzinfo=IST).timestamp()
        return {"time": stamp, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 0}

    path = tmp_path / "vob_1m_candles.json"
    path.write_text(json.dumps({"candles": [candle(9, 15, 24000)]}))
    client = FakeDhan([candle(9, 15, 24000), candle(9, 16, 24001), candle(9, 17, 24002), candle(9, 18, 24003)])

    result = sync_current_session(path, client, now=datetime(2026, 7, 22, 9, 18, 30, tzinfo=IST), minimum_retry_seconds=0)
    persisted = json.loads(path.read_text())

    assert result["added"] == 2
    assert len(persisted["candles"]) == 3
    assert persisted["cursor"]["latest_persisted_1m"] == "2026-07-22T09:17:00+05:30"
    assert persisted["cursor"]["runtime_status"] == "CATCHING_UP"
    assert datetime.fromtimestamp(persisted["candles"][-1]["time"], tz=IST).minute == 17
    assert client.calls == 1

    projection = NiftyVOBEngine().ingest_1m_candles(persisted["candles"], current_nifty_price=24002)
    assert projection["timeframes"]["3m"]["evaluated_through"] == "2026-07-22T09:15:00+05:30"
    assert projection["timeframes"]["5m"].get("evaluated_through") is None
    cursor = mark_vob_evaluated(path, datetime(2026, 7, 22, 9, 17, tzinfo=IST))
    assert cursor["runtime_status"] == "LIVE"


def test_0940_cold_start_is_exact_and_restart_safe(tmp_path):
    def candle(hour, minute, close=24000):
        stamp = datetime(2026, 7, 22, hour, minute, tzinfo=IST).timestamp()
        return {"time": stamp, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 0}

    path = tmp_path / "vob_1m_candles.json"
    invalid = candle(18, 43)
    path.write_text(json.dumps({"candles": [invalid]}))
    session = [candle(9, 15 + offset, 24000 + offset) if 15 + offset < 60 else candle(10, 15 + offset - 60, 24000 + offset) for offset in range(25)]
    client = FakeDhan(session + [candle(9, 40, 24025)])

    first = sync_current_session(path, client, now=datetime(2026, 7, 22, 9, 40, 10, tzinfo=IST), minimum_retry_seconds=0)
    stored = json.loads(path.read_text())
    assert first["added"] == 25
    assert first["invalid_removed"] == 1
    assert first["fetch_start"] == "2026-07-22T09:15:00+05:30"
    assert first["fetch_end"] == "2026-07-22T09:39:00+05:30"
    assert first["backlog_count"] == 0
    assert len(stored["candles"]) == 25
    assert [c["time"] for c in stored["candles"]] == sorted({c["time"] for c in stored["candles"]})
    projection = NiftyVOBEngine().ingest_1m_candles(stored["candles"], current_nifty_price=24024)
    assert projection["timeframes"]["3m"]["evaluated_through"] == "2026-07-22T09:36:00+05:30"
    assert projection["timeframes"]["5m"]["evaluated_through"] == "2026-07-22T09:35:00+05:30"
    mark_vob_evaluated(path, datetime(2026, 7, 22, 9, 39, tzinfo=IST))

    second = sync_current_session(path, client, now=datetime(2026, 7, 22, 9, 40, 30, tzinfo=IST), minimum_retry_seconds=0)
    assert second["added"] == 0
    assert second["runtime_status"] == "LIVE"
    assert len(json.loads(path.read_text())["candles"]) == 25


def test_provider_failure_does_not_advance_cursor(tmp_path):
    path = tmp_path / "vob_1m_candles.json"
    path.write_text(json.dumps({"candles": []}))
    client = FakeDhan([])
    result = sync_current_session(path, client, now=datetime(2026, 7, 22, 9, 40, tzinfo=IST), minimum_retry_seconds=0)
    cursor = json.loads(path.read_text())["cursor"]
    assert result["runtime_status"] == "CATCHING_UP"
    assert result["backlog_count"] == 25
    assert cursor["latest_persisted_1m"] is None
