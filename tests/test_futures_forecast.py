from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.futures_forecast.math import ForecastValidationError, representative_ohlc_path, validate_ohlc_path
from src.futures_forecast.history import (
    context_hash,
    finalized_five_minute_bars,
    missing_current_session_minutes,
    normalize_genuine_1m,
)
from src.futures_forecast.orchestrator import ForecastOrchestratorError, FuturesForecastOrchestrator
from src.futures_forecast.session_time import NSEForecastTimeMapper
from src.futures_forecast.tirex_state import TiRexStateClassifier
from src.futures_forecast.workers import LatestWinsQueue, function_worker
from src.oracle_development.instrument_resolver import OracleDevInstrumentResolver
from src.market.session_calendar import NSESessionCalendar


IST = ZoneInfo("Asia/Kolkata")


def chart_projection(*, security_id="58072", contract="NIFTY-Aug2026-FUT", expiry="2026-08-25", market="OPEN"):
    starts = []
    for day in (datetime(2026, 8, 5, tzinfo=IST), datetime(2026, 8, 6, tzinfo=IST), datetime(2026, 8, 7, tzinfo=IST)):
        opening = day.replace(hour=9, minute=15)
        starts.extend(opening + timedelta(minutes=5 * index) for index in range(75))
    starts = starts[-180:]
    candles = []
    for index, start in enumerate(starts):
        close = 24500.0 + index
        candles.append({
            "time": int(start.timestamp()),
            "open": close - 1, "high": close + 2, "low": close - 2, "close": close,
            "volume": 1000 + index, "input_candles_count": 5,
        })
    return {
        "status": "AVAILABLE", "timeframe": "5m", "market_status": market,
        "is_synthetic": False, "contract": contract, "security_id": security_id, "expiry": expiry,
        "source_timestamp": datetime.fromtimestamp(candles[-1]["time"], tz=timezone.utc).isoformat(),
        "candles": candles,
        "data_repair": {"data_repair_status": "READY", "missing_1m_count_before_repair": 0,
                        "missing_1m_count_after_repair": 0, "backfilled_1m_count": 0},
    }


def model_workers():
    def chronos(request):
        return {"status": "READY", "device": "cpu", "inference_duration_ms": 2.0,
                "model_load_duration_ms": 3.0,
                "forecast_rows": [
                    {"timestamp": stamp, "p10": 24550 + index, "p25": 24555 + index,
                     "p50": 24560 + index, "p75": 24565 + index, "p90": 24570 + index}
                    for index, stamp in enumerate(request["future_timestamps"])
                ]}

    def kronos(request):
        paths = []
        for path_index in range(request["sample_count"]):
            path = []
            prior = 24563.0
            for step in range(request["forecast_horizon"]):
                close = prior + (path_index - 3) * .2 + step
                path.append({"open": prior, "high": max(prior, close) + 1, "low": min(prior, close) - 1, "close": close})
                prior = close
            paths.append(path)
        selected = representative_ohlc_path(paths, 24563)
        return {"status": "READY", "model_name": "NeoQuasar/Kronos-small", "model_revision": "certified",
                "device": "cpu", "inference_duration_ms": 4.0, "model_load_duration_ms": 5.0,
                "raw_path_count": len(paths), "sample_count": len(paths), **selected}

    def tirex(request):
        close = request["closes"][-1]
        quantiles = [[close + (step + 1) * 2 + (qindex - 4) for step in range(6)] for qindex in range(9)]
        return {"status": "READY", "model": "NX-AI/TiRex-2", "model_revision": "official",
                "package_version": "0.1.1", "device": "cpu", "dtype": "float32",
                "inference_duration_ms": 8.0, "model_load_duration_ms": 9.0,
                "raw_shape": [1, 9, 6], "quantile_levels": [index / 10 for index in range(1, 10)],
                "quantiles": quantiles}

    return function_worker(kronos), function_worker(chronos), function_worker(tirex)


def orchestrator(tmp_path):
    kronos, chronos, tirex = model_workers()
    return FuturesForecastOrchestrator(
        state_path=tmp_path / "forecast.json", kronos_worker=kronos,
        chronos_worker=chronos, tirex_worker=tirex, kronos_sample_count=8,
        clock=lambda: datetime(2026, 8, 7, 15, 30, tzinfo=IST),
    )


