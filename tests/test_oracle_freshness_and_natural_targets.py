"""Regression tests for Oracle provider freshness, multi-timeframe natural targets, and decision gating."""

from datetime import datetime, timezone
import pytest

from src.oracle.analyst.core import AnalystPolicy, MarketAnalystCore
from src.oracle.contracts.analysis import (
    AnalysisSnapshot, OptionContractQuote, seal,
)
from src.oracle.contracts.perception import Availability, FreshnessState


def _make_test_snapshot(
    vob_5m_res=None,
    vob_15m_res=None,
    vob_nearest_res=None,
    spot=24640.0,
    support_low=24616.0,
    support_high=24630.0,
):
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = {
        "source_ids": {"feed": "test-feed"},
        "source_hashes": {"feed": "hash123"},
        "dependency_versions": {"policy": "1.0.0"},
        "provenance": {"service": "test", "advisory_only": True, "execution_influence": "ZERO"},
    }
    source_records = {
        "argus_underlying": {"ltp": spot, "fetched_at": now_iso},
        "vob": {
            "current_nifty_spot": spot,
            "nearest_support": {
                "zone_id": "VOB-NIFTY-5M-BUL-1",
                "zone_low": support_low,
                "zone_high": support_high,
                "role": "SUPPORT",
                "freshness": "STALE",  # 15 touches (zone fatigue), but data is live
            },
            "nearest_resistance": vob_nearest_res,
            "strongest_confluence": {"bullish": {"side": "BULLISH"}},
            "timeframes": {
                "5m": {
                    "current_nifty_price": spot,
                    "nearest_bullish_support": {
                        "zone_id": "VOB-NIFTY-5M-BUL-1",
                        "zone_low": support_low,
                        "zone_high": support_high,
                        "role": "SUPPORT",
                        "freshness": "STALE",
                    },
                    "nearest_bearish_resistance": vob_5m_res,
                },
                "15m": {
                    "nearest_bearish_resistance": vob_15m_res,
                },
            },
        },
        "context_lanes": {
            "1D": {"availability": "AVAILABLE"},
            "1H": {"availability": "AVAILABLE"},
            "15m": {"availability": "AVAILABLE"},
            "4H": {"availability": "AVAILABLE"},
        },
        "canonical_market_assessment": {"directional_bias": "BULLISH"},
        "canonical_features": {"supertrend": {"direction": "BULLISH"}},
        "argus_tactical": {
            "contract_selection": {"directive_contract": {"stretch_state": "NORMAL"}},
            "entry_lifecycle": {"state": "READY"},
        },
        "ose": {"duel": {"state": "CALL ADVANTAGE"}},
    }

    quote = seal(OptionContractQuote(
        correlation_id="test-corr",
        snapshot_id="test-snap",
        decision_id="test-dec",
        instrument_id="NIFTY",
        security_id="41011",
        symbol="NIFTY",
        timeframe="5m",
        source_timestamp=now_iso,
        generated_at=now_iso,
        as_of=now_iso,
        availability=Availability.AVAILABLE,
        freshness_state=FreshnessState.FRESH,
        **meta,
        contract_id="41011",
        trading_symbol="NIFTY260811C24650",
        option_type="CE",
        strike=24650.0,
        expiry="2026-08-11",
        bid=120.0,
        ask=121.0,
        mid=120.5,
        ltp=120.8,
        spread_abs=1.0,
        spread_pct=0.82,
        bid_depth=1000,
        ask_depth=1000,
        distance_atm=10.0,
        delta=0.52,
        gamma=0.002,
        vega=12.5,
        iv=14.5,
        theta=-8.2,
        volume=100000,
        oi=500000,
        authority_rank=1,
        authority_score=85.0,
        authority_status="CANDIDATE",
        rejection_reason=None,
    ))

    return seal(AnalysisSnapshot(
        correlation_id="test-corr",
        snapshot_id="test-snap",
        decision_id="test-dec",
        instrument_id="NIFTY",
        security_id="41011",
        symbol="NIFTY",
        timeframe="5m",
        source_timestamp=now_iso,
        generated_at=now_iso,
        as_of=now_iso,
        availability=Availability.AVAILABLE,
        freshness_state=FreshnessState.FRESH,
        **meta,
        analysis_id="test-snap",
        context_snapshot_id="ctx-snap-1",
        context_hash="ctxhash123",
        lane_hashes={"1D": "h1D", "1H": "h1H", "15m": "h15m"},
        expiry="2026-08-11",
        market_state="OPEN",
        time_remaining_seconds=3600.0,
        source_states={"argus": "FRESH", "vob": "FRESH", "ose": "FRESH"},
        source_timestamps={"argus": now_iso, "vob": now_iso, "ose": now_iso},
        source_records=source_records,
        visual_claims=(),
        candidate_contracts=(quote,),
        compatible=True,
        compatibility_reasons=(),
        data_completeness=100,
    ))


def test_multi_timeframe_natural_target_fallback_when_5m_broken():
    """When 5m resistance is broken (None), analyst must fall back to multi-TF resistance."""
    res_15m = {
        "zone_id": "VOB-NIFTY-15M-BEA-1",
        "zone_low": 24760.0,
        "zone_high": 24774.3,
        "role": "RESISTANCE",
        "timeframe": "15m",
    }
    # 5m resistance is None (broken earlier in session)
    snapshot = _make_test_snapshot(
        vob_5m_res=None,
        vob_15m_res=res_15m,
        vob_nearest_res=res_15m,
        spot=24640.0,
        support_low=24616.0,
        support_high=24630.0,
    )

    analyst = MarketAnalystCore()
    underlying, timing, options = analyst.assess(snapshot)

    # In unpatched code, natural_targets is EMPTY and blockers contain NATURAL_TARGET_UNAVAILABLE
    assert len(underlying.natural_targets) > 0, "Natural targets must not be empty"
    assert underlying.natural_targets[0].level == 24774.3
    assert underlying.location_quality == "FAVOURABLE"
    assert "NATURAL_TARGET_UNAVAILABLE" not in underlying.blockers
    assert "NO_LOCATION_EDGE" not in underlying.blockers

    # Option capture assessment must compute valid execution estimate with positive RR
    assert options.execution_estimate is not None
    assert len(options.execution_estimate.target_premiums) > 0
    assert len(options.execution_estimate.resulting_rr) > 0
    assert options.execution_estimate.resulting_rr[0] >= 1.5
    assert "PREMIUM_TARGET_MAPPING_UNAVAILABLE" not in options.blockers
    assert "INSUFFICIENT_NATURAL_RR" not in options.blockers


def test_safety_and_paper_only_invariant():
    """Oracle analysis must remain advisory with zero execution influence."""
    snapshot = _make_test_snapshot()
    analyst = MarketAnalystCore()
    underlying, _, _ = analyst.assess(snapshot)

    assert underlying.provenance.get("advisory_only") is True
    assert underlying.provenance.get("execution_influence") == "ZERO"
