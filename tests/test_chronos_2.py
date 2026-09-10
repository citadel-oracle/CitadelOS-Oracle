from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from tests.frontend_dashboard_contract import assert_centralized_feed

from app.main import app
from src.chronos_2.analytics import QUALITY_WEIGHTS, derive_analytics
from src.chronos_2.config import Chronos2Config
from src.chronos_2.evaluation import ChronosRealizationEvaluator
from src.chronos_2.inputs import (
    ChronosInputError,
    argus_features,
    build_model_rows,
    future_timestamps,
    input_fingerprint,
    validate_closed_candles,
)
from src.chronos_2.service import Chronos2Scheduler, Chronos2Service
from src.chronos_2.storage import AtomicJsonDocument, ChronosStorageError, ForecastLedger
from src.market.session_calendar import NSESessionCalendar


pytestmark = pytest.mark.unit
IST = ZoneInfo("Asia/Kolkata")


def candles(count=256, start="2026-07-09T09:15:00+05:30", volume=True):
    current = datetime.fromisoformat(start)
    rows = []
    value = 24000.0
    while len(rows) < count:
        session = NSESessionCalendar().session_for_date(current.date())
        if session["session_state"] not in {"OPEN", "SPECIAL_SESSION"}:
            current = datetime.fromisoformat(session["next_valid_open"])
            continue
        close = datetime.fromisoformat(session["scheduled_close"])
        if current >= close:
            current = datetime.fromisoformat(session["next_valid_open"])
            continue
        value += 1.0
        rows.append({"timestamp": current.isoformat(), "candle_closed_at": (current + timedelta(minutes=5)).isoformat(),
                     "open": value - 1, "high": value + 3, "low": value - 3, "close": value,
                     "volume": 1000 + len(rows) if volume else None, "closed": True, "is_closed": True,
                     "freshness": "HISTORICAL"})
        current += timedelta(minutes=5)
    return rows


def forecast(direction="bullish", width=30):
    origin = 24000.0
    rows = []
    for index in range(1, 13):
        move = index * 3 if direction == "bullish" else -index * 3 if direction == "bearish" else (1 if index % 2 else -1)
        median = origin + move
        rows.append({"timestamp": f"2026-07-13T{9 + (15 + index * 5) // 60:02d}:{(15 + index * 5) % 60:02d}:00+05:30",
                     "p10": median - width, "p25": median - width / 2, "p50": median,
                     "p75": median + width / 2, "p90": median + width})
    return {"forecast_rows": rows, "forecast_low": min(row["p10"] for row in rows),
            "forecast_high": max(row["p90"] for row in rows), "input_coverage": 100.0}


def argus(side="CE", freshness="FRESH"):
    return {"status": freshness, "features": {"preferred_option_side": side, "confidence": 80}}


def test_official_identity_and_frozen_shadow_contract():
    config = Chronos2Config()
    assert config.model_name == "amazon/chronos-2"
    assert config.model_revision == "29ec3766d36d6f73f0696f85560a422f50e8498c"
    assert config.upstream_revision == "7dc4435706a4454feb79df44ca9f33631f3027bf"
    assert config.package_version == "2.3.1" and config.license == "Apache-2.0"
    assert config.shadow_mode and config.advisory_only
    assert config.execution_influence == config.aegis_direct_influence == 0


def test_closed_candle_validation_and_multivariate_features():
    selected = validate_closed_candles(candles(), now=datetime.fromisoformat("2026-07-15T12:00:00+05:30"))
    rows, mode, features, coverage = build_model_rows(selected)
    assert len(rows) == 256 and mode == "MULTIVARIATE" and coverage == 100
    assert features == ["open", "high", "low", "volume", "realized_volatility", "atr_normalized"]
    assert all(row["timestamp"] <= selected[-1]["timestamp"] for row in rows)


def test_missing_volume_truthfully_reduces_coverage_without_invention():
    rows, mode, features, coverage = build_model_rows(candles(volume=False))
    assert mode == "MULTIVARIATE" and "volume" not in features
    assert coverage < 100 and all(row["volume"] is None for row in rows)


@pytest.mark.parametrize("mutation,reason", [
    (lambda rows: rows.__setitem__(10, {**rows[10], "closed": False}), "INCOMPLETE_CANDLE"),
    (lambda rows: rows.__setitem__(10, {**rows[10], "timestamp": rows[9]["timestamp"]}), "DUPLICATE_CANDLE"),
    (lambda rows: rows.reverse(), "UNSORTED_CANDLES"),
    (lambda rows: rows.__setitem__(-1, {**rows[-1], "candle_closed_at": "2026-07-15T10:00:00+05:30"}), "LOOK_AHEAD_CANDLE"),
])
def test_invalid_or_future_inputs_fail_closed(mutation, reason):
    rows = candles(64); mutation(rows)
    with pytest.raises(ChronosInputError, match=reason):
        validate_closed_candles(rows, now=datetime.fromisoformat("2026-07-11T12:00:00+05:30"))