class FakeDhan:
    def __init__(self, volumes=None):
        self.volumes = volumes or {}

    def get_multiple_quotes(self, watchlist):
        return {key: {"raw": {"volume": self.volumes.get(value["security_id"], 0)}} for key, value in watchlist.items()}


def write_master(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": datetime.now().isoformat(), "rows": rows}), encoding="utf-8")


def future_row(security_id, expiry, symbol):
    return {"SECURITY_ID": security_id, "UNDERLYING_SYMBOL": "NIFTY", "SYMBOL_NAME": symbol,
            "SM_EXPIRY_DATE": expiry, "INSTRUMENT": "FUTIDX", "LOT_SIZE": "65"}


def test_current_futures_resolver_is_dynamic_and_authoritative(tmp_path):
    path = tmp_path / "master.json"
    write_master(path, [future_row("58072", "2026-08-25", "NIFTY-Aug2026-FUT"), future_row("68407", "2026-09-29", "NIFTY-Sep2026-FUT")])
    resolver = OracleDevInstrumentResolver(FakeDhan({"58072": 999, "68407": 1}), option_master_path=tmp_path / "options.json", futures_cache_path=path,
                                           clock=lambda: datetime(2026, 8, 9, tzinfo=timezone.utc))
    value = resolver.resolve_futures()
    assert value == {"security_id": "58072", "symbol": "NIFTY-Aug2026-FUT", "lot_size": 65,
                     "expiry": "2026-08-25", "segment": "NSE_FNO", "instrument": "FUTIDX",
                     "instrument_type": "FUTIDX", "position": "FRONT_MONTH", "rollover_from": None}


def test_futures_rollover_selects_next_unexpired_contract(tmp_path):
    path = tmp_path / "master.json"
    write_master(path, [future_row("58072", "2026-08-25", "NIFTY-Aug2026-FUT"), future_row("68407", "2026-09-29", "NIFTY-Sep2026-FUT")])
    resolver = OracleDevInstrumentResolver(FakeDhan(), futures_cache_path=path,
                                           clock=lambda: datetime(2026, 8, 26, 4, tzinfo=timezone.utc))
    value = resolver.resolve_futures()
    assert value["security_id"] == "68407"
    assert value["expiry"] == "2026-09-29"


def test_no_hardcoded_nifty_shortcut_remains():
    source = Path("src/oracle_development/instrument_resolver.py").read_text(encoding="utf-8")
    assert 'if underlying == "NIFTY":\n            return {' not in source


def test_session_mapper_intraday_and_friday_to_monday():
    mapper = NSEForecastTimeMapper()
    intraday = mapper.future_timestamps("2026-08-07T09:45:00Z", steps=2)
    rollover = mapper.future_timestamps("2026-08-07T09:55:00Z", steps=2)
    assert intraday == ("2026-08-07T09:50:00Z", "2026-08-07T09:55:00Z")
    assert rollover == ("2026-08-10T03:45:00Z", "2026-08-10T03:50:00Z")
    mapper.assert_valid((*intraday, *rollover))


def test_mapper_never_outputs_weekend_or_after_close():
    values = NSEForecastTimeMapper().future_timestamps("2026-08-07T09:55:00Z", steps=6)
    assert all(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST).weekday() < 5 for value in values)
    assert all(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST).time().isoformat() < "15:30:00" for value in values)


def test_session_mapper_skips_authoritative_nse_holiday():
    values = NSEForecastTimeMapper().future_timestamps("2026-09-11T09:55:00Z", steps=1)
    assert values == ("2026-09-15T03:45:00Z",)


def test_latest_wins_queue_drops_superseded_and_deduplicates():
    queue = LatestWinsQueue()
    assert queue.submit("A", {"v": 1}) is True
    assert queue.submit("B", {"v": 2}) is True
    assert queue.submit("B", {"v": 3}) is False
    assert queue.get()[0] == "B"
    assert queue.dropped == 1 and queue.duplicates == 1


def test_representative_path_is_a_real_sample_and_preserves_ohlc():
    paths = [
        [{"open": 100, "high": max(100, 101 + offset) + 1, "low": min(100, 101 + offset) - 1, "close": 101 + offset},
         {"open": 101 + offset, "high": max(101 + offset, 103 + offset) + 1, "low": min(101 + offset, 103 + offset) - 1, "close": 103 + offset}]
        for offset in (-3, 0, 4)
    ]
    result = representative_ohlc_path(paths, 100)
    assert result["representative_path"] in paths
    assert result["representative_path_id"] == 1
    assert result["sample_count"] == 3


