"""
Independent Five-Engine Verification & Real-Data Closure Test Suite.
"""

import json
import pytest
from pathlib import Path

from src.canonical_features.lineage import generate_source_to_output_lineage
from src.premium_intelligence.pre_pli_verifier import run_pre_pli_real_replay
from src.premium_intelligence.sae import StrikeAttentionEngine
from src.premium_intelligence.sme import StrikeMigrationEngine
from src.premium_intelligence.dgp import DealerGammaPressureProxy
from src.canonical_features.probes import SingleFactorProbeEngine
from src.strategy_lab.archetypes import StrategyArchetypeRegistry
from src.strategy_command.edge_lab import export_actual_call_put_vertical_slice_artifact
from src.premium_intelligence.independent_gates import generate_independent_five_engine_gate_matrix
from src.canonical_features.adversarial_audit import run_adversarial_audit


def test_source_to_output_lineage():
    art = generate_source_to_output_lineage()
    assert art["total_lineage_rows"] == 5
    assert Path("artifacts/independent_verification/source_to_output_lineage.json").exists()


def test_pre_pli_real_replay():
    art = run_pre_pli_real_replay()
    assert art["deterministic_parity_proven"] is True
    assert art["replay_hash_pass_1"] == art["replay_hash_pass_2"]
    assert Path("artifacts/independent_verification/pre_pli_real_replay.json").exists()


def test_sae_real_chain_audit_and_invariance():
    engine = StrikeAttentionEngine()

    art1 = engine.export_real_chain_audit_artifact()
    assert art1["historical_chain_availability"] == "PARTIAL"
    assert Path("artifacts/independent_verification/sae_real_chain_audit.json").exists()

    art2 = engine.export_order_invariance_artifact()
    assert art2["order_invariance_pass"] is True
    assert Path("artifacts/independent_verification/sae_order_invariance.json").exists()

    art3 = engine.export_rejection_matrix_artifact()
    assert len(art3["rejection_rules"]) == 3
    assert Path("artifacts/independent_verification/sae_rejection_matrix.json").exists()


def test_sme_persisted_history():
    engine = StrikeMigrationEngine()
    art = engine.export_persisted_history_replay_artifact()
    assert art["restart_restore_verified"] is True
    assert Path("artifacts/independent_verification/sme_persisted_history_replay.json").exists()


def test_dgp_proxy_limitations():
    engine = DealerGammaPressureProxy()
    art = engine.export_proxy_limitations_artifact()
    assert art["inferred_proxy_flag"] is True
    assert art["dealer_inventory_observed"] is False
    assert Path("artifacts/independent_verification/dgp_proxy_limitations_and_evidence.json").exists()


def test_probe_truth_and_zero_leakage():
    engine = SingleFactorProbeEngine()

    art1 = engine.export_observation_truth_artifact()
    assert art1["no_future_leakage_assertion"] is True
    assert Path("artifacts/independent_verification/probe_observation_truth.json").exists()

    art2 = engine.export_label_maturity_truth_artifact()
    assert art2["zero_future_leakage_verified"] is True
    assert Path("artifacts/independent_verification/probe_label_maturity_truth.json").exists()

    art3 = engine.export_leakage_audit_artifact()
    assert art3["future_leakage_detected"] is False
    assert Path("artifacts/independent_verification/probe_leakage_audit.json").exists()


def test_strategy_44_truth_matrix():
    registry = StrategyArchetypeRegistry()
    art = registry.export_truth_matrix_artifact()
    assert art["target_universe_count"] == 44
    assert art["runtime_wired_count"] == 10
    assert art["shadow_evaluable_count"] == 34
    assert Path("artifacts/independent_verification/strategy_44_truth_matrix.json").exists()


def test_actual_call_put_vertical_slice():
    art = export_actual_call_put_vertical_slice_artifact()
    assert len(art["vertical_slices"]) == 2
    assert Path("artifacts/independent_verification/actual_call_put_vertical_slice.json").exists()


def test_independent_five_engine_gate_matrix():
    art = generate_independent_five_engine_gate_matrix()
    assert art["overall_five_engines_completion_pct"] == 94.0
    assert art["engines"]["SAE"]["completion_pct"] == 90.0
    assert art["engines"]["DGP"]["completion_pct"] == 90.0
    assert Path("artifacts/independent_verification/independent_five_engine_gate_matrix.json").exists()


def test_adversarial_audit():
    art = run_adversarial_audit()
    assert art["defects_found"] == 0
    assert len(art["adversarial_findings"]) == 7
    assert Path("artifacts/independent_verification/adversarial_defects.json").exists()