def test_context_minimum_and_semantic_fingerprint():
    with pytest.raises(ChronosInputError, match="CONTEXT_INSUFFICIENT"):
        validate_closed_candles(candles(63), now=datetime.fromisoformat("2026-07-11T12:00:00+05:30"))
    rows = candles(64)
    first = input_fingerprint(rows, ["open"], Chronos2Config().model_revision)
    assert first == input_fingerprint(rows, ["open"], Chronos2Config().model_revision)
    assert first != input_fingerprint(rows, ["high"], Chronos2Config().model_revision)


def test_session_gap_future_timestamps_skip_weekend_and_holidays():
    values = future_timestamps("2026-07-10T15:25:00+05:30", 12)
    assert values[0] == "2026-07-13T09:15:00+05:30"
    assert values[-1] == "2026-07-13T10:10:00+05:30"
    assert len(values) == len(set(values)) == 12


def test_argus_adapter_is_sanitized_current_projection_not_history():
    projection = {"status": "stale", "freshness": "stale", "data": {
        "underlying": {"fetched_at": "2026-07-10T15:29:00+05:30"},
        "totals": {"ce_oi": 10, "pe_oi": 20, "pcr": 2},
        "walls": {"highest_ce_oi": {"strike": 24200}, "highest_pe_oi": {"strike": 24100}},
        "verdict": {"bias": "BULLISH", "preferred_option_side": "CE", "confidence": 70}}}
    value = argus_features(projection)
    assert value["status"] == "STALE" and value["features"]["aggregate_pcr"] == 2
    assert value["reason"] == "CURRENT_SNAPSHOT_NOT_HISTORICAL_SEQUENCE"
    assert "raw" not in json.dumps(value).lower()


@pytest.mark.parametrize("direction,expected", [("bullish", "BULLISH"), ("bearish", "BEARISH"), ("sideways", "SIDEWAYS")])
def test_directional_analytics_are_bounded_and_not_probability(direction, expected):
    value = derive_analytics(forecast(direction), origin=24000, recent_volatility=10, argus=argus())
    assert value["directional_bias"] == expected
    assert 0 <= value["directional_confidence"] <= 100
    assert "NOT_A_CALIBRATED_PROBABILITY" in value["warnings"][0]
    assert value["label"] == "CITADEL-DERIVED FROM CHRONOS-2 FORECAST"


def test_ce_and_pe_quality_are_direction_specific_independent_and_bounded():
    bullish = derive_analytics(forecast("bullish"), origin=24000, recent_volatility=10, argus=argus("CE"))
    bearish = derive_analytics(forecast("bearish"), origin=24000, recent_volatility=10, argus=argus("PE"))
    assert bullish["ce_quality"]["score"] > bullish["pe_quality"]["score"]
    assert bearish["pe_quality"]["score"] > bearish["ce_quality"]["score"]
    for quality in (bullish["ce_quality"], bullish["pe_quality"], bearish["ce_quality"], bearish["pe_quality"]):
        assert 0 <= quality["score"] <= 100 and quality["recommendation"] is None
    assert sum(QUALITY_WEIGHTS.values()) == 100


def test_uncertainty_reversal_sideways_and_stale_argus_penalize_quality():
    clean = derive_analytics(forecast("bullish", width=10), origin=24000, recent_volatility=20, argus=argus("CE", "FRESH"))
    wide = derive_analytics(forecast("bullish", width=200), origin=24000, recent_volatility=10, argus=argus("CE", "FRESH"))
    stale = derive_analytics(forecast("bullish", width=10), origin=24000, recent_volatility=20, argus=argus("CE", "STALE"))
    sideways = derive_analytics(forecast("sideways", width=10), origin=24000, recent_volatility=20, argus=argus("CE", "FRESH"))
    assert wide["ce_quality"]["score"] <= clean["ce_quality"]["score"]
    assert stale["ce_quality"]["score"] < clean["ce_quality"]["score"]
    assert sideways["ce_quality"]["score"] < clean["ce_quality"]["score"]


def test_missing_liquidity_is_not_positive_evidence():
    value = derive_analytics(forecast("bullish"), origin=24000, recent_volatility=10, argus=None)
    assert "liquidity" in value["ce_quality"]["missing_components"]
    assert "liquidity" not in value["ce_quality"]["components"]


