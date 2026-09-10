"""
Test Suite for Unified Risk, Stop & Exit Operating System Foundation.
"""

from __future__ import annotations
import pytest
from src.risk_engine.contracts import RiskPlan, ExitDecision, ExitAction, SkipReason, TargetStep
from src.risk_engine.stop_engine import LayeredStopEngine
from src.risk_engine.quality_gates import QualityGateEvaluator
from src.risk_engine.exit_policies import ExitPolicyRegistry
from src.risk_engine.simulator import DeterministicExitSimulator
from src.risk_engine.service import UnifiedRiskEngineService


@pytest.fixture(autouse=True)
def reset_risk_service():
    UnifiedRiskEngineService.reset_instance()
    yield
    UnifiedRiskEngineService.reset_instance()


def test_1_layered_stop_engine_long():
    engine = LayeredStopEngine()
    eff_stop, skip_r, details = engine.compute_layered_stop(
        entry_price=24000.0,
        side="LONG",
        structural_price=23950.0,
        atr=20.0,  # vol_buffer = 10.0 -> raw_stop = 23940.0
    )
    assert skip_r == SkipReason.NONE
    assert eff_stop == 23940.0


def test_2_noise_spread_floor_enforcement():
    engine = LayeredStopEngine()
    # Structural stop is too close (distance 2.0 < noise_floor 5.0)
    eff_stop, skip_r, details = engine.compute_layered_stop(
        entry_price=24000.0,
        side="LONG",
        structural_price=23998.0,
        spread=0.0,
        noise_floor=5.0,  # min distance 5.0 (spread gate disabled)
    )
    assert skip_r == SkipReason.NONE
    assert eff_stop == 23995.0  # Enforced noise floor


def test_3_too_deep_stop_skip():
    engine = LayeredStopEngine(default_max_risk_pct=0.01)  # 1% cap = 240.0 pts
    eff_stop, skip_r, details = engine.compute_layered_stop(
        entry_price=24000.0,
        side="LONG",
        structural_price=23700.0,  # Distance 300.0 > 240.0 cap
    )
    # UNVALIDATED 1% risk cap does NOT hard-veto — skip_reason is NONE, WOULD_SKIP telemetry recorded
    assert skip_r == SkipReason.NONE
    assert "WOULD_SKIP_IF_ENFORCED" in details
    assert "STOP_EXCEEDS_RISK_CAP" in details


def test_4_missing_structural_invalidation():
    engine = LayeredStopEngine()
    eff_stop, skip_r, details = engine.compute_layered_stop(
        entry_price=24000.0,
        side="LONG",
        structural_price=None,
    )
    assert skip_r == SkipReason.MISSING_STRUCTURAL_INVALIDATION


def test_5_quality_gates():
    evaluator = QualityGateEvaluator(max_spread_points=10.0, min_reward_risk_ratio=1.5)
    # Wide spread skip
    ok, skip_r, _ = evaluator.evaluate_entry_quality(
        entry_price=24000.0,
        side="LONG",
        effective_stop=23950.0,
        first_target=24100.0,
        spread=12.0,
    )
    assert ok is False
    assert skip_r == SkipReason.SPREAD_TOO_WIDE

    # Low R/R ratio skip
    ok, skip_r, _ = evaluator.evaluate_entry_quality(
        entry_price=24000.0,
        side="LONG",
        effective_stop=23900.0,  # Risk 100
        first_target=24100.0,    # Reward 100 -> R/R 1.0 < 1.5
        spread=2.0,
    )
    assert ok is False
    assert skip_r == SkipReason.REWARD_RISK_BELOW_THRESHOLD


def test_6_deterministic_exit_simulator():
    sim = DeterministicExitSimulator()
    plan = RiskPlan(
        plan_id="p1",
        strategy_id="TEST",
        deployment_id="TEST_DEPLOY",
        instrument="NIFTY",
        option_context=None,
        option_symbol=None,
        side="LONG",
        entry_price=24000.0,
        structural_invalidation=23950.0,
        noise_spread_floor=5.0,
        volatility_buffer=0.0,
        effective_stop=23950.0,
        maximum_risk_cap=500.0,
        position_size=1,
        target_ladder=[TargetStep(target_price=24100.0, exit_ratio=1.0)],
        trailing_policy="NONE",
        time_decay_policy="NONE",
        lifecycle_exit_policy="STRUCTURAL",
    )

    candles = [
        {"open": 24000.0, "high": 24020.0, "low": 23990.0, "close": 24010.0},
        {"open": 24010.0, "high": 24110.0, "low": 24005.0, "close": 24105.0},  # Target reached
    ]

    res = sim.simulate_trade_exit(plan, candles)
    assert res["status"] == "COMPLETED"
    assert res["final_outcome"] == "TARGET_FIRST"
    assert res["realized_r"] == 2.0


def test_7_same_bar_ambiguity_conservative():
    sim = DeterministicExitSimulator()
    plan = RiskPlan(
        plan_id="p2",
        strategy_id="TEST",
        deployment_id="TEST_DEPLOY",
        instrument="NIFTY",
        option_context=None,
        option_symbol=None,
        side="LONG",
        entry_price=24000.0,
        structural_invalidation=23950.0,
        noise_spread_floor=5.0,
        volatility_buffer=0.0,
        effective_stop=23950.0,
        maximum_risk_cap=500.0,
        position_size=1,
        target_ladder=[TargetStep(target_price=24100.0, exit_ratio=1.0)],
        trailing_policy="NONE",
        time_decay_policy="NONE",
        lifecycle_exit_policy="STRUCTURAL",
    )

    # Bar touches BOTH target (24100) and stop (23950)
    candles = [
        {"open": 24000.0, "high": 24120.0, "low": 23940.0, "close": 24000.0},
    ]

    res = sim.simulate_trade_exit(plan, candles)
    assert res["final_outcome"] == "STOP_FIRST"  # Conservative ambiguity resolution!


def test_8_shadow_service():
    service = UnifiedRiskEngineService.get_instance()
    plan = service.evaluate_shadow_risk_plan(
        strategy_id="BULL_PULSE",
        instrument="NIFTY",
        side="LONG",
        entry_price=24000.0,
        structural_invalidation=23950.0,
        atr=20.0,
        first_target=24100.0,
    )
    assert plan.is_skipped is False
    assert plan.effective_stop == 23940.0
    status = service.get_shadow_status()
    assert status["execution_influence"] == "ZERO"
    assert status["active_plans_count"] == 1
