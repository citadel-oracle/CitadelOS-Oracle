from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.strategy_lab.completed_candle import CompletedCandleContextProvider
from src.strategy_lab.option_charts import OptionChartCandleFeed
from src.strategy_lab.strategies.pullback_master.deployment import (
    SOURCE_SHA256,
    build_deployment_request,
)
from src.strategy_lab.strategies.pullback_master.parity import (
    VobNumericObservation,
    active_config_mismatches,
    compare_vob_numeric,
    load_parity_manifest,
    parity_config_hash,
)
from src.strategy_lab.strategies.pullback_master.strategy import (
    PullbackMasterConfig,
    PullbackMasterStrategyEngine,
)


IST = ZoneInfo("Asia/Kolkata")


def _canonical_row(opened_at: str, *, contract: str = "45107", close: float = 100.0):
    opened = datetime.fromisoformat(opened_at)
    return {
        "timestamp": opened.isoformat(),
        "candle_closed_at": (opened + timedelta(minutes=5)).isoformat(),
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 100.0,
        "closed": True,
        "is_closed": True,
        "contract": contract,
        "chart_contract": {"security_id": contract, "option_type": "PE"},
    }


def _chart_context(opened_at: str, timeframe: str, canonical_rows):
    opened = datetime.fromisoformat(opened_at)
    minutes = int(timeframe[:-1])
    return {
        "contract": "45107",
        "timeframe": timeframe,
        "canonical_5m_candles": canonical_rows,
        "bar": {
            "index": int(opened.timestamp() // 60),
            "timestamp": opened.isoformat(),
            "candle_closed_at": (opened + timedelta(minutes=minutes)).isoformat(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 10.0,
            "confirmed": True,
        },
    }


@pytest.mark.unit
def test_one_minute_sees_completed_five_minute_value_only_at_exact_close_boundary():
    rows = [
        _canonical_row("2026-08-14T09:15:00+05:30", close=100.0),
        _canonical_row("2026-08-14T09:20:00+05:30", close=101.0),
    ]
    engine = PullbackMasterStrategyEngine(PullbackMasterConfig.tradingview_v2_20260814())

    before = engine.evaluate(_chart_context("2026-08-14T09:18:00+05:30", "1m", rows))
    assert before["shared_core"]["supertrend_source_status"] == "CANONICAL_5M_WARMUP_REQUIRED"
    assert before["shared_core"]["supertrend_last_timestamp"] is None

    boundary = engine.evaluate(_chart_context("2026-08-14T09:19:00+05:30", "1m", rows))
    first_timestamp = int(datetime.fromisoformat(rows[0]["timestamp"]).timestamp() * 1000)
    assert boundary["shared_core"]["supertrend_source_status"] == "ADVANCED_COMPLETED_5M"
    assert boundary["shared_core"]["supertrend_last_timestamp"] == first_timestamp

    after = engine.evaluate(_chart_context("2026-08-14T09:20:00+05:30", "1m", rows))
    assert after["shared_core"]["supertrend_source_status"] == "CARRIED_FORWARD_COMPLETED_5M"
    assert after["shared_core"]["supertrend_last_timestamp"] == first_timestamp


@pytest.mark.unit
def test_three_minute_evaluation_carries_last_completed_five_minute_without_future_leakage():
    rows = [
        _canonical_row("2026-08-14T09:15:00+05:30", close=100.0),
        _canonical_row("2026-08-14T09:20:00+05:30", close=101.0),
    ]
    engine = PullbackMasterStrategyEngine(PullbackMasterConfig.tradingview_v2_20260814())

    before = engine.evaluate(_chart_context("2026-08-14T09:15:00+05:30", "3m", rows))
    assert before["shared_core"]["supertrend_last_timestamp"] is None

    first_after = engine.evaluate(_chart_context("2026-08-14T09:18:00+05:30", "3m", rows))
    first_timestamp = int(datetime.fromisoformat(rows[0]["timestamp"]).timestamp() * 1000)
    second_timestamp = int(datetime.fromisoformat(rows[1]["timestamp"]).timestamp() * 1000)
    assert first_after["shared_core"]["supertrend_last_timestamp"] == first_timestamp

    minute_before = engine.evaluate(_chart_context("2026-08-14T09:21:00+05:30", "3m", rows))
    assert minute_before["shared_core"]["supertrend_last_timestamp"] == first_timestamp

    after_second_close = engine.evaluate(_chart_context("2026-08-14T09:24:00+05:30", "3m", rows))
    assert after_second_close["shared_core"]["supertrend_last_timestamp"] == second_timestamp


@pytest.mark.unit
def test_context_provider_filters_future_and_cross_contract_canonical_rows():
    rows = [
        _canonical_row("2026-08-14T09:15:00+05:30", contract="45107"),
        _canonical_row("2026-08-14T09:20:00+05:30", contract="45107"),
        _canonical_row("2026-08-14T09:15:00+05:30", contract="45102"),
    ]

    class Source:
        def load_cache(self):
            return rows

    provider = CompletedCandleContextProvider(
        candle_source=None, argus_provider=lambda: {}, canonical_5m_source=Source()
    )
    legal = provider._canonical_5m_history(
        candle_closed_at=datetime(2026, 8, 14, 9, 21, tzinfo=IST), security_id="45107"
    )
    assert [row["contract"] for row in legal] == ["45107"]
    assert [row["timestamp"] for row in legal] == ["2026-08-14T03:45:00+00:00"]


@pytest.mark.unit
def test_option_five_minute_source_reuses_vob_session_bucket_and_keeps_contract_lineage():
    feed = OptionChartCandleFeed(dhan=object(), instrument_master=object())
    rows = []
    for offset in range(6):
        opened = datetime(2026, 8, 14, 9, 15, tzinfo=IST) + timedelta(minutes=offset)
        rows.append({
            "timestamp": opened.isoformat(),
            "candle_closed_at": (opened + timedelta(minutes=1)).isoformat(),
            "open": 100.0 + offset,
            "high": 101.0 + offset,
            "low": 99.0 + offset,
            "close": 100.5 + offset,
            "volume": 10.0,
            "closed": True,
            "is_closed": True,
            "contract": "45107",
            "chart_contract": {"security_id": "45107", "option_type": "PE"},
        })
    result = feed._aggregate_five_minute(rows)
    assert len(result) == 1
    assert result[0]["timestamp"] == "2026-08-14T09:15:00+05:30"
    assert result[0]["candle_closed_at"] == "2026-08-14T09:20:00+05:30"
    assert (result[0]["open"], result[0]["high"], result[0]["low"], result[0]["close"]) == (
        100.0, 105.0, 99.0, 104.5,
    )
    assert result[0]["contract"] == "45107"


@pytest.mark.unit
def test_authoritative_manifest_is_frozen_and_native_binding_has_no_setting_drift():
    manifest = load_parity_manifest()
    assert manifest["authority"]["pine_sha256"] == "4527ffb1cc5c02d4fb023d37d9801950f5c666e0b71fc376c981f0fa5d59a715"
    assert manifest["canonical_5m_supertrend"] == {
        "pine_expression": "ta.supertrend(vobSTTrailFactor, vobSTTrailLen)",
        "source_series": ["high", "low", "close"],
        "timeframe": "5",
        "atr_length": 10,
        "factor": 3.5,
        "bullish_direction": -1,
        "request_security_gaps": "barmerge.gaps_off",
        "request_security_lookahead": "barmerge.lookahead_off",
        "historical_availability": "AVAILABLE_ON_LTF_BAR_WHOSE_CLOSE_REACHES_THE_COMPLETED_5M_CLOSE",
        "forming_5m_usable_for_deterministic_replay": False,
        "trail_requires_confirmed_chart_bar": True,
    }
    assert active_config_mismatches(PullbackMasterConfig.tradingview_v2_20260814()) == {}
    assert len(parity_config_hash()) == 64


@pytest.mark.unit
def test_deployment_records_supplied_pine_and_frozen_parity_authorities():
    deployment = build_deployment_request()
    parameters = deployment.metadata.parameters
    manifest = load_parity_manifest()

    assert parameters["source_sha256"] == SOURCE_SHA256
    assert parameters["parity_authority_pine_sha256"] == manifest["authority"]["pine_sha256"]
    assert parameters["parity_config_hash"] == parity_config_hash(manifest)
    assert parameters["parity_settings_strategy"] == "PULLBACK V2"


@pytest.mark.unit
def test_vob_numeric_comparison_refuses_visual_self_certification():
    citadel = VobNumericObservation(
        contract="NIFTY260818P24400", timeframe="5m",
        formed_at="2026-08-14T13:45:00+05:30", side="BULLISH",
        top=72.0, bottom=69.0, touch_at="2026-08-14T14:00:00+05:30",
    )
    unknown = compare_vob_numeric(citadel=citadel, tradingview=None)
    assert unknown.status == "TV_NUMERIC_EVIDENCE_REQUIRED"
    assert unknown.tradingview is None
    assert compare_vob_numeric(citadel=citadel, tradingview=citadel).status == "MATCH"