def test_quantile_contract_range_and_terminal_move():
    value = forecast("bullish")
    assert all(row["p10"] <= row["p25"] <= row["p50"] <= row["p75"] <= row["p90"] for row in value["forecast_rows"])
    assert value["forecast_low"] == min(row["p10"] for row in value["forecast_rows"])
    assert value["forecast_high"] == max(row["p90"] for row in value["forecast_rows"])


def ledger_forecast():
    value = forecast("bullish")
    return {"forecast_id": "forecast-1", "generated_at": "2026-07-10T15:30:00+05:30", "model_revision": "rev",
            "symbol": "NIFTY", "timeframe": "5m", "input_fingerprint": "fingerprint", "mode": "MULTIVARIATE",
            "context_end": "2026-07-10T15:25:00+05:30", "forecast_origin": 24000.0, "prediction_length": 12,
            "forecast_rows": value["forecast_rows"], "forecast_low": value["forecast_low"], "forecast_high": value["forecast_high"],
            "derived_analytics": derive_analytics(value, origin=24000, recent_volatility=10, argus=argus())}


def test_ledger_atomic_duplicate_restart_immutability_and_bound(tmp_path):
    ledger = ForecastLedger(tmp_path / "history.json", retention=20)
    original = ledger_forecast(); assert ledger.append_forecast(original) == ("forecast-1", True)
    original["forecast_origin"] = -1
    assert ledger.append_forecast(ledger_forecast()) == ("forecast-1", False)
    assert ForecastLedger(tmp_path / "history.json").forecasts()[0]["forecast_origin"] == 24000
    for index in range(1, 25):
        item = ledger_forecast(); item["forecast_id"] = f"forecast-{index + 1}"; ledger.append_forecast(item)
    assert len(ledger.forecasts()) == 20
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_ledger_fails_visibly_without_reset(tmp_path):
    path = tmp_path / "history.json"; path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ChronosStorageError, match="CORRUPT"):
        ForecastLedger(path).history()
    assert path.read_text(encoding="utf-8") == "not-json"


def test_realization_waits_for_full_horizon_and_preserves_forecast(tmp_path):
    ledger = ForecastLedger(tmp_path / "history.json"); record = ledger_forecast(); ledger.append_forecast(record)
    evaluator = ChronosRealizationEvaluator(ledger)
    future = candles(12, start="2026-07-13T09:15:00+05:30")
    assert evaluator.evaluate(future[:11]) == []
    completed = evaluator.evaluate(future)
    assert len(completed) == 1 and 0 <= completed[0]["p10_p90_interval_coverage"] <= 100
    assert ledger.forecasts()[0]["forecast_rows"] == record["forecast_rows"]


class FakeSource:
    def __init__(self, rows): self.rows = rows
    def load_cache(self): return self.rows


class FakeWorker:
    def __init__(self): self.calls = 0
    def run(self, request, preferred_device="mps"):
        self.calls += 1
        rows = []
        for index, timestamp in enumerate(request["future_timestamps"]):
            median = 24200 + index
            rows.append({"timestamp": timestamp, "p10": median - 20, "p25": median - 10, "p50": median, "p75": median + 10, "p90": median + 20})
        return {"status": "READY", "device": "cpu", "model_class": "Chronos2Pipeline", "model_load_duration_ms": 1,
                "inference_duration_ms": 2, "forecast_rows": rows}, []


def scheduler(tmp_path, now, rows=None, worker=None):
    config = replace(Chronos2Config(), forecast_cache_path=tmp_path / "forecast.json", history_path=tmp_path / "history.json")
    return Chronos2Scheduler(config=config, candle_source=FakeSource(rows or candles()), worker=worker or FakeWorker(),
                             clock=lambda: now, argus_provider=lambda: None)


def test_scheduler_weekend_duplicate_and_overlap_safety(tmp_path):
    worker = FakeWorker(); closed = scheduler(tmp_path, datetime.fromisoformat("2026-07-11T12:00:00+05:30"), worker=worker)
    assert closed.tick()["reason"] == "WEEKEND" and worker.calls == 0
    open_rows = candles(256, start="2026-07-13T09:15:00+05:30")
    current = datetime.fromisoformat(open_rows[-1]["candle_closed_at"]) + timedelta(seconds=10)
    active = scheduler(tmp_path / "open", current, rows=open_rows, worker=worker)
    assert active.tick()["ran"] is True and worker.calls == 1
    assert active.tick()["reason"] == "SKIPPED_DUPLICATE" and worker.calls == 1
    active._lock.acquire()
    try: assert active.tick()["reason"] == "JOB_ALREADY_RUNNING"
    finally: active._lock.release()


