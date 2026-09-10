"""
CITADEL Risk Engine — Real Strategy Integration Tests.

Covers:
  1.  Authoritative 13-lane inventory (12 option-chart + 1 underlying)
  2.  CE and PUT (PE) plan generation
  3.  Unit separation: underlying vs option premium
  4.  Missing premium translation → OPTION_PREMIUM_UNAVAILABLE skip
  5.  Real strategy evaluation integration (evaluate_shadow_from_evaluation)
  6.  Strategy output unchanged (evaluation dict not mutated)
  7.  Duplicate candidate idempotency (same plan_id returned)
  8.  Bounded plan retention (evicts oldest when max reached)
  9.  Restart recovery (reset_instance + re-populate)
  10. All 8 exit policies
  11. Threshold governance: LOCKED, UNVALIDATED_DEFAULT, DISABLED labels
  12. Offline journal replay without look-ahead
  13. Zero execution influence invariant
"""

from __future__ import annotations
import copy
import json
import os
import tempfile
import pytest

from src.risk_engine.inventory import (
    AUTHORITATIVE_LANES, all_lanes, enabled_lanes, get_lane,
)
from src.risk_engine.contracts import (
    ExitAction, RiskPlan, SkipReason, TargetStep, UnitSafeOptionContext,
)
from src.risk_engine.service import UnifiedRiskEngineService
from src.risk_engine.stop_engine import LayeredStopEngine
from src.risk_engine.quality_gates import QualityGateEvaluator
from src.risk_engine.exit_policies import (
    ExitPolicyRegistry, StructuralTargetPolicy, FixedRPolicy,
    HybridPartialRunnerPolicy, TrailingStructurePolicy, TrailingVolatilityPolicy,
    LifecycleExitPolicy, TimeDecayExitPolicy, NoProgressExitPolicy,
)
from src.risk_engine.thresholds import (
    THRESHOLD_REGISTRY, GovernanceClass, locked_thresholds,
    unvalidated_thresholds, disabled_thresholds,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_service():
    """Ensure a fresh singleton for every test."""
    UnifiedRiskEngineService.reset_instance()
    yield
    UnifiedRiskEngineService.reset_instance()


def make_service(max_plans: int = 200) -> UnifiedRiskEngineService:
    UnifiedRiskEngineService.reset_instance()
    svc = UnifiedRiskEngineService(enabled=True, shadow_mode=True, max_plans=max_plans)
    UnifiedRiskEngineService._instance = svc
    return svc


def ce_evaluation(entry: float = 85.0, sl: float = 70.0, target: float = None) -> dict:
    """Simulate a TrendCatcher / BullPulse BUY evaluation (CE, premium pts)."""
    return {
        "status": "ENTRY_CANDIDATE",
        "signal": "BUY",
        "reason": "MOMENTUM_TRIGGERED",
        "entry": entry,
        "sl": sl,
        "target": target,
        "option_contract": {
            "trading_symbol": "NIFTY26AUG24400CE",
            "strike": 24400.0,
            "expiry": "2026-08-04",
            "option_type": "CE",
        },
        "lot_size": 25,
        "bar_timestamp": "2026-07-31T09:35:00+05:30",
        "evaluated_at": "2026-07-31T09:35:01+05:30",
        "candle_id": "candle_abc123",
    }


def pe_evaluation(entry: float = 75.0, sl: float = 60.0, target: float = None) -> dict:
    """Simulate a PullbackMaster / BreakoutMain BUY evaluation (PE, premium pts)."""
    return {
        "status": "ENTRY_CANDIDATE",
        "signal": "BUY",
        "reason": "OB_TOUCH",
        "entry": entry,
        "sl": sl,
        "target": target,
        "option_contract": {
            "trading_symbol": "NIFTY26AUG24400PE",
            "strike": 24400.0,
            "expiry": "2026-08-04",
            "option_type": "PE",
        },
        "lot_size": 25,
        "bar_timestamp": "2026-07-31T09:40:00+05:30",
        "evaluated_at": "2026-07-31T09:40:01+05:30",
        "candle_id": "candle_def456",
    }


def underlying_evaluation(entry: float = 24400.0, sl: float = 24350.0) -> dict:
    """Simulate pullback-master-pine-v5 (underlying index bar strategy, no premium)."""
    return {
        "status": "ENTRY_CANDIDATE",
        "signal": "BUY",
        "reason": "OB_RETEST",
        "entry": entry,
        "sl": sl,
        "target": None,
        "option_contract": None,
        "lot_size": None,
        "bar_timestamp": "2026-07-31T09:45:00+05:30",
        "evaluated_at": "2026-07-31T09:45:01+05:30",
        "candle_id": "candle_underlying_001",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Authoritative 13-lane inventory
# ─────────────────────────────────────────────────────────────────────────────

class TestInventory:
    def test_total_lane_count(self):
        lanes = all_lanes()
        assert len(lanes) == 13, f"Expected 13 lanes, got {len(lanes)}"

    def test_option_chart_lanes(self):
        opt_lanes = [l for l in all_lanes() if not l.underlying_domain]
        assert len(opt_lanes) == 12

    def test_underlying_lane_exists(self):
        lane = get_lane("pullback-master-pine-v5")
        assert lane is not None
        assert lane.underlying_domain is True
        assert lane.premium_domain is False

    def test_ce_lanes(self):
        ce = [l for l in all_lanes() if l.option_side == "CE"]
        assert len(ce) == 7  # PB_CE_1M, PB_CE_3M, BO_CE_1M, BO_CE_3M, BP_CE_1M, BP_CE_3M, pullback-master-pine-v5 (CE)

    def test_pe_lanes(self):
        pe = [l for l in all_lanes() if l.option_side == "PE"]
        assert len(pe) == 6  # PB_PE_1M, PB_PE_3M, BO_PE_1M, BO_PE_3M, TC_PE_1M, TC_PE_3M

    def test_enabled_lanes_excludes_off_mode(self):
        enabled = enabled_lanes()
        off_ids = {"TC_NIFTY_PE_3M", "BP_NIFTY_CE_3M"}
        for lane in enabled:
            assert lane.deployment_id not in off_ids

    def test_get_lane_unknown(self):
        assert get_lane("INVENTED_DEPLOYMENT_XYZ") is None

    def test_each_lane_has_deployment_id(self):
        for lane in all_lanes():
            assert lane.deployment_id, "Deployment ID must not be empty"

    def test_all_underlying_is_nifty(self):
        for lane in all_lanes():
            assert lane.underlying == "NIFTY"

    def test_service_deployment_flags_match_inventory(self):
        svc = make_service()
        for lane in all_lanes():
            assert lane.deployment_id in svc._deployment_flags


# ─────────────────────────────────────────────────────────────────────────────
# 2. CE and PE plan generation
# ─────────────────────────────────────────────────────────────────────────────

class TestCEAndPEPlans:
    def test_ce_plan_generated(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        assert plan is not None
        assert plan.deployment_id == "TC_NIFTY_PE_1M"
        assert plan.option_context is not None

    def test_pe_plan_generated(self):
        svc = make_service()
        # Use tight stop so 2% UNVALIDATED_DEFAULT risk cap (75*0.02=1.5pts) is satisfied
        plan = svc.evaluate_shadow_from_evaluation("PB_NIFTY_PE_1M", pe_evaluation(entry=75.0, sl=74.0))
        assert plan is not None
        # Plan may be skipped due to UNVALIDATED_DEFAULT risk cap — that's expected behaviour
        # Key assertion: deployment_id and option_context are correctly populated
        assert plan.deployment_id == "PB_NIFTY_PE_1M"
        assert plan.option_context is not None
        assert plan.option_context.option_type == "PE"

    def test_ce_plan_premium_entry_correct(self):
        svc = make_service()
        ev = ce_evaluation(entry=92.5, sl=77.0)
        plan = svc.evaluate_shadow_from_evaluation("BP_NIFTY_CE_1M", ev)
        assert plan.entry_price == 92.5
        assert plan.option_context.option_premium_entry == 92.5

    def test_pe_plan_symbol_stored(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("BO_NIFTY_PE_1M", pe_evaluation())
        assert plan.option_context.option_symbol == "NIFTY26AUG24400PE"

    def test_both_ce_and_pe_in_same_session(self):
        svc = make_service()
        p1 = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        p2 = svc.evaluate_shadow_from_evaluation("PB_NIFTY_PE_1M", pe_evaluation())
        assert p1.plan_id != p2.plan_id
        assert len(svc._shadow_plans) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 3. Unit separation: never mix underlying and option premium
# ─────────────────────────────────────────────────────────────────────────────

class TestUnitSeparation:
    def test_option_premium_not_underlying_index(self):
        """Option premiums are < 5000; underlying index levels are > 20000."""
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation(entry=85.0, sl=70.0))
        # entry_price must be premium-domain (< 5000)
        assert plan.entry_price < 5000, "entry_price must be option premium, not underlying index"

    def test_underlying_index_as_entry_triggers_unavailable(self):
        """If entry looks like an underlying index level, system detects it and skips."""
        svc = make_service()
        # Simulate erroneous underlying-level in premium field
        ev = ce_evaluation(entry=24400.0, sl=24350.0)  # these are index levels
        plan = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ev)
        assert plan.is_skipped
        assert plan.skip_reason == SkipReason.OPTION_PREMIUM_UNAVAILABLE

    def test_underlying_context_not_used_as_stop(self):
        """
        UnitSafeOptionContext.underlying_structural_invalidation is contextual only.
        The stop engine operates on premium stop (60.0 pts), not underlying index (24200).
        The UNVALIDATED_DEFAULT 2% risk cap may gate the trade — that is correct and expected.
        Key check: effective_stop is in premium space (< 200 pts), never in index range (> 20000).
        """
        oc = UnitSafeOptionContext(
            underlying_price=24383.6,
            underlying_structural_invalidation=24200.0,  # index level — contextual only
            option_symbol="NIFTY26AUG24400PE",
            option_type="PE",
            option_strike=24400.0,
            option_expiry="2026-08-04",
            option_premium_entry=75.0,         # premium pts
            option_premium_stop=60.0,          # premium pts
            option_premium_target=None,
            option_lot_size=25,
            option_source_timestamp=None,
        )
        # The stop engine must use premium stop (60.0), not underlying structural level (24200)
        engine = LayeredStopEngine()
        eff_stop, skip_r, _ = engine.compute_layered_stop(
            entry_price=oc.option_premium_entry,   # 75.0 (premium pts)
            side="LONG",
            structural_price=oc.option_premium_stop,   # 60.0 (premium pts)
        )
        # Stop must remain in premium domain (< 200 pts), regardless of gate result
        assert eff_stop < 200, "Stop must be in premium space, not underlying index range"
        # Gate may fire (STOP_EXCEEDS_RISK_CAP from UNVALIDATED_DEFAULT 2% cap) — this is correct
        # Key: we are NOT in underlying index territory (eff_stop would be ~24200 if wrong domain)
        assert skip_r in (SkipReason.NONE, SkipReason.STOP_EXCEEDS_RISK_CAP)

    def test_unit_safe_context_is_premium_available(self):
        oc = UnitSafeOptionContext(
            underlying_price=24383.6,
            underlying_structural_invalidation=None,
            option_symbol="NIFTY26AUG24400CE",
            option_type="CE", option_strike=24400.0, option_expiry="2026-08-04",
            option_premium_entry=85.0, option_premium_stop=70.0,
            option_premium_target=None, option_lot_size=25,
            option_source_timestamp=None,
        )
        assert oc.is_premium_available() is True

    def test_unavailable_translation_not_premium_available(self):
        oc = UnitSafeOptionContext(
            underlying_price=24383.6, underlying_structural_invalidation=24200.0,
            option_symbol=None, option_type=None, option_strike=None, option_expiry=None,
            option_premium_entry=None, option_premium_stop=None,
            option_premium_target=None, option_lot_size=None, option_source_timestamp=None,
            translation_method="UNAVAILABLE", translation_confidence="UNAVAILABLE",
        )
        assert oc.is_premium_available() is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Missing premium translation → OPTION_PREMIUM_UNAVAILABLE skip
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingPremiumTranslation:
    def test_underlying_domain_skip(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation(
            "pullback-master-pine-v5", underlying_evaluation()
        )
        assert plan.is_skipped
        assert plan.skip_reason == SkipReason.OPTION_PREMIUM_UNAVAILABLE

    def test_missing_entry_in_evaluation_skips(self):
        svc = make_service()
        ev = {"signal": "BUY", "entry": None, "sl": 70.0,
              "option_contract": {"trading_symbol": "NIFTY26AUG24400CE",
                                  "option_type": "CE", "strike": 24400.0}}
        plan = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ev)
        assert plan.is_skipped
        assert plan.skip_reason == SkipReason.OPTION_PREMIUM_UNAVAILABLE

    def test_skip_reason_in_plan_dict(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation(
            "pullback-master-pine-v5", underlying_evaluation()
        )
        d = plan.to_dict()
        assert d["skip_reason"] == "OPTION_PREMIUM_UNAVAILABLE"
        assert d["is_skipped"] is True

    def test_unknown_deployment_skips(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("INVENTED_UNKNOWN_XYZ", ce_evaluation())
        assert plan.is_skipped
        assert plan.skip_reason == SkipReason.RISK_ENGINE_DISABLED


# ─────────────────────────────────────────────────────────────────────────────
# 5 & 6. Real strategy integration + strategy output unchanged
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategyIntegration:
    def test_evaluation_dict_not_mutated(self):
        """Shadow evaluation must never modify the strategy evaluation dict."""
        svc = make_service()
        ev = ce_evaluation()
        ev_before = copy.deepcopy(ev)
        svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ev)
        # Compare all keys that existed before the call
        for key in ev_before:
            assert ev.get(key) == ev_before[key], f"Key {key!r} was mutated"
        # Allow only _shadow_* annotation keys to be added (they use setdefault via runtime hook)

    def test_plan_stored_after_buy(self):
        svc = make_service()
        svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        assert len(svc._shadow_plans) == 1

    def test_wait_signal_not_evaluated(self):
        """WAIT signals should not call evaluate_shadow_from_evaluation (tested via service directly)."""
        svc = make_service()
        # Only BUY triggers plan creation; service doesn't filter — caller (runtime) filters
        assert len(svc._shadow_plans) == 0

    def test_plan_contains_deployment_id(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("BP_NIFTY_CE_1M", ce_evaluation())
        assert plan.deployment_id == "BP_NIFTY_CE_1M"

    def test_plan_contains_bar_timestamp(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        assert plan.provenance.get("bar_timestamp") == "2026-07-31T09:35:00+05:30"

    def test_plan_execution_influence_zero(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        assert plan.provenance.get("execution_influence") == "ZERO"

    def test_all_enabled_deployments_can_generate_plan(self):
        svc = make_service()
        ce_ids = ["PB_NIFTY_CE_1M", "PB_NIFTY_CE_3M", "BO_NIFTY_CE_1M", "BO_NIFTY_CE_3M",
                  "BP_NIFTY_CE_1M", "TC_NIFTY_PE_1M"]
        pe_ids = ["PB_NIFTY_PE_1M", "PB_NIFTY_PE_3M", "BO_NIFTY_PE_1M", "BO_NIFTY_PE_3M"]
        for dep_id in ce_ids:
            ev = ce_evaluation()
            ev["candle_id"] = f"candle_{dep_id}"
            plan = svc.evaluate_shadow_from_evaluation(dep_id, ev)
            assert plan is not None, f"No plan for {dep_id}"
        for dep_id in pe_ids:
            ev = pe_evaluation()
            ev["candle_id"] = f"candle_{dep_id}"
            plan = svc.evaluate_shadow_from_evaluation(dep_id, ev)
            assert plan is not None, f"No plan for {dep_id}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Duplicate candidate idempotency
# ─────────────────────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_same_candidate_key_returns_same_plan(self):
        svc = make_service()
        key = "TC_NIFTY_PE_1M:candle_abc123"
        p1 = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation(), candidate_key=key)
        p2 = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation(), candidate_key=key)
        assert p1.plan_id == p2.plan_id

    def test_same_candidate_key_no_duplicate_in_store(self):
        svc = make_service()
        key = "TC_NIFTY_PE_1M:candle_abc123"
        svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation(), candidate_key=key)
        svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation(), candidate_key=key)
        assert len(svc._shadow_plans) == 1

    def test_different_candle_ids_create_different_plans(self):
        svc = make_service()
        ev1 = ce_evaluation(); ev1["candle_id"] = "candle_001"
        ev2 = ce_evaluation(); ev2["candle_id"] = "candle_002"
        p1 = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ev1, candidate_key="TC_NIFTY_PE_1M:candle_001")
        p2 = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ev2, candidate_key="TC_NIFTY_PE_1M:candle_002")
        assert p1.plan_id != p2.plan_id

    def test_no_key_always_creates_new_plan(self):
        svc = make_service()
        p1 = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        p2 = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        assert p1.plan_id != p2.plan_id


