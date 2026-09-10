"""
Comprehensive Unit & Integration Tests for Five-Engine Closure & Research Lab Sprint.
"""

import json
import pytest
from pathlib import Path

from src.canonical_features.truth_matrix import generate_engine_input_truth_matrix
from src.premium_intelligence.gate_matrix import generate_five_engine_gate_matrix
from src.premium_intelligence.sae import StrikeAttentionEngine
from src.premium_intelligence.sme import StrikeMigrationEngine
from src.premium_intelligence.dgp import DealerGammaPressureProxy
from src.canonical_features.probes import SingleFactorProbeEngine
from src.strategy_lab.archetypes import StrategyArchetypeRegistry
from src.strategy_command.edge_lab import export_actual_call_put_vertical_slice_artifact
from src.canonical_features.adversarial_audit import run_adversarial_audit


def test_engine_input_truth_matrix():
    art = generate_engine_input_truth_matrix()
    assert art["total_inputs_audited"] == 19
    assert Path("artifacts/engine_closure/engine_input_truth_matrix.json").exists()


def test_five_engine_gate_matrix():
    art = generate_five_engine_gate_matrix()
    assert art["overall_engines_completion_pct"] == 100.0
    for eng in ["PRE", "PLI", "SAE", "SME", "DGP"]:
        assert art["engines"][eng]["gates_passed"] == 10
    assert Path("artifacts/engine_closure/five_engine_gate_matrix.json").exists()


def test_sae_reorder_invariance_and_replay():
    engine = StrikeAttentionEngine()
    chain1 = [
        {"strike": 24500, "bid": 100.0, "ask": 101.0, "volume": 10000},
        {"strike": 24550, "bid": 70.0, "ask": 72.0, "volume": 5000},
    ]
    chain2 = list(reversed(chain1))

    snap1 = engine.evaluate(atm_strike=24500, option_chain=chain1)
    snap2 = engine.evaluate(atm_strike=24500, option_chain=chain2)

    assert snap1.top_strike == snap2.top_strike
    assert snap1.top_strike_score == snap2.top_strike_score

    art = engine.export_order_invariance_artifact()
    assert art["order_invariance_pass"] is True
    assert Path("artifacts/independent_verification/sae_order_invariance.json").exists()


def test_sme_migration_replay():
    engine = StrikeMigrationEngine()
    engine.record_sae_snapshot(timestamp="2026-08-01T10:00:00Z", top_strike=24500, ranked_strikes=[])
    engine.record_sae_snapshot(timestamp="2026-08-01T10:05:00Z", top_strike=24550, ranked_strikes=[])

    art = engine.export_persisted_history_replay_artifact()
    assert art["restart_restore_verified"] is True
    assert Path("artifacts/independent_verification/sme_persisted_history_replay.json").exists()


def test_dgp_proxy_evidence():
    engine = DealerGammaPressureProxy()
    art = engine.export_proxy_limitations_artifact()
    assert art["inferred_proxy_flag"] is True
    assert art["dealer_inventory_observed"] is False
    assert Path("artifacts/independent_verification/dgp_proxy_limitations_and_evidence.json").exists()


def test_single_factor_probes_and_outcome_store():
    engine = SingleFactorProbeEngine()
    engine.record_probe_observation(timestamp="2026-08-01T10:00:00Z", probe_id="PROBE_01", raw_value=75.0)

    art1 = engine.export_observation_truth_artifact()
    assert art1["no_future_leakage_assertion"] is True
    assert Path("artifacts/independent_verification/probe_observation_truth.json").exists()

    art2 = engine.export_label_maturity_truth_artifact()
    assert art2["zero_future_leakage_verified"] is True
    assert Path("artifacts/independent_verification/probe_label_maturity_truth.json").exists()


def test_44_strategy_activation_matrix():
    registry = StrategyArchetypeRegistry()
    art = registry.export_truth_matrix_artifact()
    assert art["target_universe_count"] == 44
    assert art["runtime_wired_count"] == 10
    assert art["shadow_evaluable_count"] == 34
    assert Path("artifacts/independent_verification/strategy_44_truth_matrix.json").exists()


def test_vertical_slice_trace_and_adversarial_findings():
    art1 = export_actual_call_put_vertical_slice_artifact()
    assert len(art1["vertical_slices"]) == 2
    assert Path("artifacts/independent_verification/actual_call_put_vertical_slice.json").exists()

    art2 = run_adversarial_audit()
    assert len(art2["adversarial_findings"]) == 7
    assert Path("artifacts/independent_verification/adversarial_defects.json").exists()
