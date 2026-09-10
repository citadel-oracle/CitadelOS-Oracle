from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "src/components/institutional/OracleFuturesVwapChart.tsx"
PROVIDER = ROOT / "src/dashboard/providers/RestDashboardProvider.ts"


def test_chart_uses_distinct_observed_and_prediction_series():
    source = CHART.read_text(encoding="utf-8")
    assert "candleSeriesRef" in source
    assert "ghostSeriesRef" in source
    assert source.count("chart.addSeries(CandlestickSeries") == 2
    assert "ghostSeries.setData(forecast.ghost.map(candleBar))" in source
    assert "candleSeries.setData(candles.map(candleBar))" in source


def test_chart_renders_only_chronos_p10_p50_p90_and_one_tirex_pill():
    source = CHART.read_text(encoding="utf-8")
    assert all(label in source for label in ("p10SeriesRef", "p50SeriesRef", "p90SeriesRef"))
    assert source.count("className={styles.tirexPill}") == 1
    assert "TiRex <i>·</i>" in source
    assert "nowDividerRef" in source
    assert "FORECAST · HISTORICAL REPLAY" in source


def test_frontend_rejects_stale_or_wrong_identity_forecast():
    source = CHART.read_text(encoding="utf-8")
    assert "actual !== identity" in source
    assert "next.revision >= previous.revision" in source
    assert "time <= sourceEpoch" in source


def test_sse_provider_reuses_existing_transport_without_direct_model_fetch():
    source = PROVIDER.read_text(encoding="utf-8")
    assert "event.projection.futures_forecast" in source
    assert "futures_chart: futuresChart" in source
    assert "/v1/kronos-alpha" not in source
    assert "/v1/chronos-2" not in source
    assert "tirex" not in source.lower()


def test_forecast_replacement_never_mutates_observed_array():
    source = CHART.read_text(encoding="utf-8")
    forecast_effect = source[source.index("ghostSeries.setData"):source.index("syncOverlayRef.current()", source.index("ghostSeries.setData"))]
    assert "candles.push" not in forecast_effect
    assert "candleSeries.update" not in forecast_effect
