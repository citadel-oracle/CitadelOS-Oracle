from __future__ import annotations

import inspect
import json
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.oracle_development.chart_adapter import OracleDevChartAdapter
from src.oracle_development.oracle_dev_service import (
    OracleDevService,
    analyze_price_action_batch,
)
from src.oracle.isolated_execution_boundary import IsolatedExecutionBoundary


class _Dhan:
    def get_quote(self, *_args, **_kwargs):
        return {"ltp": 25_000.0}

    def get_intraday_candles(self, *_args, **_kwargs):
        return {"candles": []}


def _candles(count: int = 72):
    ist = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 8, 14, 9, 15, tzinfo=ist)
    return [
        {
            "time": int((start + timedelta(minutes=index)).timestamp()),
            "open": 25_000.0 + index * 0.5,
            "high": 25_004.0 + index * 0.5 + (index % 4),
            "low": 24_996.0 + index * 0.5 - (index % 3),
            "close": 25_001.0 + index * 0.5 + ((index % 5) - 2),
            "volume": 1_000 + index * 11,
        }
        for index in range(count)
    ]


def _service(tmpdir: str):
    now = datetime(2026, 8, 14, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    service = OracleDevService(_Dhan(), None, None, None, state_root=Path(tmpdir), clock=lambda: now)
    service.is_replay = True
    service.is_synthetic = False
    service._futures_chart_identity = {
        "security_id": "58072",
        "contract": "NIFTY AUG FUT",
        "expiry": "2026-08-27",
    }
    return service, now


def test_worker_output_preserves_price_action_structure_and_chart_semantics():
    with tempfile.TemporaryDirectory() as tmpdir:
        service, now = _service(tmpdir)
        spot = _candles()
        futures = [
            {**row, "open": row["open"] + 12, "high": row["high"] + 12,
             "low": row["low"] + 12, "close": row["close"] + 12}
            for row in spot
        ]
        source_revision = service._candle_input_revision(spot, futures)
        payload = {
            "batch_revision": 1,
            "source_revisions": {"3m": source_revision},
            "lanes": {"3m": {"spot": deepcopy(spot), "futures": deepcopy(futures)}},
        }

        old_result = service.pa_analyzer.analyze(deepcopy(spot), deepcopy(futures), "NIFTY")
        worker = analyze_price_action_batch("chart_price_action", payload)

        # Exact formula-level parity covers BOS/CHoCH structure events and the
        # price-action inputs consumed by VOB/scoring without changing either.
        assert worker["results"]["3m"] == old_result

        expected = OracleDevChartAdapter.get_chart_data(
            service,
            "3m",
            spot_candles=deepcopy(spot),
            fut_candles=deepcopy(futures),
            pa_result=deepcopy(old_result),
            now_dt=now,
        )
        service._price_action_pending[1] = {
            "3m": {"spot": deepcopy(spot), "futures": deepcopy(futures)}
        }
        service.apply_price_action_snapshot(worker)
        actual = json.loads(service.chart_data_snapshot("3m").encoded_bytes)
        for key in (
            "chart_snapshot_revision", "chart_source_revisions",
            "chart_source_timestamp", "chart_analyzed_at", "chart_published_at",
            "price_action_analysis_count", "price_action_structure_scan_count",
            "execution_influence",
        ):
            actual.pop(key, None)
        assert actual == expected


def test_one_hundred_same_revision_reads_add_no_analysis_or_structure_scans():
    with tempfile.TemporaryDirectory() as tmpdir:
        service, _ = _service(tmpdir)
        spot = _candles()
        futures = deepcopy(spot)
        source_revision = service._candle_input_revision(spot, futures)
        payload = {
            "batch_revision": 1,
            "source_revisions": {"3m": source_revision},
            "lanes": {"3m": {"spot": spot, "futures": futures}},
        }
        service._price_action_pending[1] = {"3m": payload["lanes"]["3m"]}
        service.apply_price_action_snapshot(analyze_price_action_batch("chart_price_action", payload))
        before = service.chart_data_health()
        bodies = [service.chart_data_snapshot("3m").encoded_bytes for _ in range(100)]
        after = service.chart_data_health()

        assert all(body is bodies[0] for body in bodies)
        assert after["analysis_count"] == before["analysis_count"]
        assert after["structure_scan_count"] == before["structure_scan_count"]
        assert after["snapshots"]["3m"]["revision"] == before["snapshots"]["3m"]["revision"]


def test_published_revision_cannot_be_mutated_by_a_later_revision():
    with tempfile.TemporaryDirectory() as tmpdir:
        service, _ = _service(tmpdir)
        first = service.chart_data_snapshot("3m")
        first_body = first.encoded_bytes
        rows = _candles()
        source_revision = service._candle_input_revision(rows, rows)
        payload = {
            "batch_revision": 1,
            "source_revisions": {"3m": source_revision},
            "lanes": {"3m": {"spot": deepcopy(rows), "futures": deepcopy(rows)}},
        }
        service._price_action_pending[1] = {"3m": payload["lanes"]["3m"]}
        service.apply_price_action_snapshot(analyze_price_action_batch("chart_price_action", payload))

        assert service.chart_data_snapshot("3m").revision > first.revision
        assert first.encoded_bytes is first_body
        assert json.loads(first.encoded_bytes)["reason"] == "PRICE_ACTION_SNAPSHOT_WARMING"


def test_price_action_process_has_one_owner_and_deterministic_shutdown():
    received = []
    boundary = IsolatedExecutionBoundary(
        name="test-price-action-worker",
        processor=analyze_price_action_batch,
        on_snapshot=received.append,
        input_capacity=8,
        publish_interval_seconds=0.05,
    )
    rows = _candles(8)
    payload = {
        "batch_revision": 1,
        "source_revisions": {"3m": "fixture"},
        "lanes": {"3m": {"spot": rows, "futures": rows}},
    }
    try:
        assert boundary.start() is True
        pid = boundary.status()["pid"]
        assert pid is not None
        assert boundary.start() is False
        assert boundary.status()["pid"] == pid
        assert boundary.submit("chart_price_action", payload, timeout=1.0) is True
        deadline = time.monotonic() + 5.0
        while not received and time.monotonic() < deadline:
            time.sleep(0.02)
        assert received[0]["results"]["3m"]["score"] >= 0
    finally:
        boundary.stop()
    assert boundary.status()["alive"] is False


def test_forming_futures_tick_is_not_a_price_action_revision_input():
    with tempfile.TemporaryDirectory() as tmpdir:
        service, now = _service(tmpdir)
        rows = _candles()
        service._historical_spot_candles["3m"] = deepcopy(rows)
        service._historical_futures_candles["3m"] = deepcopy(rows)
        service._active_fut_security_id = "58072"
        before = service._candle_input_revision(
            service._historical_spot_candles["3m"],
            service._historical_futures_candles["3m"],
        )
        service.ingest_live_futures_tick({
            "security_id": "58072",
            "ltp": 25_123.5,
            "ltt": int(now.timestamp()),
            "receive_wall_utc": now.astimezone(timezone.utc).isoformat(),
        })
        after = service._candle_input_revision(
            service._historical_spot_candles["3m"],
            service._historical_futures_candles["3m"],
        )

        assert before == after
        assert service._forming_futures_cache["3m"]["close"] == 25_123.5


def test_chart_http_source_is_cached_snapshot_only():
    source = (Path(__file__).parents[2] / "app" / "main.py").read_text()
    start = source.index("def active_dev_chart_data(")
    end = source.index("\n@app.post(\"/v1/oracle-development/sync\")", start)
    route = source[start:end]

    assert "chart_data_snapshot" in route
    assert "pa_analyzer" not in route
    assert "OracleDevChartAdapter" not in route
    assert "refresh_market_data_if_due" not in route
    assert "request_chart_refresh" in route


def test_chart_adapter_formula_path_is_unchanged_when_precomputed_result_is_supplied():
    source = inspect.getsource(OracleDevChartAdapter.get_chart_data)
    assert 'service.pa_analyzer.analyze(spot_candles, fut_candles, "NIFTY")' in source
    assert "if pa_result is None" in source
