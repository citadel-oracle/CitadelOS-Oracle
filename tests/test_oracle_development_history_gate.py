"""Tests for genuine warmup helpers and the fail-closed history gate."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.oracle_development.oracle_dev_service import (
    OracleDevService,
    _HISTORY_GATE,
    evaluate_oracle_dev_gate
)


def _make_service(tmp_path):
    dhan = MagicMock()
    dhan.__class__.__name__ = "MockDhan"
    dhan.get_quote.return_value = {"ltp": 24000.0}
    dhan.get_intraday_candles.return_value = {"candles": []}
    argus = MagicMock()
    argus.get_flow_bias.return_value = {"bias": "neutral", "strength": 0.0}
    ose = MagicMock()
    ose.get_order_pressure.return_value = {}
    vob = MagicMock()
    vob._zones = {}
    svc = OracleDevService(dhan, argus, ose, vob, state_root=str(tmp_path))
    return svc


def _candle(ts: int, price: float = 24000.0) -> dict:
    return {"time": ts, "open": price, "high": price + 10, "low": price - 10, "close": price, "volume": 1000}


# ---------------------------------------------------------------------------
# Warmup helper tests
# ---------------------------------------------------------------------------

def test_merge_deduplicates_by_timestamp(tmp_path):
    svc = _make_service(tmp_path)
    base = [_candle(1000, 100.0), _candle(2000, 200.0)]
    incoming = [_candle(2000, 210.0), _candle(3000, 300.0)]
    merged = svc._merge_candles(base, incoming)
    assert len(merged) == 3
    assert merged[1]["close"] == 210.0  # incoming wins


def test_merge_sorted_ascending(tmp_path):
    svc = _make_service(tmp_path)
    merged = svc._merge_candles([_candle(3000), _candle(1000)], [_candle(2000)])
    times = [c["time"] for c in merged]
    assert times == sorted(times)


def test_today_first_candle_appends_without_deleting_history(tmp_path):
    svc = _make_service(tmp_path)
    warm = [_candle(1000 + i * 60) for i in range(10)]
    today = [_candle(warm[-1]["time"] + 60)]
    merged = svc._merge_candles(warm, today)
    assert len(merged) == 11
    assert merged[-1]["time"] == today[0]["time"]
    assert merged[0]["time"] == warm[0]["time"]  # history preserved


def test_different_contract_stores_stay_isolated(tmp_path):
    svc = _make_service(tmp_path)
    store_a = tmp_path / "candle_store_fut_1m_61093.json"
    store_b = tmp_path / "candle_store_fut_1m_99999.json"
    svc._save_candle_store(store_a, [_candle(1000, 24000.0)])
    svc._save_candle_store(store_b, [_candle(2000, 25000.0)])
    a = svc._load_candle_store(store_a)
    b = svc._load_candle_store(store_b)
    assert a[0]["close"] == 24000.0
    assert b[0]["close"] == 25000.0


def test_candle_store_roundtrip(tmp_path):
    svc = _make_service(tmp_path)
    path = tmp_path / "test_store.json"
    candles = [_candle(t) for t in range(1000, 1600, 60)]
    svc._save_candle_store(path, candles)
    loaded = svc._load_candle_store(path)
    assert len(loaded) == len(candles)
    assert loaded[0]["time"] == 1000


def test_load_missing_store_returns_empty(tmp_path):
    svc = _make_service(tmp_path)
    assert svc._load_candle_store(tmp_path / "nonexistent.json") == []


def test_trading_days_back_skips_weekends(tmp_path):
    svc = _make_service(tmp_path)
    # 2026-07-28 is a Tuesday; going back 3 business days → Mon 27, Fri 24, Thu 23
    from datetime import timezone as tz
    now_ist = datetime(2026, 7, 28, 10, 0, 0, tzinfo=timezone.utc)
    days = svc._trading_days_back(now_ist, 3)
    assert len(days) == 3
    for d in days:
        dt = datetime.strptime(d, "%Y-%m-%d")
        assert dt.weekday() < 5


# ---------------------------------------------------------------------------
# History gate tests
# ---------------------------------------------------------------------------

def test_history_gate_constants():
    assert _HISTORY_GATE == {"1m": 80, "3m": 60, "5m": 50}


def test_gate_bypassed_in_test_env(tmp_path):
    """In test run (with is_replay=False, is_synthetic=False), we verify full gate behavior."""
    # When all parameters are compliant, gate is allowed
    res = evaluate_oracle_dev_gate(
        lane="1m",
        canonical_candle_count=80,
        current_session_completed_count=1,
        current_session_data_age_seconds=10.0,
        is_replay=False,
        is_synthetic=False
    )
    assert res["allowed"] is True
    assert res["blocker"] is None


def test_approved_lots_zero_when_guardian_and_risk_false(tmp_path):
    """When scores have guardian_ready=False/risk_approved=False, planner yields approved_lots=0."""
    from src.oracle_development.scoring_engine import OracleDevScoringEngine
    from src.oracle_development.trade_planner_dev import OracleDevTradePlanner

    engine = OracleDevScoringEngine()
    planner = OracleDevTradePlanner()

    exec_data = {
        "risk_approved": False, "guardian_ready": False,
        "contract_integrity_points": 0.0, "quote_freshness_points": 0.0,
        "strike_eligibility_points": 0.0, "liquidity_spread_points": 0.0,
        "chase_points": 0.0,
    }
    scores = engine.compute_scores({"score": 25.0, "factors": {}}, {}, {}, exec_data)
    assert scores["guardian_ready"] is False
    assert scores["risk_approved"] is False

    plan = planner.plan_trade(
        "PA Breakout", "CALL", 24000.0, 23950.0,
        scores, pa_aligned=True, vob_aligned=True, deriv_aligned=True
    )
    assert plan["approved_lots"] == 0


def test_no_mission_opened_with_few_candles(tmp_path):
    """process_candle_update must not open any OPEN mission when candles are few."""
    svc = _make_service(tmp_path)
    svc.is_replay = False
    svc.is_synthetic = False
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    # 5 candles is way below the 1m lane gate requirement of 80 canonical candles
    spot_1m = [_candle(now_epoch - (5 - i) * 60, 24000.0) for i in range(5)]
    fut_1m = [_candle(now_epoch - (5 - i) * 60, 24020.0) for i in range(5)]
    svc.process_candle_update(spot_1m, fut_1m, {})
    assert svc.missions.active() is None


def test_exec_res_contains_blocker_field(tmp_path):
    """exec_res always contains blocker, candle_count and required_candle_count keys."""
    svc = _make_service(tmp_path)
    svc.is_replay = False
    svc.is_synthetic = False
    now_dt = datetime.now(timezone.utc)
    last_spot = _candle(int(now_dt.timestamp()) - 5)
    res = svc._assess_execution(
        last_spot, {}, {}, now_dt,
        lane="3m",
        canonical_candle_count=10,
        current_session_completed_count=1,
        current_session_data_age_seconds=10.0
    )
    assert "blocker" in res
    assert "candle_count" in res
    assert "required_candle_count" in res
    assert res["required_candle_count"] == 60  # 3m gate
    assert res["blocker"] == "INSUFFICIENT_HISTORY"


# ---------------------------------------------------------------------------
# Pure Gate Matrix Tests
# ---------------------------------------------------------------------------

def test_pure_gate_1m_limits():
    # 1m 79 blocked
    r_79 = evaluate_oracle_dev_gate("1m", 79, 1, 10.0, False, False)
    assert r_79["allowed"] is False
    assert r_79["blocker"] == "INSUFFICIENT_HISTORY"

    # 1m 80 fresh allowed
    r_80 = evaluate_oracle_dev_gate("1m", 80, 1, 10.0, False, False)
    assert r_80["allowed"] is True
    assert r_80["blocker"] is None


def test_pure_gate_3m_limits():
    # 3m 59 blocked
    r_59 = evaluate_oracle_dev_gate("3m", 59, 1, 10.0, False, False)
    assert r_59["allowed"] is False
    assert r_59["blocker"] == "INSUFFICIENT_HISTORY"

    # 3m 60 fresh allowed
    r_60 = evaluate_oracle_dev_gate("3m", 60, 1, 10.0, False, False)
    assert r_60["allowed"] is True
    assert r_60["blocker"] is None


def test_pure_gate_5m_limits():
    # 5m 49 blocked
    r_49 = evaluate_oracle_dev_gate("5m", 49, 1, 10.0, False, False)
    assert r_49["allowed"] is False
    assert r_49["blocker"] == "INSUFFICIENT_HISTORY"

    # 5m 50 fresh allowed
    r_50 = evaluate_oracle_dev_gate("5m", 50, 1, 10.0, False, False)
    assert r_50["allowed"] is True
    assert r_50["blocker"] is None


def test_pure_gate_zero_session_completed_candles():
    r = evaluate_oracle_dev_gate("1m", 100, 0, 10.0, False, False)
    assert r["allowed"] is False
    assert r["blocker"] == "NO_COMPLETED_CURRENT_SESSION_CANDLE"


def test_pure_gate_age_stale():
    r = evaluate_oracle_dev_gate("1m", 100, 2, 31.0, False, False)
    assert r["allowed"] is False
    assert r["blocker"] == "STALE_DATA"


def test_pure_gate_replay_blocked():
    r = evaluate_oracle_dev_gate("1m", 100, 2, 10.0, True, False)
    assert r["allowed"] is False
    assert r["blocker"] == "REPLAY_BLOCKED"


def test_pure_gate_synthetic_blocked():
    r = evaluate_oracle_dev_gate("1m", 100, 2, 10.0, False, True)
    assert r["allowed"] is False
    assert r["blocker"] == "SYNTHETIC_BLOCKED"
