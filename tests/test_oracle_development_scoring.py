"""Focused unit tests for Oracle Development scoring weights and event fingerprinting."""

import pytest

from src.oracle_development.scoring_engine import OracleDevScoringEngine
from src.oracle_development.price_action_analyzer import OracleDevPriceActionAnalyzer


def test_locked_authority_weighting():
    """Asserts composite scoring matches the locked 30/25/25/20 weights exactly."""
    engine = OracleDevScoringEngine()
    
    # Run full score calculation with maximum possible sub-scores
    pa_analysis = {"score": 30.0, "factors": {}}
    vob_data = {"proximity_points": 10.0, "volume_ratio_points": 10.0, "displacement_points": 5.0} # 25 max
    deriv_data = {"argus_points": 5.0, "ose_points": 5.0, "ssi_oic_points": 5.0, "chain_change_points": 5.0, "writer_wall_points": 3.0, "futures_points": 2.0} # 25 max
    exec_data = {
        "risk_approved": True,
        "guardian_ready": True,
        "contract_integrity_points": 4.0,
        "quote_freshness_points": 4.0,
        "strike_eligibility_points": 4.0,
        "liquidity_spread_points": 4.0,
        "chase_points": 4.0
    } # 20 max
    
    scores = engine.compute_scores(pa_analysis, vob_data, deriv_data, exec_data)
    
    assert scores["pa_score"] == 30.0
    assert scores["vob_score"] == 25.0
    assert scores["deriv_score"] == 25.0
    assert scores["exec_score"] == 20.0
    assert scores["total_score"] == 100.0


def test_fvg_nested_score_cap():
    """Asserts FVG sub-family scores are nested within Price Action and capped at 8 out of 30."""
    analyzer = OracleDevPriceActionAnalyzer()
    
    # Mock spot candles
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24020.0, "low": 23990.0, "close": 24010.0, "volume": 100},
        # FVG 1 (Breakaway)
        {"time": now_epoch - 240, "open": 24010.0, "high": 24100.0, "low": 24005.0, "close": 24095.0, "volume": 120},
        {"time": now_epoch - 180, "open": 24095.0, "high": 24110.0, "low": 24080.0, "close": 24085.0, "volume": 80},
        # FVG 2 (Continuation)
        {"time": now_epoch - 120, "open": 24085.0, "high": 24200.0, "low": 24075.0, "close": 24195.0, "volume": 150},
        {"time": now_epoch - 60, "open": 24195.0, "high": 24220.0, "low": 24185.0, "close": 24210.0, "volume": 140}
    ]
    
    res = analyzer.analyze(spot_candles, spot_candles, "NIFTY")
    
    # Assert FVG points do not leak to a separate category and are nested inside PA
    assert res["score"] <= 30.0
    fvg_fact = res["factors"].get("fvg_family")
    assert fvg_fact is not None
    assert fvg_fact["score"] <= 8.0 # Capped at 8 points


def test_event_fingerprint_deduplication():
    """Asserts that overlapping setup events generate identical fingerprint hashes to prevent duplicates."""
    engine = OracleDevScoringEngine()
    
    # Identical details must yield identical fingerprint hashes
    fp1 = engine.generate_fingerprint(
        instrument="NIFTY",
        direction="CALL",
        timeframe="3m",
        structural_location="VOB_DEMAND",
        trigger_candle_time=1785148800,
        event_time=1785148810,
        parent_trade_family="VOB Pullback"
    )
    
    fp2 = engine.generate_fingerprint(
        instrument="NIFTY",
        direction="CALL",
        timeframe="3m",
        structural_location="VOB_DEMAND",
        trigger_candle_time=1785148800,
        event_time=1785148810,
        parent_trade_family="VOB Pullback"
    )
    
    assert fp1 == fp2
    
    # Overlapping variation check (different timestamp or family must yield different fingerprint)
    fp3 = engine.generate_fingerprint(
        instrument="NIFTY",
        direction="CALL",
        timeframe="3m",
        structural_location="VOB_DEMAND",
        trigger_candle_time=1785148900, # different trigger
        event_time=1785148810,
        parent_trade_family="VOB Pullback"
    )
    
    assert fp1 != fp3


def test_derivative_dimensional_units():
    """Verify points/min, bps/min and ATR-normalized basis trend derivative math."""
    from src.oracle_development.oracle_dev_service import OracleDevService
    from unittest.mock import MagicMock
    
    service = OracleDevService(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    
    lane = "5m"
    spot_lane = [
        {"high": 24010.0, "low": 24000.0, "close": 24010.0},
        {"high": 24010.0, "low": 24000.0, "close": 24000.0}
    ]
    futures_lane = [
        {"close": 24060.0},
        {"close": 24080.0}
    ]
    options_lane = {}
    
    now_epoch = 1785148800
    service._raw_spot_1m = [
        {"time": now_epoch - i * 60, "open": 24000.0, "high": 24010.0, "low": 24000.0, "close": 24000.0, "volume": 100}
        for i in range(20)
    ]
    
    res = service._assess_derivatives(lane, spot_lane, futures_lane, options_lane)
    
    assert res["derv_points_min_str"] == "6.00 points/min"
    assert res["derv_bpm_str"] == "2.50 bps/min"
    assert res["atr_normalized_derv_str"] == "0.60 pts/min/ATR"
    assert res["raw_basis_delta"] == 30.0
