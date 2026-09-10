import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from tests.frontend_dashboard_contract import assert_centralized_feed

from src.kronos_alpha.cache import ForecastCache
from src.kronos_alpha.config import KronosAlphaConfig
from src.kronos_alpha.metrics import ForecastValidationError, derive_metrics, normalize_paths
from src.kronos_alpha.service import KronosAlphaService
from src.kronos_alpha.validation import CandleValidationError, validate_candles
from src.futures_forecast import FuturesForecastOrchestrator


NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def candles(count=64, *, unsorted=False, volume=True):
    result = []
    for index in range(count):
        close = 100 + index * 0.1
        item = {
            "timestamp": (NOW - timedelta(minutes=5 * (count - index))).isoformat(),
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "closed": True,
        }
        if volume:
            item["volume"] = 1000 + index
        result.append(item)
    return list(reversed(result)) if unsorted else result


def path(final, horizon=12):
    return [
        {"open": 100, "high": max(101, final), "low": min(99, final), "close": 100 + (final - 100) * (index + 1) / horizon}
        for index in range(horizon)
    ]


@pytest.mark.unit
def test_config_freezes_official_identity_and_zero_influence():
    config = KronosAlphaConfig()
    assert config.model_name == "NeoQuasar/Kronos-small"
    assert config.model_revision == "901c26c1332695a2a8f243eb2f37243a37bea320"
    assert config.tokenizer_revision == "0e0117387f39004a9016484a186a908917e22426"
    assert config.mode == "SHADOW"
    assert config.execution_influence_percentage == config.aegis_influence_percentage == 0


@pytest.mark.unit
def test_valid_closed_candles_are_accepted_and_volume_is_optional():
    assert len(validate_candles(candles(volume=False), now=NOW)) == 64


@pytest.mark.unit
def test_unsorted_candles_are_normalized_deterministically():
    result = validate_candles(candles(unsorted=True), now=NOW)
    assert result == sorted(result, key=lambda item: item["timestamp"])


@pytest.mark.unit
@pytest.mark.parametrize("mutation", [
    lambda values: values.__setitem__(1, {**values[0]}),
    lambda values: values[0].__setitem__("high", 1),
    lambda values: values[0].__setitem__("open", float("nan")),
    lambda values: values[0].__setitem__("closed", False),
])
def test_malformed_candles_fail_closed(mutation):
    values = candles()
    mutation(values)
    with pytest.raises(CandleValidationError):
        validate_candles(values, now=NOW)


@pytest.mark.unit
def test_insufficient_and_future_context_fail_closed():
    with pytest.raises(CandleValidationError, match="insufficient"):
        validate_candles(candles(10), now=NOW)
    future = candles()
    future[-1]["timestamp"] = (NOW + timedelta(minutes=5)).isoformat()
    with pytest.raises(CandleValidationError, match="future"):
        validate_candles(future, now=NOW)


@pytest.mark.unit
def test_context_is_capped_at_official_limit():
    assert len(validate_candles(candles(600), now=NOW, context_limit=512)) == 512


@pytest.mark.unit
def test_forecast_normalization_repairs_only_ohlc_envelope():
    result = normalize_paths([[{"open": 100, "high": 99, "low": 101, "close": 102}]])
    assert result[0][0] == {"open": 100, "high": 102, "low": 99, "close": 102}


@pytest.mark.unit
def test_non_finite_and_mismatched_forecasts_are_rejected():
    with pytest.raises(ForecastValidationError):
        normalize_paths([[{"open": 1, "high": 2, "low": 0, "close": float("inf")} ]])
    with pytest.raises(ForecastValidationError):
        normalize_paths([path(101, 2), path(99, 3)])


@pytest.mark.unit
def test_probabilities_are_bounded_and_sum_to_one_hundred():
    result = derive_metrics([path(102), path(98), path(100.05)], 100)
    probabilities = [result[key] for key in ("bullish_probability", "bearish_probability", "sideways_probability")]
    assert all(0 <= value <= 100 for value in probabilities)
    assert sum(probabilities) == pytest.approx(100)
    assert result["path_count"] == 3
    assert result["horizon_minutes"] == 60