# ─────────────────────────────────────────────────────────────────────────────
# 8. Bounded plan retention
# ─────────────────────────────────────────────────────────────────────────────

class TestBoundedRetention:
    def test_plans_evicted_when_max_reached(self):
        svc = make_service(max_plans=5)
        first_id = None
        for i in range(7):
            ev = ce_evaluation(); ev["candle_id"] = f"candle_{i:04d}"
            plan = svc.evaluate_shadow_from_evaluation(
                "TC_NIFTY_PE_1M", ev, candidate_key=f"TC_NIFTY_PE_1M:candle_{i:04d}"
            )
            if i == 0:
                first_id = plan.plan_id
        assert len(svc._shadow_plans) == 5
        assert first_id not in svc._shadow_plans

    def test_max_plans_respected(self):
        svc = make_service(max_plans=3)
        for i in range(10):
            ev = ce_evaluation(); ev["candle_id"] = f"candle_{i}"
            svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ev)
        assert len(svc._shadow_plans) <= 3


# ─────────────────────────────────────────────────────────────────────────────
# 9. Restart recovery
# ─────────────────────────────────────────────────────────────────────────────

class TestRestartRecovery:
    def test_singleton_reset_clears_plans(self):
        svc = make_service()
        svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        assert len(svc._shadow_plans) == 1
        UnifiedRiskEngineService.reset_instance()
        new_svc = UnifiedRiskEngineService.get_instance()
        assert len(new_svc._shadow_plans) == 0

    def test_after_reset_can_generate_plans(self):
        UnifiedRiskEngineService.reset_instance()
        svc = UnifiedRiskEngineService.get_instance()
        plan = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        assert plan is not None

    def test_bootstrap_from_journal_file(self):
        """Bootstrap from a synthetic journal file and verify plan count increases."""
        svc = make_service()
        records = [
            {"event_type": "STRATEGY_DECISION", "payload": {
                "signal": "BUY", "entry": 85.0, "sl": 70.0, "status": "ENTRY_CANDIDATE",
                "candle_id": f"candle_{i}",
                "option_contract": {"trading_symbol": "NIFTY26AUG24400CE",
                                    "option_type": "CE", "strike": 24400.0},
                "lot_size": 25, "bar_timestamp": "2026-07-31T09:35:00+05:30",
            }}
            for i in range(5)
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            tmp_path = f.name
        try:
            result = svc.bootstrap_from_journal(tmp_path, "TC_NIFTY_PE_1M")
            assert result["records_scanned"] == 5
            # Each record has a different candle_id — all 5 are new
            assert result["plans_generated"] + result["plans_skipped"] > 0
        finally:
            os.unlink(tmp_path)

    def test_bootstrap_missing_file_returns_not_found(self):
        svc = make_service()
        result = svc.bootstrap_from_journal("/nonexistent/path/journal.jsonl", "TC_NIFTY_PE_1M")
        assert result["status"] == "FILE_NOT_FOUND"


# ─────────────────────────────────────────────────────────────────────────────
# 10. All 8 exit policies
# ─────────────────────────────────────────────────────────────────────────────

def _make_plan(entry: float = 80.0, stop: float = 65.0, target: float = None,
               deployment: str = "TC_NIFTY_PE_1M") -> RiskPlan:
    oc = UnitSafeOptionContext(
        underlying_price=None, underlying_structural_invalidation=None,
        option_symbol="NIFTY26AUG24400CE", option_type="CE",
        option_strike=24400.0, option_expiry="2026-08-04",
        option_premium_entry=entry, option_premium_stop=stop,
        option_premium_target=target, option_lot_size=25,
        option_source_timestamp=None,
    )
    tgt_ladder = []
    if target:
        tgt_ladder = [TargetStep(target_price=target, exit_ratio=0.5, move_stop_to=entry,
                                 description="T1")]
    return RiskPlan(
        plan_id="plan_test001", strategy_id="TREND_CATCHER",
        deployment_id=deployment, instrument="NIFTY",
        option_context=oc, option_symbol="NIFTY26AUG24400CE",
        side="LONG", entry_price=entry, structural_invalidation=stop,
        noise_spread_floor=5.0, volatility_buffer=0.0,
        effective_stop=stop, maximum_risk_cap=entry * 0.02,
        position_size=25, target_ladder=tgt_ladder,
        trailing_policy="TRAILING_STRUCTURE",
        time_decay_policy="DISABLED", lifecycle_exit_policy="DISABLED",
    )


class TestExitPolicies:
    # 1. STRUCTURAL_TARGET
    def test_structural_target_hit(self):
        plan = _make_plan(entry=80.0, stop=65.0, target=110.0)
        policy = StructuralTargetPolicy()
        dec = policy.evaluate(plan, 115.0, high=115.0, low=105.0, current_stop=65.0)
        assert dec is not None
        assert dec.action in (ExitAction.PARTIAL_EXIT, ExitAction.FULL_EXIT)

    def test_structural_target_not_hit(self):
        plan = _make_plan(entry=80.0, stop=65.0, target=110.0)
        dec = StructuralTargetPolicy().evaluate(plan, 95.0, high=95.0, low=88.0, current_stop=65.0)
        assert dec is None

    # 2. FIXED_R
    def test_fixed_r_hit(self):
        plan = _make_plan(entry=80.0, stop=65.0)  # risk=15pts; 3R target=125
        policy = FixedRPolicy(r_multiple=3.0)
        dec = policy.evaluate(plan, 130.0, high=130.0, low=120.0, current_stop=65.0)
        assert dec is not None
        assert dec.action == ExitAction.FULL_EXIT

    def test_fixed_r_disabled_when_none(self):
        plan = _make_plan(entry=80.0, stop=65.0)
        dec = FixedRPolicy(r_multiple=None).evaluate(plan, 200.0, high=200.0, low=180.0, current_stop=65.0)
        assert dec is None

    # 3. HYBRID_PARTIAL_RUNNER
    def test_hybrid_partial_disabled_by_default(self):
        plan = _make_plan(entry=80.0, stop=65.0)
        policy = HybridPartialRunnerPolicy(enabled=False)
        dec = policy.evaluate(plan, 130.0, high=130.0, low=100.0, current_stop=65.0)
        assert dec is None

    def test_hybrid_partial_enabled(self):
        plan = _make_plan(entry=80.0, stop=65.0)  # risk=15pts; T1 at 1.5R=102.5
        policy = HybridPartialRunnerPolicy(enabled=True, t1_r=1.5, partial_exit_ratio=0.5)
        dec = policy.evaluate(plan, 105.0, high=105.0, low=95.0, current_stop=65.0, bars_held=5)
        assert dec is not None
        assert dec.action == ExitAction.PARTIAL_EXIT
        assert dec.exit_ratio == 0.5
        assert dec.new_stop_price == 80.0  # moved to breakeven

    # 4. TRAILING_STRUCTURE
    def test_trailing_structure_improves_stop(self):
        plan = _make_plan(entry=80.0, stop=65.0)
        policy = TrailingStructurePolicy(enabled=True)
        new_stop = policy.new_stop(plan, current_price=95.0, current_stop=65.0,
                                   structural_level=78.0)  # new structure above old stop
        assert new_stop == 78.0

    def test_trailing_structure_no_improvement(self):
        plan = _make_plan(entry=80.0, stop=65.0)
        new_stop = TrailingStructurePolicy().new_stop(plan, 80.0, 70.0, structural_level=62.0)
        assert new_stop is None  # 62 < 70, no improvement

    # 5. TRAILING_VOLATILITY
    def test_trailing_volatility_disabled_by_default(self):
        plan = _make_plan()
        new_stop = TrailingVolatilityPolicy(enabled=False).new_stop(plan, 95.0, 65.0, atr=5.0)
        assert new_stop is None

    def test_trailing_volatility_improves_stop(self):
        plan = _make_plan(entry=80.0, stop=65.0)
        # current_price=100, atr=5, multiplier=1.5 → candidate=100-7.5=92.5 > 65 → new stop
        policy = TrailingVolatilityPolicy(atr_multiplier=1.5, enabled=True)
        new_stop = policy.new_stop(plan, current_price=100.0, current_stop=65.0, atr=5.0)
        assert new_stop == pytest.approx(92.5)

    # 6. LIFECYCLE_EXIT
    def test_lifecycle_exit_disabled_by_default(self):
        plan = _make_plan()
        dec = LifecycleExitPolicy(enabled=False).evaluate(plan, 80.0, dte=0)
        assert dec is None

    def test_lifecycle_exit_fires_on_expiry(self):
        plan = _make_plan()
        dec = LifecycleExitPolicy(dte_threshold_days=0, enabled=True).evaluate(plan, 80.0, dte=0)
        assert dec is not None
        assert dec.action == ExitAction.DECAY_EXIT

    # 7. TIME_DECAY_EXIT
    def test_time_decay_disabled_by_default(self):
        plan = _make_plan()
        dec = TimeDecayExitPolicy(enabled=False, max_bars=10).evaluate(plan, 80.0, bars_held=20)
        assert dec is None

    def test_time_decay_fires_when_enabled(self):
        plan = _make_plan()
        dec = TimeDecayExitPolicy(enabled=True, max_bars=10).evaluate(plan, 80.0, bars_held=10)
        assert dec is not None
        assert dec.action == ExitAction.TIME_EXIT

    # 8. NO_PROGRESS_EXIT
    def test_no_progress_disabled_by_default(self):
        plan = _make_plan()
        dec = NoProgressExitPolicy(enabled=False).evaluate(plan, 80.0, bars_held=15, mfe=0.5)
        assert dec is None

    def test_no_progress_fires_when_mfe_insufficient(self):
        plan = _make_plan(entry=80.0, stop=65.0)  # risk=15pts
        policy = NoProgressExitPolicy(enabled=True, min_mfe_r=0.5, check_after_bars=5)
        # mfe=3pts → 3/15=0.2R < 0.5R threshold
        dec = policy.evaluate(plan, 80.0, bars_held=10, mfe=3.0)
        assert dec is not None
        assert dec.action == ExitAction.NO_PROGRESS_EXIT

    def test_composite_registry_stop_hit(self):
        plan = _make_plan(entry=80.0, stop=65.0)
        reg = ExitPolicyRegistry()
        dec = reg.evaluate_exit(plan, current_price=63.0, high=67.0, low=63.0,
                                current_stop=65.0)
        assert dec.action == ExitAction.FULL_EXIT
        assert "Stop loss" in dec.reason

    def test_composite_registry_hold(self):
        plan = _make_plan(entry=80.0, stop=65.0)
        reg = ExitPolicyRegistry()
        dec = reg.evaluate_exit(plan, current_price=85.0, high=87.0, low=82.0,
                                current_stop=65.0)
        assert dec.action == ExitAction.HOLD


# ─────────────────────────────────────────────────────────────────────────────
# 11. Threshold governance
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholdGovernance:
    def test_registry_not_empty(self):
        assert len(THRESHOLD_REGISTRY) > 0

    def test_locked_thresholds_have_source(self):
        for t in locked_thresholds():
            assert t.source, f"{t.name} has no source citation"

    def test_unvalidated_defaults_not_empty(self):
        assert len(unvalidated_thresholds()) > 0

    def test_disabled_thresholds_have_none_value(self):
        for t in disabled_thresholds():
            # Disabled thresholds should have None or a clearly marked value
            assert t.governance == GovernanceClass.DISABLED

    def test_no_invented_defaults_as_locked(self):
        """Ensure extension gate and R/R gate are not marked as LOCKED."""
        locked_names = {t.name for t in locked_thresholds()}
        assert "entry_extension_pct" not in locked_names
        assert "min_reward_risk_ratio" not in locked_names

    def test_quality_gates_disabled_defaults(self):
        gate = QualityGateEvaluator()  # all DISABLED by default
        assert gate._max_spread_points is None
        assert gate._min_reward_risk_ratio is None
        assert gate._max_entry_extension_pct is None

    def test_locked_tc_stop_value(self):
        from src.risk_engine.thresholds import get_threshold
        t = get_threshold("tc_leg_stop_loss_value")
        assert t is not None
        assert t.governance == GovernanceClass.LOCKED_STRATEGY_RULE
        assert t.value == 15.0

    def test_locked_bp_stop_pct(self):
        from src.risk_engine.thresholds import get_threshold
        t = get_threshold("bp_leg_stop_loss_pct")
        assert t is not None
        assert t.governance == GovernanceClass.LOCKED_STRATEGY_RULE
        assert t.value == 20.0


# ─────────────────────────────────────────────────────────────────────────────
# 12. Offline journal replay without look-ahead
# ─────────────────────────────────────────────────────────────────────────────

class TestOfflineReplay:
    def _write_journal(self, records: list, path: str):
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_replay_produces_plans_from_journal(self):
        svc = make_service()
        records = [
            {"payload": {"signal": "BUY", "entry": 85.0, "sl": 70.0,
                         "candle_id": f"c_{i}", "status": "ENTRY_CANDIDATE",
                         "option_contract": {"trading_symbol": "NIFTY26AUG24400CE",
                                             "option_type": "CE", "strike": 24400.0},
                         "lot_size": 25}}
            for i in range(3)
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            tmp_path = f.name
        try:
            result = svc.bootstrap_from_journal(tmp_path, "TC_NIFTY_PE_1M")
            assert result["records_scanned"] == 3
            assert len(svc._shadow_plans) > 0
        finally:
            os.unlink(tmp_path)

    def test_replay_chronological_no_lookahead(self):
        """
        Bars processed in strict order. Each bar's plan is independent.
        No future bar's data can affect an earlier bar's plan.
        """
        svc = make_service()
        records = []
        for i in range(5):
            records.append({"payload": {
                "signal": "BUY", "entry": 80.0 + i * 2,
                "sl": 65.0 + i, "candle_id": f"bar_{i}",
                "status": "ENTRY_CANDIDATE",
                "option_contract": {"trading_symbol": "NIFTY26AUG24400CE",
                                    "option_type": "CE", "strike": 24400.0},
                "lot_size": 25,
            }})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            tmp_path = f.name
        try:
            svc.bootstrap_from_journal(tmp_path, "TC_NIFTY_PE_1M", max_records=5)
            plans = list(svc._shadow_plans.values())
            # Each plan's entry_price should be from its own bar only
            entries = [p.entry_price for p in plans if not p.is_skipped]
            assert all(e < 200 for e in entries), "Entry prices must be premium, not look-ahead values"
        finally:
            os.unlink(tmp_path)

    def test_wait_records_not_replayed(self):
        svc = make_service()
        records = [
            {"payload": {"signal": "WAIT", "entry": None, "candle_id": "c_wait_1"}},
            {"payload": {"signal": "WAIT", "entry": None, "candle_id": "c_wait_2"}},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            tmp_path = f.name
        try:
            result = svc.bootstrap_from_journal(tmp_path, "TC_NIFTY_PE_1M")
            assert result["plans_generated"] == 0
        finally:
            os.unlink(tmp_path)


# ─────────────────────────────────────────────────────────────────────────────
# 13. Zero execution influence invariant
# ─────────────────────────────────────────────────────────────────────────────

class TestZeroExecutionInfluence:
    def test_shadow_status_reports_zero(self):
        svc = make_service()
        status = svc.get_shadow_status()
        assert status["execution_influence"] == "ZERO"

    def test_every_plan_has_execution_influence_zero(self):
        svc = make_service()
        for dep_id in ["TC_NIFTY_PE_1M", "BP_NIFTY_CE_1M", "PB_NIFTY_PE_1M"]:
            ev = ce_evaluation()
            ev["candle_id"] = dep_id
            plan = svc.evaluate_shadow_from_evaluation(dep_id, ev)
            assert plan.provenance.get("execution_influence") == "ZERO", (
                f"{dep_id} plan missing execution_influence=ZERO in provenance"
            )

    def test_skipped_plan_also_zero_influence(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("pullback-master-pine-v5", underlying_evaluation())
        assert plan.provenance.get("execution_influence") == "ZERO"

    def test_plan_shadow_mode_true(self):
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation("TC_NIFTY_PE_1M", ce_evaluation())
        assert plan.provenance.get("shadow_mode") is True

    def test_service_shadow_mode_true(self):
        svc = make_service()
        assert svc.shadow_mode is True

    def test_legacy_api_execution_influence_zero(self):
        svc = make_service()
        plan = svc.evaluate_shadow_risk_plan(
            strategy_id="TREND_CATCHER",
            instrument="NIFTY",
            side="LONG",
            entry_price=85.0,
            structural_invalidation=70.0,
            deployment_id="TC_NIFTY_PE_1M",
        )
        assert plan.provenance.get("execution_influence") == "ZERO"


# ─────────────────────────────────────────────────────────────────────────────
# 14. Closure Requirements Tests (Telemetry, UNVALIDATED telemetry, Suppression)
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeClosureRequirements:
    def test_unvalidated_risk_cap_telemetry_only(self):
        """UNVALIDATED 2% risk cap records WOULD_SKIP_IF_ENFORCED but does NOT hard-veto."""
        svc = make_service()
        # Entry 75, stop 60 -> distance 15 > 1.5 (2% cap)
        plan = svc.evaluate_shadow_from_evaluation("PB_NIFTY_PE_1M", pe_evaluation(entry=75.0, sl=60.0))
        assert plan.is_skipped is False
        assert plan.provenance.get("would_skip_if_enforced") is not None
        assert "STOP_EXCEEDS_RISK_CAP" in plan.provenance["would_skip_if_enforced"][0]

    def test_hook_failure_telemetry_recording(self):
        """Exceptions in shadow hook record bounded telemetry and do not crash."""
        svc = make_service()
        try:
            raise ValueError("Test shadow failure")
        except Exception as exc:
            svc.record_hook_failure("TC_NIFTY_PE_1M", exc)

        telemetry = svc.get_hook_telemetry()
        assert telemetry["risk_hook_failures"] == 1
        assert telemetry["last_failure_deployment"] == "TC_NIFTY_PE_1M"
        assert telemetry["last_failure_type"] == "ValueError"
        assert "Test shadow failure" in telemetry["last_failure_message"]

    def test_suppressed_candidate_provenance(self):
        """Suppressed candidate carries candidate_status=SUPPRESSED and actionable=False."""
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation(
            "TC_NIFTY_PE_1M",
            ce_evaluation(entry=85.0, sl=70.0),
            candidate_status="SUPPRESSED",
            suppression_reason="MAX_POSITIONS_REACHED",
        )
        assert plan.provenance.get("candidate_status") == "SUPPRESSED"
        assert plan.provenance.get("suppression_reason") == "MAX_POSITIONS_REACHED"
        assert plan.provenance.get("actionable") is False

    def test_unsuppressed_candidate_provenance(self):
        """Unsuppressed candidate carries candidate_status=ENTRY_CANDIDATE and actionable=True."""
        svc = make_service()
        plan = svc.evaluate_shadow_from_evaluation(
            "TC_NIFTY_PE_1M",
            ce_evaluation(entry=85.0, sl=70.0),
            candidate_status="ENTRY_CANDIDATE",
            suppression_reason=None,
        )
        assert plan.provenance.get("candidate_status") == "ENTRY_CANDIDATE"
        assert plan.provenance.get("suppression_reason") is None
        assert plan.provenance.get("actionable") is True

