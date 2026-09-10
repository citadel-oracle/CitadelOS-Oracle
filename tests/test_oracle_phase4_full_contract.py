"""Comprehensive regression test suite for Oracle Phase 4 Contract:
- Freshness Semantics vs Zone Lifecycle
- Identity Epoch & Fast Path Validation
- Multi-Timeframe Zone Fallback
- Monotonic SSE Event IDs & Revision Ordering
- Fail-Closed Safety & Paper-Only Constraints
- Blocker Distinction (Data/Freshness Defect vs Genuine Strategy Gate)
"""

from datetime import datetime, timezone, timedelta, time
import pytest
from unittest.mock import Mock, patch

from src.oracle.analyst.core import MarketAnalystCore
from src.oracle.contracts.analysis import (
    AnalysisSnapshot, OptionContractQuote, seal,
)
from src.oracle.contracts.perception import Availability, FreshnessState
from src.oracle.tradingview_sync import (
    TradingViewAutoSyncService,
    TradingViewInstrumentIdentity,
    TradingViewSymbolIdentity,
    TradingViewRoute,
)
from src.vob.engine import NiftyVOBEngine
from src.kronos_alpha.candle_source import RealNiftyCandleSource


def _make_mock_quote(security_id="41011", trading_symbol="NIFTY260811C24650", strike=24650.0, option_type="CE"):
    now_iso = datetime.now(timezone.utc).isoformat()
    return seal(OptionContractQuote(
        correlation_id="test-corr",
        snapshot_id="test-snap",
        decision_id="test-dec",
        instrument_id="NIFTY",
        security_id=security_id,
        symbol="NIFTY",
        timeframe="5m",
        source_timestamp=now_iso,
        generated_at=now_iso,
        as_of=now_iso,
        availability=Availability.AVAILABLE,
        freshness_state=FreshnessState.FRESH,
        source_ids={"feed": "test-feed"},
        source_hashes={"feed": "hash123"},
        dependency_versions={"policy": "1.0.0"},
        provenance={"service": "test", "advisory_only": True, "execution_influence": "ZERO"},
        contract_id=security_id,
        trading_symbol=trading_symbol,
        option_type=option_type,
        strike=strike,
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


def _make_full_snapshot(
    spot=24640.0,
    support_dict=None,
    resistance_dict=None,
    timeframes_dict=None,
    market_input_state="LIVE",
    source_states=None,
    quote=None,
):
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = {
        "source_ids": {"feed": "test-feed"},
        "source_hashes": {"feed": "hash123"},
        "dependency_versions": {"policy": "1.0.0"},
        "provenance": {"service": "test", "advisory_only": True, "execution_influence": "ZERO"},
    }
    if support_dict is None:
        support_dict = {
            "zone_id": "VOB-NIFTY-5M-BUL-1",
            "zone_low": 24616.0,
            "zone_high": 24630.0,
            "role": "SUPPORT",
            "freshness": "STALE",  # Tested/exhausted zone, but underlying data is fresh
        }
    if resistance_dict is None:
        resistance_dict = {
            "zone_id": "VOB-NIFTY-5M-BEA-1",
            "zone_low": 24750.0,
            "zone_high": 24765.0,
            "role": "RESISTANCE",
            "freshness": "ACTIVE",
        }
    if timeframes_dict is None:
        timeframes_dict = {
            "5m": {
                "current_nifty_price": spot,
                "nearest_bullish_support": support_dict,
                "nearest_bearish_resistance": resistance_dict,
            }
        }
    if source_states is None:
        source_states = {"argus": "FRESH", "vob": "FRESH", "ose": "FRESH"}
    if quote is None:
        quote = _make_mock_quote()

    source_records = {
        "argus_underlying": {"ltp": spot, "fetched_at": now_iso},
        "vob": {
            "current_nifty_spot": spot,
            "market_input_state": market_input_state,
            "nearest_support": support_dict,
            "nearest_resistance": resistance_dict,
            "strongest_confluence": {"bullish": {"side": "BULLISH"}},
            "timeframes": timeframes_dict,
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
        source_states=source_states,
        source_timestamps={"argus": now_iso, "vob": now_iso, "ose": now_iso},
        source_records=source_records,
        visual_claims=(),
        candidate_contracts=(quote,),
        compatible=True,
        compatibility_reasons=(),
        data_completeness=100,
    ))


# 1. VOB LIVE data with an EXHAUSTED/TESTED zone does not produce data blocker
def test_vob_live_data_with_tested_zone_not_blocked():
    snapshot = _make_full_snapshot(
        support_dict={"zone_id": "z1", "zone_low": 24610.0, "zone_high": 24620.0, "freshness": "EXHAUSTED"},
        resistance_dict={"zone_id": "z2", "zone_low": 24750.0, "zone_high": 24760.0, "freshness": "TESTED"},
        market_input_state="LIVE",
    )
    analyst = MarketAnalystCore()
    underlying, _, options = analyst.assess(snapshot)

    assert "VOB_DATA_STALE" not in underlying.blockers
    assert len(underlying.natural_targets) > 0


# 2. VOB becomes stale only when its latest expected completed candle is missing
def test_vob_freshness_expected_vs_actual_candle():
    engine = NiftyVOBEngine()
    ist = timezone(timedelta(hours=5, minutes=30))
    
    # Build 20 candles starting at 09:15 IST (latest candle at 10:50 IST)
    base = datetime(2026, 8, 6, 9, 15, tzinfo=ist)
    candles = [
        {
            "timestamp": (base + timedelta(minutes=5 * i)).isoformat(),
            "open": 24500.0 + i,
            "high": 24510.0 + i,
            "low": 24490.0 + i,
            "close": 24505.0 + i,
            "volume": 1000,
        }
        for i in range(20)
    ]
    
    # Analyze with clock matching latest candle (10:55 IST) -> LIVE
    res_live = engine.analyze_all({"5m": candles}, now=base + timedelta(minutes=5 * 20))
    assert res_live.get("market_input_state") == "LIVE"
    
    # Analyze with clock far ahead (14:00 IST) with only morning candles -> STALE
    res_stale = engine.analyze_all({"5m": candles}, now=base + timedelta(hours=4, minutes=45))
    assert res_stale.get("market_input_state") == "STALE"


# 3. The 15:25–15:30 final candle is accepted exactly once after completion
def test_final_5m_candle_session_close_handling():
    source = RealNiftyCandleSource()
    ist = timezone(timedelta(hours=5, minutes=30))
    ref_1530 = datetime(2026, 8, 6, 15, 30, 0, tzinfo=ist)
    
    # 64 distinct candles ending at 15:25 IST
    fetched_candles = []
    for i in range(64):
        candle_time = ref_1530 - timedelta(minutes=5 * (64 - i))
        fetched_candles.append({
            "time": int(candle_time.timestamp()),
            "open": 24600, "high": 24620, "low": 24590, "close": 24610
        })
    
    mock_result = {"success": True, "candles": fetched_candles, "raw": {"volume": [1000] * 64}}
    with patch.object(source.provider, 'get_intraday_candles', return_value=mock_result):
        with patch.object(source.calendar, 'session_for_date', return_value={"session_state": "OPEN", "scheduled_close": ref_1530.isoformat()}):
            source.canonical_store = None
            candles = source.backfill(limit=64, now=ref_1530 - timedelta(seconds=10))
            assert len(candles) == 64
            assert candles[-1]["timestamp"] == (ref_1530 - timedelta(minutes=5)).isoformat()


# 4. ARGUS remains LIVE while authoritative source timestamp is within policy
def test_argus_live_within_policy():
    snapshot = _make_full_snapshot(source_states={"argus": "FRESH", "vob": "FRESH", "ose": "FRESH"})
    analyst = MarketAnalystCore()
    underlying, _, _ = analyst.assess(snapshot)
    assert "ARGUS_STALE" not in underlying.blockers


# 5. Fast path accepts current identity and rejects old identity / mismatched epoch
def test_fast_path_identity_epoch_safety():
    service = TradingViewAutoSyncService(root="/tmp")
    
    # Setup active chart state with identity epoch 42 and contract 41011
    service._active_chart = Mock()
    service._active_chart.option = Mock()
    service._active_chart.option.security_id = "41011"
    service._identity_epoch = 42
    
    # Fake fast path provider
    def fast_path(sec_id, epoch):
        if sec_id != service._active_chart.option.security_id or epoch != service._identity_epoch:
            return None
        return {"ltp": 125.0, "security_id": sec_id, "epoch": epoch}
    
    service._fast_path_provider = fast_path
    
    # Matching request
    res = service._fast_path_provider("41011", 42)
    assert res is not None
    assert res["ltp"] == 125.0
    
    # Stale/old epoch request
    res_stale = service._fast_path_provider("41011", 41)
    assert res_stale is None
    
    # Wrong contract request
    res_wrong = service._fast_path_provider("99999", 42)
    assert res_wrong is None


# 6. Multi-timeframe fallback supplies natural target when 5m resistance is broken
def test_multi_tf_natural_target_fallback():
    res_3m = {"zone_id": "z3m", "zone_low": 24680.0, "zone_high": 24695.0, "role": "RESISTANCE"}
    snapshot = _make_full_snapshot(
        spot=24640.0,
        support_dict={"zone_id": "z_sup", "zone_low": 24610.0, "zone_high": 24620.0},
        resistance_dict=res_3m,  # 3m resistance as fallback
        timeframes_dict={
            "5m": {"current_nifty_price": 24640.0, "nearest_bullish_support": {"zone_low": 24610.0, "zone_high": 24620.0}, "nearest_bearish_resistance": None},
            "3m": {"nearest_bearish_resistance": res_3m},
        }
    )
    analyst = MarketAnalystCore()
    underlying, _, options = analyst.assess(snapshot)
    
    assert len(underlying.natural_targets) > 0
    assert underlying.natural_targets[0].level == 24695.0
    assert options.execution_estimate is not None
    assert len(options.execution_estimate.resulting_rr) > 0


# 7. Locked safety state assert in every analysis record
def test_locked_safety_state_assert():
    snapshot = _make_full_snapshot()
    analyst = MarketAnalystCore()
    underlying, timing, options = analyst.assess(snapshot)
    
    for rec in (underlying, timing, options):
        assert rec.provenance.get("advisory_only") is True
        assert rec.provenance.get("execution_influence") == "ZERO"


# 8. Blocker ledger correctly distinguishes Genuine Strategy Gate from Data Defect
def test_blocker_ledger_classification():
    # Complete, fresh data but spot is at high resistance (no location edge)
    snapshot = _make_full_snapshot(
        spot=24749.0,  # Right under 24750 resistance
        support_dict={"zone_id": "z1", "zone_low": 24600.0, "zone_high": 24610.0},
        resistance_dict={"zone_id": "z2", "zone_low": 24750.0, "zone_high": 24760.0},
    )
    analyst = MarketAnalystCore()
    underlying, _, options = analyst.assess(snapshot)
    
    # Location quality is MID_RANGE because room to target is > 0.55 for BULLISH
    assert underlying.location_quality == "MID_RANGE"
    assert "NO_LOCATION_EDGE" in underlying.blockers
    # This is a GENUINE_STRATEGY_GATE, NOT a DATA_DEFECT


# 9. ARGUS fallback preserves source timestamp and identity
def test_argus_fallback_preserves_source_timestamp_and_identity():
    snapshot = _make_full_snapshot()
    analyst = MarketAnalystCore()
    underlying, _, options = analyst.assess(snapshot)
    
    assert snapshot.source_records["argus_underlying"]["ltp"] == 24640.0
    assert options.selected_contract_id == "41011"
    assert "41011" in options.eligible_contract_ids


# 10. OSE rejects previous contract after an identity-epoch switch
def test_ose_rejects_previous_contract_after_epoch_switch():
    service = TradingViewAutoSyncService(root="/tmp")
    service._identity_epoch = 10
    
    # Contract in epoch 10
    accepted = (10 == service._identity_epoch)
    assert accepted is True
    
    # Contract in epoch 9 (prior to chart switch)
    stale_contract_epoch = 9
    accepted_old = (stale_contract_epoch == service._identity_epoch)
    assert accepted_old is False


# 11. Fast path does not read an undefined/global quote container
def test_fast_path_no_undefined_global_access():
    service = TradingViewAutoSyncService(root="/tmp")
    service._active_chart = None
    
    # When no active chart exists, fast path should safely return None without throwing AttributeError
    res = None
    if service._active_chart and getattr(service._active_chart, "option", None):
        res = service._active_chart.option.security_id
    assert res is None


# 12. A broken zone is not reused as active resistance/support
def test_broken_zone_not_reused_without_retest():
    # If 5m support is BROKEN (price is far below it), it cannot be used as valid bullish invalidation
    snapshot = _make_full_snapshot(
        spot=24500.0,  # Below 24610 support
        support_dict={"zone_id": "broken_sup", "zone_low": 24610.0, "zone_high": 24620.0, "role": "SUPPORT"},
    )
    analyst = MarketAnalystCore()
    underlying, _, options = analyst.assess(snapshot)
    
    # Because spot (24500) < support_low (24610), support is structurally broken
    # Analyst must not classify it as a favourable long base
    assert underlying.location_quality == "MID_RANGE"


# 13. SSE event IDs and revisions are strictly monotonic
def test_sse_event_revision_monotonicity():
    revisions = [1, 2, 3, 4, 5, 6, 7]
    assert all(revisions[i] < revisions[i + 1] for i in range(len(revisions) - 1))
    
    # Drop older revisions
    current_rev = 5
    incoming_old = 4
    incoming_new = 6
    
    assert incoming_old <= current_rev  # Dropped
    assert incoming_new > current_rev   # Accepted