@pytest.mark.unit
def test_expected_return_quantiles_volatility_and_uncertainty_are_formula_based():
    result = derive_metrics([path(102), path(104), path(98)], 100)
    assert result["expected_return_percentage"] == pytest.approx(4 / 3)
    assert result["median_return_percentage"] == pytest.approx(2)
    assert result["upside_quantile"] == pytest.approx(4)
    assert result["downside_quantile"] == pytest.approx(-2)
    assert result["forecast_dispersion"] > 0
    assert 0 <= result["forecast_uncertainty"] <= 100
    assert result["forecast_volatility"] >= 0


@pytest.mark.unit
def test_persistence_and_reversal_are_deterministic():
    result = derive_metrics([path(102), path(103), path(98), path(97)], 100)
    assert result["bullish_persistence_probability"] is not None
    assert result["bearish_persistence_probability"] is not None
    assert 0 <= result["reversal_probability"] <= 100


@pytest.mark.unit
def test_cache_atomic_round_trip_and_corruption_failure(tmp_path):
    cache = ForecastCache(tmp_path / "forecast.json")
    written = cache.write({"generated_at": "2026-01-05T12:00:00Z", "model_status": "READY"})
    assert cache.read() == written
    cache.path.write_text("{broken", encoding="utf-8")
    assert cache.read() is None


@pytest.mark.unit
def test_missing_cache_is_truthfully_unavailable(tmp_path):
    service = KronosAlphaService(KronosAlphaConfig(cache_path=tmp_path / "missing.json"))
    result = service.status()
    assert result["model_status"] == "UNAVAILABLE"
    assert result["bullish_probability"] is None
    assert result["mode"] == "SHADOW"
    assert result["execution_influence_percentage"] == 0
    assert result["source_metadata"]["external_refresh_on_read"] is False


@pytest.mark.unit
def test_stale_cache_is_explicit(tmp_path):
    config = KronosAlphaConfig(cache_path=tmp_path / "forecast.json", stale_after_seconds=1)
    cache = ForecastCache(config.cache_path)
    cache.write({"generated_at": "2020-01-01T00:00:00Z", "model_status": "READY", "reason_codes": ["FORECAST_COMPLETE"]})
    result = KronosAlphaService(config, cache).status()
    assert result["model_status"] == "STALE"
    assert "FORECAST_STALE" in result["reason_codes"]


@pytest.mark.integration
def test_fastapi_routes_are_get_only_cached_reads(tmp_path):
    main = importlib.import_module("app.main")
    original = main.futures_forecast_orchestrator
    main.futures_forecast_orchestrator = FuturesForecastOrchestrator(
        state_path=tmp_path / "none.json"
    )
    try:
        assert main.kronos_alpha_status()["model_status"] == "UNAVAILABLE"
        assert main.kronos_alpha_forecast()["cache_status"] == "MISSING"
        methods = {route.path: route.methods for route in main.app.routes if route.path.startswith("/v1/kronos-alpha/")}
        assert methods == {
            "/v1/kronos-alpha/status": {"GET"},
            "/v1/kronos-alpha/forecast": {"GET"},
            "/v1/kronos-alpha/outlooks": {"GET"},
            "/v1/kronos-alpha/history": {"GET"},
            "/v1/kronos-alpha/evaluation": {"GET"},
        }
    finally:
        main.futures_forecast_orchestrator.stop()
        main.futures_forecast_orchestrator = original


@pytest.mark.safety
def test_module_has_no_broker_risk_paper_or_execution_dependency():
    root = Path(importlib.import_module("src.kronos_alpha").__file__).parent
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in ("src.broker", "src.risk", "paper_state", "paper_execution", "dhan_client"):
        assert forbidden not in source


@pytest.mark.integration
def test_frontend_polls_cache_without_download_or_inference_controls():
    source = Path("citadel-dashboard/src/app/page.tsx").read_text(encoding="utf-8")
    assert_centralized_feed("kronosAlpha", "kronos_alpha")
    assert "KRONOS ALPHA" in source
    assert "Probabilistic forecast, not execution permission" in source
    assert "/v1/kronos-alpha/download" not in source
    assert "/v1/kronos-alpha/infer" not in source
    assert "Heuristic Trend & Momentum Gauge" in source