def test_invalid_ohlc_path_fails_closed():
    with pytest.raises(ForecastValidationError, match="OHLC_INVARIANT"):
        validate_ohlc_path([{"open": 100, "high": 99, "low": 98, "close": 101}])


def test_orchestrator_replay_uses_same_identity_and_six_valid_steps(tmp_path):
    engine = orchestrator(tmp_path)
    result = engine.evaluate_historical(chart_projection())
    assert result["instrument"]["security_id"] == "58072"
    assert result["status"] == "READY"
    assert len(result["chronos"]["forecast_rows"]) == 6
    assert len(result["kronos"]["ghost_ohlc"]) == 6
    assert result["tirex"]["raw_shape"] == [1, 9, 6]
    assert all(NSEForecastTimeMapper().is_valid_bar_start(value) for value in result["future_timestamps"])
    history = result["orchestrator"]["last_10_forecast_revisions"]
    assert len(history) == 1
    assert history[0]["forecast_revision"] == result["forecast_revision"]
    assert history[0]["context_hash"] == result["input_context_hash"]
    assert history[0]["kronos"]["representative_path_id"] is not None
    assert len(history[0]["chronos2"]["quantile_hash"]) == 20
    assert history[0]["tirex2"]["state"] == result["tirex"]["state"]


def test_public_transport_hides_tirex_raw_quantiles(tmp_path):
    engine = orchestrator(tmp_path)
    engine.evaluate_historical(chart_projection())
    assert "_raw_quantiles" in engine.projection()["tirex"]
    assert "_raw_quantiles" not in engine.public_projection()["tirex"]


def test_identity_mismatch_rejected_for_chart_transport(tmp_path):
    engine = orchestrator(tmp_path)
    engine.evaluate_historical(chart_projection())
    mismatch = chart_projection(security_id="13", contract="NIFTY INDEX", expiry="N/A")
    assert engine.projection_for(mismatch)["reason"] == "FORECAST_INSTRUMENT_IDENTITY_MISMATCH"


def test_stale_forecast_source_is_rejected_for_current_chart(tmp_path):
    engine = orchestrator(tmp_path)
    original = chart_projection()
    engine.evaluate_historical(original)
    advanced = chart_projection()
    advanced["source_timestamp"] = "2026-08-07T10:00:00+00:00"
    result = engine.projection_for(advanced)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "FORECAST_SOURCE_CANDLE_MISMATCH"


def test_prediction_feedback_is_rejected(tmp_path):
    projection = chart_projection()
    projection["candles"][0]["predicted"] = True
    with pytest.raises(ForecastOrchestratorError, match="PREDICTION_FEEDBACK"):
        orchestrator(tmp_path).evaluate_historical(projection)


def test_unfinished_or_source_mismatched_candle_is_rejected(tmp_path):
    projection = chart_projection()
    projection["source_timestamp"] = "2026-08-07T09:50:00+00:00"
    with pytest.raises(ForecastOrchestratorError, match="SOURCE_CANDLE_MISMATCH"):
        orchestrator(tmp_path).evaluate_historical(projection)


def test_kronos_requires_180_finalized_genuine_futures_bars(tmp_path):
    insufficient = chart_projection()
    insufficient["candles"] = insufficient["candles"][-179:]
    with pytest.raises(ForecastOrchestratorError, match="INSUFFICIENT_CONTEXT"):
        orchestrator(tmp_path).evaluate_historical(insufficient)
    incomplete = chart_projection()
    incomplete["candles"][-1]["input_candles_count"] = 4
    with pytest.raises(ForecastOrchestratorError, match="OBSERVATION_COVERAGE_INCOMPLETE"):
        orchestrator(tmp_path).evaluate_historical(incomplete)


def test_chronos_reuses_validated_multivariate_feature_path(tmp_path):
    engine = orchestrator(tmp_path)
    request = engine._request_from_projection(chart_projection(), require_live=False)
    value = engine._worker_request("chronos", request)
    assert value["feature_names"] == ["open", "high", "low", "volume", "realized_volatility", "atr_normalized"]
    assert value["mode"] == "MULTIVARIATE"
    assert value["input_coverage"] == 100.0


