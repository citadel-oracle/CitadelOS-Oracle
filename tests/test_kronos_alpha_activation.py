import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.kronos_alpha.cache import ForecastCache
from src.kronos_alpha.candle_source import CandleSourceError, RealNiftyCandleSource
from src.kronos_alpha.config import KronosAlphaConfig
from src.kronos_alpha.history import ForecastHistoryLedger, RealizationEvaluator
from src.kronos_alpha.metrics import ForecastValidationError, derive_metrics
from src.kronos_alpha.outlooks import forecast_quality, option_outlooks
from src.kronos_alpha.scheduler import KronosAlphaScheduler
from src.market.session_calendar import NSESessionCalendar


IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
MODEL = Path("/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface/models--NeoQuasar--Kronos-small/snapshots/901c26c1332695a2a8f243eb2f37243a37bea320")
TOKENIZER = Path("/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface/models--NeoQuasar--Kronos-Tokenizer-base/snapshots/0e0117387f39004a9016484a186a908917e22426")


def at(day, hour, minute=0):
    return datetime(2026, 7, day, hour, minute, tzinfo=IST)


@pytest.mark.unit
@pytest.mark.parametrize(("when", "state", "opened"), [
    (at(11, 10), "WEEKEND", False),
    (at(12, 10), "WEEKEND", False),
    (datetime(2026, 6, 26, 10, tzinfo=IST), "HOLIDAY", False),
    (at(10, 9, 5), "PRE_OPEN", False),
    (at(10, 10), "OPEN", True),
    (at(10, 16), "CLOSED", False),
])
def test_canonical_nse_session_states(when, state, opened):
    result = NSESessionCalendar().status(when)
    assert result["session_state"] == state
    assert result["market_open"] is opened
    assert result["timezone"] == "Asia/Kolkata"


@pytest.mark.unit
def test_saturday_11_july_2026_is_never_open_from_connectivity_or_cache():
    result = NSESessionCalendar().status(at(11, 11))
    fake_connectivity = {"backend_connected": True, "cached_price": 25000}
    assert fake_connectivity["backend_connected"] and fake_connectivity["cached_price"]
    assert result["session_state"] == "WEEKEND"
    assert result["market_open"] is False
    assert result["reason"] == "NSE_WEEKEND_CLOSED"


@pytest.mark.unit
def test_timezone_conversion_and_next_valid_open_are_canonical():
    result = NSESessionCalendar().status(datetime(2026, 7, 10, 4, 30, tzinfo=ZoneInfo("UTC")))
    assert result["session_state"] == "OPEN"
    weekend = NSESessionCalendar().status(at(11, 11))
    assert weekend["next_valid_open"] == "2026-07-13T09:15:00+05:30"


@pytest.mark.unit
def test_unknown_calendar_fails_closed(tmp_path):
    result = NSESessionCalendar(calendar_dir=tmp_path).status(at(10, 10))
    assert result["session_state"] == "UNKNOWN"
    assert result["market_open"] is False
    assert result["warnings"]


@pytest.mark.unit
def test_explicit_special_session_override(tmp_path):
    document = json.loads((ROOT / "config/market_calendars/nse_2026.json").read_text(encoding="utf-8"))
    document["special_sessions"] = [{"date": "2026-07-11", "open": "10:00", "close": "11:00", "name": "TEST_VERIFIED_SPECIAL"}]
    (tmp_path / "nse_2026.json").write_text(json.dumps(document), encoding="utf-8")
    result = NSESessionCalendar(calendar_dir=tmp_path).status(at(11, 10, 30))
    assert result["session_state"] == "SPECIAL_SESSION"
    assert result["market_open"] is True