def test_scheduler_tick_evaluates_mature_forecasts_before_new_inference(tmp_path):
    rows = candles(80, start="2026-07-13T09:15:00+05:30")
    current = datetime.fromisoformat(rows[-1]["candle_closed_at"]) + timedelta(seconds=10)
    active = scheduler(tmp_path, current, rows=rows)
    record = ledger_forecast()
    record["context_end"] = rows[-13]["timestamp"]
    record["forecast_rows"] = [
        {**row, "timestamp": rows[index - 12]["timestamp"]}
        for index, row in enumerate(record["forecast_rows"])
    ]
    active.ledger.append_forecast(record)

    active.tick()

    assert active.ledger.history()["evaluation_count"] == 1


def test_service_unavailable_routes_never_trigger_worker(tmp_path):
    worker = FakeWorker(); value = scheduler(tmp_path, datetime.fromisoformat("2026-07-11T12:00:00+05:30"), worker=worker)
    service = Chronos2Service(value)
    for method in (service.status, service.forecast, service.outlook, service.history, service.evaluation, service.features, service.comparison):
        method()
    assert worker.calls == 0


def test_comparison_agreement_conflict_unavailable_and_no_premature_winner(tmp_path):
    value = scheduler(tmp_path, datetime.fromisoformat("2026-07-11T12:00:00+05:30"))
    document = {**Chronos2Config().public_metadata(), **ledger_forecast(), "status": "READY", "freshness": "HISTORICAL",
                "context_start": "2026-07-09T09:15:00+05:30", "input_candle_count": 256, "input_feature_count": 7,
                "input_feature_names": ["close"], "input_coverage": 100, "median_terminal_move_points": 1,
                "median_terminal_move_percentage": 0.1, "prediction_interval_width": 10, "forecast_dispersion": 5,
                "terminal_p10": 1, "terminal_p50": 2, "terminal_p90": 3, "device": "cpu", "inference_duration_ms": 2,
                "warnings": [], "schema_version": 1}
    value.cache.write(document)
    same = Chronos2Service(value, kronos_provider=lambda: {"last_input_candle_at": document["context_end"], "expected_direction": "BULLISH", "outlooks": {}}).comparison()
    conflict = Chronos2Service(value, kronos_provider=lambda: {"last_input_candle_at": document["context_end"], "expected_direction": "BEARISH", "outlooks": {}}).comparison()
    unavailable = Chronos2Service(value, kronos_provider=lambda: {}).comparison()
    assert same["agreement"] == "AGREE" and conflict["agreement"] == "CONFLICT" and unavailable["agreement"] == "UNAVAILABLE"
    assert same["rolling_winner"] is None and same["maturity"] == "COLLECTING"


def test_get_only_routes_sanitized_frontend_contract_and_existing_dashboard():
    expected = {"/v1/chronos-2/status", "/v1/chronos-2/forecast", "/v1/chronos-2/outlook", "/v1/chronos-2/history",
                "/v1/chronos-2/evaluation", "/v1/chronos-2/comparison/kronos-alpha", "/v1/chronos-2/features"}
    routes = {route.path: set(route.methods or ()) for route in app.routes}
    assert expected.issubset(routes) and all(routes[path] == {"GET"} for path in expected)
    frontend = (Path(__file__).parents[1] / "citadel-dashboard/src/app/page.tsx").read_text(encoding="utf-8")
    assert_centralized_feed("chronos2", "chronos2")
    assert frontend.index("KRONOS ALPHA") < frontend.index("CHRONOS-2")
    assert "CHRONOS-2 CE and PE quality wheels" in frontend
    assert 'label="Forecast confidence"' in frontend and "function ForecastRange" in frontend
    assert 'label="Execution / AEGIS influence"' in frontend
    assert not any(label in frontend for label in ("Run Chronos", "Download model", "BUY CHRONOS", "SELL CHRONOS"))
    for existing in ("Mission Control summary", "ARGUS OI positioning", "AEGIS — FINAL DECISION INTELLIGENCE", "Personal Trading Intelligence"):
        assert existing in frontend


def test_module_has_no_broker_paper_risk_kill_switch_or_hermes_dependency():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (Path(__file__).parents[1] / "src/chronos_2").glob("*.py"))
    for forbidden in ("src.broker", "src.execution", "src.risk", "src.hermes"):
        assert forbidden not in source
    settings = json.loads((Path(__file__).parents[1] / "config/settings.json").read_text(encoding="utf-8"))
    assert settings["live_trading_enabled"] is False