def test_market_close_accepts_same_session_finalized_last_candle(tmp_path):
    assert orchestrator(tmp_path).ingest(chart_projection(market="MARKET_CLOSED")) is True


def test_market_close_rejects_old_or_not_yet_finalized_candle(tmp_path):
    old_clock_engine = orchestrator(tmp_path)
    old_clock_engine.clock = lambda: datetime(2026, 8, 10, 15, 30, tzinfo=IST)
    assert old_clock_engine.ingest(chart_projection(market="MARKET_CLOSED")) is False

    future = chart_projection(market="MARKET_CLOSED")
    future["source_timestamp"] = datetime(2026, 8, 7, 15, 30, tzinfo=IST).astimezone(timezone.utc).isoformat()
    future["candles"][-1]["time"] = int(datetime(2026, 8, 7, 15, 30, tzinfo=IST).timestamp())
    assert orchestrator(tmp_path).ingest(future) is False


def test_opening_waits_for_first_genuine_finalized_five_minute_bar(tmp_path):
    kronos, chronos, tirex = model_workers()
    engine = FuturesForecastOrchestrator(
        state_path=tmp_path / "forecast.json", kronos_worker=kronos, chronos_worker=chronos,
        tirex_worker=tirex, clock=lambda: datetime(2026, 8, 10, 9, 17, tzinfo=IST),
    )
    assert engine.ingest(chart_projection()) is False


def test_startup_gap_repair_rebuilds_identical_180_bar_context(tmp_path):
    calendar = NSESessionCalendar(clock=lambda: datetime(2026, 8, 10, 9, 20, tzinfo=IST))
    rows = []
    for day in (5, 6, 7):
        opening = datetime(2026, 8, day, 9, 15, tzinfo=IST)
        for minute in range(375):
            stamp = opening + timedelta(minutes=minute)
            close = 24400 + len(rows) * .1
            rows.append({"time": int(stamp.timestamp()), "open": close - .2, "high": close + .4,
                         "low": close - .4, "close": close, "volume": 1000 + minute})
    opening = datetime(2026, 8, 10, 9, 15, tzinfo=IST)
    monday = []
    for minute in range(5):
        close = 24600 + minute
        monday.append({"time": int((opening + timedelta(minutes=minute)).timestamp()), "open": close - .2,
                       "high": close + .4, "low": close - .4, "close": close, "volume": 2000 + minute})
    as_of = datetime(2026, 8, 10, 9, 20, tzinfo=IST)
    baseline_1m = normalize_genuine_1m([*rows, *monday], as_of=as_of, calendar=calendar)
    local_at_restart = list(rows)
    assert len(missing_current_session_minutes(local_at_restart, as_of=datetime(2026, 8, 10, 9, 17, tzinfo=IST), calendar=calendar)) == 2
    dhan_backfill = monday[:2]
    live_after_restart = monday[2:]
    recovered_1m = normalize_genuine_1m([*local_at_restart, *dhan_backfill, *live_after_restart], as_of=as_of, calendar=calendar)
    assert recovered_1m == baseline_1m
    assert missing_current_session_minutes(recovered_1m, as_of=as_of, calendar=calendar) == ()
    baseline_5m = finalized_five_minute_bars(baseline_1m, as_of=as_of, calendar=calendar)
    recovered_5m = finalized_five_minute_bars(recovered_1m, as_of=as_of, calendar=calendar)
    assert recovered_5m == baseline_5m
    assert len({row["time"] for row in recovered_1m}) == len(recovered_1m)
    assert context_hash(recovered_5m[-180:]) == context_hash(baseline_5m[-180:])
    projection = chart_projection()
    projection["candles"] = recovered_5m[-180:]
    projection["source_timestamp"] = datetime.fromtimestamp(recovered_5m[-1]["time"], tz=timezone.utc).isoformat()
    request = orchestrator(tmp_path)._request_from_projection(projection, require_live=False)
    chronos_request = orchestrator(tmp_path)._worker_request("chronos", request)
    assert chronos_request["rows"][-1]["timestamp"] == request["source_bar_timestamp"]
    assert request["input_context_hash"] == context_hash(recovered_5m[-180:])
    assert all(not row.get("forecast") and not row.get("predicted") for row in recovered_1m)