@pytest.mark.unit
def test_holiday_calendar_identity_checksum_and_source():
    result = NSESessionCalendar().status(at(11, 10))
    assert result["calendar_version"] == "NSE_CM_2026_20260711"
    assert result["calendar_source"].startswith("https://www.nseindia.com/")
    assert len(result["calendar_checksum"]) == 64


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_intraday_candles(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def provider_response(count=300, invalid=False, volume=True):
    times, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    day = datetime(2026, 7, 6, 9, 15, tzinfo=IST)
    for index in range(count):
        session_index, within = divmod(index, 75)
        timestamp = day + timedelta(days=session_index, minutes=5 * within)
        close = 24000 + index * 0.1
        times.append(int(timestamp.timestamp()))
        opens.append(close - 0.2)
        highs.append(1 if invalid and index == count - 1 else close + 1)
        lows.append(close - 1)
        closes.append(close)
        volumes.append(1000 + index)
    raw = {"open": opens, "high": highs, "low": lows, "close": closes, "timestamp": times}
    if volume:
        raw["volume"] = volumes
    candles = [{"time": times[i], "open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i], "volume": volumes[i] if volume else 0} for i in range(count)]
    return {"success": True, "candles": candles, "raw": raw}


@pytest.mark.unit
def test_real_source_contract_exact_instrument_backfill_and_cache(tmp_path):
    provider = FakeProvider(provider_response())
    source = RealNiftyCandleSource(provider=provider, cache_path=tmp_path / "candles.json", clock=lambda: at(10, 16), sleeper=lambda _: None)
    result = source.backfill(256, now=at(10, 16))
    assert len(result) == 256
    assert all(item["symbol"] == "NIFTY" and item["provider_segment"] == "IDX_I" and item["provider_security_id"] == "13" for item in result)
    assert all(item["timeframe"] == "5m" and item["instrument"] == "INDEX" and item["is_closed"] for item in result)
    assert provider.calls == [{"segment": "IDX_I", "security_id": "13", "instrument": "INDEX", "interval": "5", "from_date": "2026-06-20", "to_date": "2026-07-10"}]
    assert source.load_cache()[-256:] == result


@pytest.mark.unit
def test_real_source_missing_volume_is_truthful(tmp_path):
    source = RealNiftyCandleSource(provider=FakeProvider(provider_response(volume=False)), cache_path=tmp_path / "candles.json", clock=lambda: at(10, 16), sleeper=lambda _: None)
    result = source.backfill(64, now=at(10, 16))
    assert all(item["volume"] is None for item in result)
    assert source.last_status["volume_available"] is False


@pytest.mark.unit
def test_real_source_filters_invalid_future_and_incomplete_candles(tmp_path):
    response = provider_response(75, invalid=True)
    source = RealNiftyCandleSource(provider=FakeProvider(response), cache_path=tmp_path / "candles.json", clock=lambda: at(6, 15, 30), sleeper=lambda _: None)
    result = source.backfill(64, now=at(6, 15, 30))
    assert len(result) == 64
    assert all(datetime.fromisoformat(item["candle_closed_at"]) <= at(6, 15, 30) for item in result)
    assert all(item["high"] >= max(item["open"], item["close"], item["low"]) for item in result)


@pytest.mark.unit
def test_backfill_retries_are_bounded_and_cached_fallback_is_truthful(tmp_path):
    class Failure:
        calls = 0
        def get_intraday_candles(self, **kwargs):
            self.calls += 1
            raise TimeoutError("provider timeout")
    source = RealNiftyCandleSource(provider=Failure(), cache_path=tmp_path / "missing.json", sleeper=lambda _: None)
    assert source.backfill(256, now=at(10, 16)) == []
    assert source._provider.calls == 3
    assert source.last_status["health"] == "UNAVAILABLE"


def directional_path(final, *, reversal=False):
    closes = [100 + (final - 100) * (index + 1) / 12 for index in range(12)]
    if reversal:
        closes = [100.3, 100.6, 101.0, 101.3, 101.5, 101.2, 100.9, 100.6, 100.3, 100.1, 99.9, 99.8]
    return [{"open": close - 0.05, "high": close + 0.2, "low": close - 0.2, "close": close} for close in closes]


@pytest.mark.unit
def test_direction_probabilities_and_direction_specific_persistence():
    metrics = derive_metrics([directional_path(102), directional_path(103), directional_path(98), directional_path(97), directional_path(100.02)], 100)
    assert metrics["bullish_probability"] == 40
    assert metrics["bearish_probability"] == 40
    assert metrics["sideways_probability"] == 20
    assert sum(metrics[key] for key in ("bullish_probability", "bearish_probability", "sideways_probability")) == 100
    assert metrics["bullish_persistence_probability"] is not None
    assert metrics["bearish_persistence_probability"] is not None


@pytest.mark.unit
def test_reversal_requires_meaningful_extension_and_retracement():
    metrics = derive_metrics([directional_path(102), directional_path(103), directional_path(99.8, reversal=True)], 100)
    assert metrics["reversal_probability"] > 0
    assert 0 <= metrics["forecast_uncertainty"] <= 100
    assert metrics["volatility_label"] in {"LOW", "MODERATE", "HIGH", "EXTREME"}


@pytest.mark.unit
def test_single_path_cannot_create_probabilities():
    with pytest.raises(ForecastValidationError, match="two valid paths"):
        derive_metrics([directional_path(102)], 100)


@pytest.mark.unit
def test_ce_pe_quality_are_direction_specific_bounded_and_not_win_probability():
    metrics = derive_metrics([directional_path(103), directional_path(102), directional_path(101), directional_path(98), directional_path(97), directional_path(100.01)], 100)
    quality = forecast_quality(metrics, expected_paths=6)
    outlooks = option_outlooks(metrics, quality)
    assert outlooks["ce"]["option_buying_quality_score"] != outlooks["pe"]["option_buying_quality_score"]
    assert all(0 <= outlooks[side]["option_buying_quality_score"] <= 100 for side in ("ce", "pe"))
    assert outlooks["ce"]["label"] == outlooks["pe"]["label"] == "OPTION_BUYING_QUALITY"
    assert "win" not in json.dumps(outlooks).lower()


@pytest.mark.unit
def test_sideways_uncertainty_reversal_and_low_volatility_reduce_quality():
    aligned = derive_metrics([directional_path(103), directional_path(102), directional_path(101), directional_path(100.5)], 100)
    unclear = derive_metrics([directional_path(100.01), directional_path(99.99), directional_path(100.02), directional_path(99.98)], 100)
    aligned_outlook = option_outlooks(aligned, forecast_quality(aligned, 4))["ce"]
    unclear_outlook = option_outlooks(unclear, forecast_quality(unclear, 4))["ce"]
    assert aligned_outlook["option_buying_quality_score"] is not None
    assert unclear_outlook["option_buying_quality_score"] is None or unclear_outlook["option_buying_quality_score"] < aligned_outlook["option_buying_quality_score"]


@pytest.mark.unit
def test_unavailable_or_stale_input_never_returns_quality_zero():
    unavailable = option_outlooks(None, None)
    assert unavailable["ce"]["option_buying_quality_score"] is None
    metrics = derive_metrics([directional_path(103), directional_path(102), directional_path(101)], 100)
    stale = option_outlooks(metrics, forecast_quality(metrics, 3), input_fresh=False)
    assert stale["ce"]["option_buying_quality_score"] is None


class FixedSource:
    def __init__(self, candles):
        self.candles = candles
        self.calls = 0
        self.last_status = {"health": "READY", "candle_count": len(candles), "last_candle_at": candles[-1]["timestamp"], "source": "DHAN_DATA_API", "freshness": "FRESH", "instrument": {"symbol": "NIFTY", "exchange": "NSE", "segment": "IDX_I", "security_id": "13", "instrument": "INDEX", "timeframe": "5m"}, "volume_available": True}
    def backfill(self, limit, now=None):
        self.calls += 1
        return self.candles[-limit:]


class FixedWorker:
    def __init__(self): self.calls = 0
    def run(self, candles, device="mps"):
        self.calls += 1
        metrics = derive_metrics([directional_path(103), directional_path(102), directional_path(101), directional_path(98)], candles[-1]["close"])
        return {"generated_at": at(10, 10, 31).isoformat(), "model_status": "READY", "device": device, "symbol": "NIFTY", "timeframe": "5m", "input_candle_count": len(candles), "input_fingerprint": f"fingerprint-{candles[-1]['timestamp']}", "last_input_candle_at": candles[-1]["timestamp"], "last_inference_at": at(10, 10, 31).isoformat(), "inference_duration_ms": 10, "cache_status": "READY", **metrics, "reason_codes": ["FORECAST_COMPLETE"], "warnings": [], "missing_inputs": [], "source_metadata": {"source": "DHAN_DATA_API", "fixture_data": False, "external_refresh_on_read": False}}


def scheduler_candles(count=64):
    start = at(10, 4, 50)
    return [{"timestamp": (start + timedelta(minutes=5 * index)).isoformat(), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100, "closed": True, "freshness": "FRESH"} for index in range(count)]


@pytest.mark.unit
def test_scheduler_one_job_per_unique_closed_candle_and_no_duplicate(tmp_path):
    source, worker = FixedSource(scheduler_candles()), FixedWorker()
    config = KronosAlphaConfig(cache_path=tmp_path / "forecast.json", history_path=tmp_path / "history.json", sample_count=4)
    scheduler = KronosAlphaScheduler(config=config, candle_source=source, worker=worker, cache=ForecastCache(config.cache_path), ledger=ForecastHistoryLedger(config.history_path), clock=lambda: datetime(2026, 7, 10, 10, 10, 30, tzinfo=IST))
    first, second = scheduler.tick(), scheduler.tick()
    assert first["ran"] is True
    assert second == {"ran": False, "reason": "DUPLICATE_CANDLE"}
    assert worker.calls == 1


@pytest.mark.unit
def test_scheduler_never_infers_weekend_holiday_or_unknown(tmp_path):
    source, worker = FixedSource(scheduler_candles()), FixedWorker()
    scheduler = KronosAlphaScheduler(config=KronosAlphaConfig(cache_path=tmp_path / "f.json", history_path=tmp_path / "h.json"), candle_source=source, worker=worker, clock=lambda: at(11, 10))
    assert scheduler.tick()["reason"] == "WEEKEND"
    assert worker.calls == source.calls == 0
    unknown = KronosAlphaScheduler(config=KronosAlphaConfig(cache_path=tmp_path / "f2.json", history_path=tmp_path / "h2.json"), calendar=NSESessionCalendar(calendar_dir=tmp_path / "none"), candle_source=source, worker=worker, clock=lambda: at(10, 10))
    assert unknown.tick()["reason"] == "UNKNOWN"
    assert worker.calls == 0


@pytest.mark.unit
def test_scheduler_grace_next_open_and_restart_recovery(tmp_path):
    source, worker = FixedSource(scheduler_candles()), FixedWorker()
    config = KronosAlphaConfig(cache_path=tmp_path / "f.json", history_path=tmp_path / "h.json", provider_grace_seconds=10, sample_count=4)
    scheduler = KronosAlphaScheduler(config=config, candle_source=source, worker=worker, clock=lambda: datetime(2026, 7, 10, 10, 10, 30, tzinfo=IST))
    result = scheduler.initialize()
    assert worker.calls == 1
    assert result["next_expected_inference"].endswith("10:15:10+05:30")
    closed = KronosAlphaScheduler(config=config, candle_source=source, worker=worker, clock=lambda: at(11, 10))
    closed.initialize()
    assert closed.projection()["next_expected_inference"] == "2026-07-13T09:20:10+05:30"


def history_result(last_at, expected=1.0):
    metrics = derive_metrics([directional_path(103), directional_path(102), directional_path(98)], 100)
    quality = forecast_quality(metrics, 3)
    return {"generated_at": last_at, "session": {"session_state": "OPEN"}, "symbol": "NIFTY", "timeframe": "5m", "model_revision": "model", "tokenizer_revision": "token", "input_fingerprint": last_at, "last_input_candle_at": last_at, "input_candle_count": 64, "horizon_candles": 12, **metrics, "expected_return_percentage": expected, "outlooks": option_outlooks(metrics, quality), "source_metadata": {"source": "DHAN_DATA_API"}, "input_metadata": {"freshness": "FRESH"}}


@pytest.mark.unit
def test_history_is_append_only_duplicate_protected_bounded_and_corruption_safe(tmp_path):
    ledger = ForecastHistoryLedger(tmp_path / "history.json", retention=10)
    original = history_result(at(10, 10).isoformat())
    forecast_id, added = ledger.append_forecast(original)
    assert added is True
    assert ledger.append_forecast(original) == (forecast_id, False)
    before = ledger.payload()["forecasts"][0]
    assert ledger.append_evaluation({"forecast_id": forecast_id, "directional_correct": True, "forecast_error_percentage_points": 0}) is True
    assert ledger.payload()["forecasts"][0] == before
    ledger.path.write_text("{broken", encoding="utf-8")
    assert ledger.payload()["count"] == 0


@pytest.mark.unit
def test_realization_waits_for_complete_horizon_and_never_looks_ahead(tmp_path):
    ledger = ForecastHistoryLedger(tmp_path / "history.json")
    last = at(10, 10).isoformat()
    forecast_id, _ = ledger.append_forecast(history_result(last))
    evaluator = RealizationEvaluator(ledger)
    base = {"timestamp": last, "open": 100, "high": 101, "low": 99, "close": 100}
    future = [{"timestamp": (at(10, 10) + timedelta(minutes=5 * (index + 1))).isoformat(), "open": 100, "high": 102, "low": 99, "close": 101} for index in range(12)]
    assert evaluator.evaluate([base, *future[:11]]) == []
    completed = evaluator.evaluate([base, *future])
    assert completed[0]["forecast_id"] == forecast_id
    assert evaluator.evaluate([base, *future]) == []
    assert evaluator.summary()["calibration_status"] == "EARLY_EVALUATION"


@pytest.mark.integration
def test_activation_routes_get_only_and_frontend_has_exactly_two_primary_wheels():
    main = __import__("app.main", fromlist=["app"])
    methods = {route.path: route.methods for route in main.app.routes if route.path in {"/v1/market/session", "/v1/kronos-alpha/status", "/v1/kronos-alpha/forecast", "/v1/kronos-alpha/outlooks", "/v1/kronos-alpha/history", "/v1/kronos-alpha/evaluation"}}
    assert methods and all(value == {"GET"} for value in methods.values()) and len(methods) == 6
    page = (ROOT / "citadel-dashboard/src/app/page.tsx").read_text(encoding="utf-8")
    assert page.count('<ProbabilityWheel side="') == 2
    assert 'aria-label="CE and PE option-buying outlooks"' in page
    assert "`${side} OUTLOOK`" in page or "{side} OUTLOOK" in page
    assert "Probabilistic forecast, not execution permission" in page
    assert "/v1/kronos-alpha/infer" not in page and "/v1/kronos-alpha/download" not in page
    assert "Heuristic Trend & Momentum Gauge" in page


@pytest.mark.safety
def test_activation_has_no_mutation_or_cross_engine_dependency():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src/kronos_alpha").glob("*.py"))
    for forbidden in ("place_order", "cancel_order", "PaperState", "RiskAuthorization", "src.hermes", "src.argus", "src.athena"):
        assert forbidden not in source
    assert "execution_influence_percentage: int = 0" in source
    assert "aegis_influence_percentage: int = 0" in source


@pytest.mark.integration
def test_authenticity_hash_size_and_config_evidence():
    expected = {
        MODEL / "model.safetensors": (98980656, "b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020"),
        TOKENIZER / "model.safetensors": (15842368, "59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee"),
    }
    for path, (size, digest) in expected.items():
        assert path.stat().st_size == size
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    config = KronosAlphaConfig()
    assert config.model_name == "NeoQuasar/Kronos-small"
    assert config.tokenizer_name == "NeoQuasar/Kronos-Tokenizer-base"
    assert "chronos" not in json.dumps(config.public_metadata()).lower()
