"""Comprehensive Unit Tests for CITADEL Eye Phase E7 Personal Strategy Layer."""

import pytest
from src.eye.personal_strategies.contracts import (
    PersonalStrategyId,
    StrategyLifecycleState,
    ValidationStatus,
    DeploymentStatus,
)
from src.eye.personal_strategies.registry import PersonalStrategyRegistry
from src.eye.personal_strategies.indicators import (
    compute_rsi,
    compute_bollinger_bands,
    compute_atr,
    compute_ema,
    compute_supertrend,
    compute_traditional_pivots,
)
from src.eye.personal_strategies.strategies.s01_bb_rsi_momentum import S01Evaluator
from src.eye.personal_strategies.strategies.s05_bb_cpr_breakout import S05Evaluator
from src.eye.personal_strategies.strategies.s06_opening_momentum_recovery import S06Evaluator
from src.eye.personal_strategies.strategies.s02_nifty_volatile import S02Evaluator
from src.eye.personal_strategies.strategies.s03_trend_catcher import S03Evaluator
from src.eye.personal_strategies.strategies.s04_bull_pulse import S04Evaluator
from src.eye.personal_strategies.engine import PersonalStrategyEngine


def test_registry_all_7_strategies_present():
    reg = PersonalStrategyRegistry.get_instance()
    assert len(reg.strategies) == 7

    s07 = reg.get_strategy_metadata(PersonalStrategyId.S07)
    assert s07 is not None
    assert s07.status == "PARKED_NOT_AUTHORIZED"
    assert s07.deployment_status == DeploymentStatus.PARKED_NOT_AUTHORIZED


def test_s07_runtime_evaluator_absent():
    engine = PersonalStrategyEngine.get_instance()
    engine.evaluate_all()
    bus = engine.get_signal_bus_summary()
    assert bus["s07_runtime_evaluator_exists"] is False
    assert bus["total_registered_strategies"] == 7
    assert bus["active_evaluated_strategies"] == 6  # 6 distinct strategy IDs (S01-S06)


def test_indicator_parity_calculations():
    closes = [100.0 + i for i in range(30)]
    rsi = compute_rsi(closes, 14)
    assert len(rsi) == 30
    assert rsi[-1] == 100.0  # strictly increasing

    bb = compute_bollinger_bands(closes, 20, 2.0)
    assert bb[-1]["middle"] is not None
    assert bb[-1]["upper"] > bb[-1]["middle"]

    pivots = compute_traditional_pivots(24750.0, 24450.0, 24600.0)
    assert pivots["P"] == 24600.0
    assert pivots["R1"] == 24750.0
    assert pivots["S1"] == 24450.0


def test_s01_detection_and_risk_block():
    evaluator = S01Evaluator()
    contract = "NIFTY11AUG2624700CE"

    # Synthetic 3m bars: oscillating around 100 for 23 bars, then sharp breakout to 145
    bars_3m = [{"open": 100.0, "high": 101.0, "low": 95.0, "close": 100.0 - (i % 2 * 3.0)} for i in range(23)]
    bars_3m.append({"open": 100.0, "high": 101.0, "low": 97.0, "close": 99.0})
    bars_3m.append({"open": 99.0, "high": 150.0, "low": 98.0, "close": 145.0})

    sig = evaluator.evaluate(contract, bars_3m, "09:30:00", 145.0)
    assert sig.strategy_id == PersonalStrategyId.S01
    assert sig.state in (StrategyLifecycleState.DETECTED, StrategyLifecycleState.BLOCKED)

    if sig.state == StrategyLifecycleState.BLOCKED:
        assert sig.blocker == "STRUCTURAL_RISK_GT_30"





def test_s05_ce_and_pe_independent():
    eval_ce = S05Evaluator(option_type="CE")
    eval_pe = S05Evaluator(option_type="PE")

    bars_3m = [{"open": 180.0, "high": 190.0, "low": 175.0, "close": 185.0}] * 25
    bars_5m = [{"open": 180.0, "high": 190.0, "low": 175.0, "close": 185.0}] * 25

    sig_ce = eval_ce.evaluate("CE_CONTRACT", bars_3m, bars_5m, 24700.0, 24400.0, 24500.0, "09:30:00", 185.0)
    sig_pe = eval_pe.evaluate("PE_CONTRACT", bars_3m, bars_5m, 24700.0, 24400.0, 24500.0, "09:30:00", 185.0)

    assert sig_ce.direction == "BUY_CE"
    assert sig_pe.direction == "BUY_PE"


def test_s06_without_canonical_flow_fails_closed_not_missing_rule():
    evaluator = S06Evaluator()
    bars_1m = [{"open": 180.0, "high": 185.0, "low": 178.0, "close": 182.0}] * 20

    sig = evaluator.evaluate("CE", "PE", bars_1m, bars_1m, 175.0, 175.0, strike_buying_provider_available=False)
    assert sig.state == StrategyLifecycleState.MISSING_DATA
    assert sig.blocker == "S06_CANONICAL_FLOW_UNAVAILABLE"


def test_s02_s03_s04_missing_context_is_not_a_missing_rule():
    s02 = S02Evaluator().evaluate("PE")
    assert s02.state == StrategyLifecycleState.MISSING_DATA
    assert s02.blocker == "S02_FUTURES_CONTEXT_UNAVAILABLE"

    s03 = S03Evaluator().evaluate("PE")
    assert s03.state == StrategyLifecycleState.MISSING_DATA
    assert s03.blocker == "S03_CANONICAL_CONTEXT_UNAVAILABLE"

    s04 = S04Evaluator().evaluate("CE")
    assert s04.state == StrategyLifecycleState.MISSING_DATA
    assert s04.blocker == "S04_CANONICAL_CONTEXT_UNAVAILABLE"


def test_engine_evaluate_all_signal_bus():
    engine = PersonalStrategyEngine.get_instance()
    signals = engine.evaluate_all()
    assert len(signals) == 7

    bus = engine.get_signal_bus_summary()
    assert bus["primary_signal"] is not None
    assert bus["primary_signal"]["strategy_id"] in [s.value for s in PersonalStrategyId]