def test_duplicate_source_candle_suppressed(tmp_path):
    engine = orchestrator(tmp_path)
    value = chart_projection()
    assert engine.ingest(value) is True
    assert engine.ingest(value) is False
    assert engine.telemetry()["duplicate_source_suppression"] == 1


def test_superseded_model_completion_is_rejected(tmp_path):
    _, chronos, tirex = model_workers()
    engine = None
    def superseding_chronos(request):
        assert engine is not None
        engine._latest_requested_key = "NEWER_SOURCE"
        return chronos.request(request)
    kronos, _, _ = model_workers()
    engine = FuturesForecastOrchestrator(
        state_path=tmp_path / "forecast.json", kronos_worker=kronos,
        chronos_worker=function_worker(superseding_chronos), tirex_worker=tirex,
        clock=lambda: datetime(2026, 8, 7, 15, 30, tzinfo=IST),
    )
    request = engine._request_from_projection(chart_projection(), require_live=False)
    engine._latest_requested_key = request["forecast_id"]
    engine._process(request["forecast_id"], request, mode="HISTORICAL_REPLAY")
    assert engine.telemetry()["stale_result_rejections"] == 1


def test_model_failure_fails_dark_without_ghost_values(tmp_path):
    failing = function_worker(lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    _, chronos, tirex = model_workers()
    engine = FuturesForecastOrchestrator(state_path=tmp_path / "f.json", kronos_worker=failing, chronos_worker=chronos, tirex_worker=tirex)
    result = engine.evaluate_historical(chart_projection())
    assert result["kronos"]["status"] == "UNAVAILABLE"
    assert "ghost_ohlc" not in result["kronos"]
    assert result["safety"]["execution_influence"] == "ZERO"


def test_snapshot_is_restart_recoverable_and_revision_is_source_based(tmp_path):
    engine = orchestrator(tmp_path)
    first = engine.evaluate_historical(chart_projection())
    restored = orchestrator(tmp_path)
    assert restored.projection()["forecast_id"] == first["forecast_id"]
    assert restored.projection()["forecast_revision"] == int(datetime(2026, 8, 7, 9, 55, tzinfo=timezone.utc).timestamp())


def test_chronos_and_kronos_passive_comparison_cannot_overwrite_payload(tmp_path):
    engine = orchestrator(tmp_path)
    engine.evaluate_historical(chart_projection())
    result = engine.comparison()
    assert result["same_origin"] is True
    assert result["chronos_source_bar_timestamp"] == result["kronos_source_bar_timestamp"]


def tirex_quantiles(close, sign):
    return [[close + sign * (step + 1) * 2 + (qindex - 4) * .25 for step in range(6)] for qindex in range(9)]


def test_tirex_bullish_bearish_neutral_and_hysteresis():
    history = list(range(100, 164))
    bullish = TiRexStateClassifier()
    assert bullish.classify(tirex_quantiles(164, 1), 164, history)["state"] == "NEUTRAL"
    assert bullish.classify(tirex_quantiles(164, 1), 164, history)["state"] == "BULLISH"
    bearish = TiRexStateClassifier()
    bearish.classify(tirex_quantiles(164, -1), 164, history)
    assert bearish.classify(tirex_quantiles(164, -1), 164, history)["state"] == "BEARISH"
    neutral = TiRexStateClassifier()
    flat = [[164 + (qindex - 4) * .01 for _ in range(6)] for qindex in range(9)]
    assert neutral.classify(flat, 164, history)["state"] == "NEUTRAL"


def test_tirex_quantile_shape_and_order_are_strict():
    classifier = TiRexStateClassifier()
    with pytest.raises(ForecastValidationError, match="SHAPE"):
        classifier.classify([[1] * 6] * 8, 1, list(range(64)))


def test_old_duplicate_model_schedulers_are_not_started():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "kronos_alpha_scheduler.start()" not in source
    assert "chronos_2_scheduler.start()" not in source
    assert source.count("(\"FUTURES_FORECAST\", futures_forecast_orchestrator.start)") == 1


def test_execution_safety_is_immutable_in_projection(tmp_path):
    value = orchestrator(tmp_path).evaluate_historical(chart_projection())
    assert value["safety"] == {"advisory_only": True, "execution_influence": "ZERO", "live_trading_enabled": False, "broker_submission": False}
