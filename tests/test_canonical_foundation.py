"""
Unit & Integration Tests for CITADEL Canonical Foundation Repair.
"""

import json
import pytest
from pathlib import Path

from src.canonical_features.six_contracts import (
    SixContractsEnvelope,
    DirectionalAlphaSnapshot,
    RegimeSnapshot,
    EntryTimingSnapshot,
    ContractQualitySnapshot,
    RiskFragilitySnapshot,
    DataConfidenceSnapshot,
    generate_contract_inventory_artifact,
)
from src.canonical_features.registry import DedicatedCanonicalFeatureRegistry, CORE_CANONICAL_FEATURES
from src.canonical_features.cluster_caps import ClusterCapEvaluator
from src.strategy_command.apex_proofs import export_apex_behaviour_matrix_artifact, APEX_BEHAVIOURAL_MATRIX


def test_six_contracts_independence():
    alpha = DirectionalAlphaSnapshot(call_score=75.0, put_score=25.0, bias_direction="CALL")
    regime = RegimeSnapshot(regime_type="EXPANSION", expansion_index=80.0)
    timing = EntryTimingSnapshot(setup_type="BREAKOUT", trigger_confirmed=True)
    quality = ContractQualitySnapshot(selected_side="CALL", selected_strike=24500, contract_quality_score=95.0)
    risk = RiskFragilitySnapshot(actionable=False, skip_reason="INSUFFICIENT_EVIDENCE")
    confidence = DataConfidenceSnapshot(readiness_state="READY", live_authority_count=10)

    envelope = SixContractsEnvelope(
        snapshot_id="snap_test_001",
        directional_alpha=alpha,
        regime=regime,
        entry_timing=timing,
        contract_quality=quality,
        risk_fragility=risk,
        data_confidence=confidence,
    )

    d = envelope.to_dict()
    assert d["snapshot_id"] == "snap_test_001"
    assert d["directional_alpha"]["bias_direction"] == "CALL"
    assert d["regime"]["regime_type"] == "EXPANSION"
    assert d["risk_fragility"]["actionable"] is False


def test_contract_inventory_artifact_generation():
    inv = generate_contract_inventory_artifact("artifacts/canonical_foundation/contract_inventory.json")
    assert inv["total_contracts"] == 6
    assert Path("artifacts/canonical_foundation/contract_inventory.json").exists()


def test_canonical_feature_registry_completeness():
    reg = DedicatedCanonicalFeatureRegistry()
    features = reg.list_all()
    assert len(features) == 16

    for feat in features:
        d = feat.to_dict()
        assert "canonical_name" in d
        assert "meaning" in d
        assert "owner_engine" in d
        assert "unit" in d
        assert "missing_data_state" in d
        assert d["missing_data_state"] == "NOT_AVAILABLE"

    artifact = reg.export_inventory_artifact("artifacts/canonical_foundation/feature_registry.json")
    assert artifact["total_registered_features"] == 16
    assert Path("artifacts/canonical_foundation/feature_registry.json").exists()


def test_cluster_cap_evaluator_shadow():
    evaluator = ClusterCapEvaluator(max_cluster_pct=35.0)
    scores = {
        "option.premium_return.5m": 90.0,
        "option.premium_velocity.5m": 90.0,
        "option.premium_acceleration.5m": 90.0,
        "spot.return.5m": 50.0,
    }
    weights = {
        "option.premium_return.5m": 25.0,
        "option.premium_velocity.5m": 25.0,
        "option.premium_acceleration.5m": 25.0,
        "spot.return.5m": 25.0,
    }

    result = evaluator.evaluate_shadow(scores, weights)
    assert result.legacy_score > result.cluster_adjusted_score
    assert "premium_cluster" in result.affected_clusters
    assert result.execution_influence == "ZERO"

    report = evaluator.export_shadow_report([result], "artifacts/canonical_foundation/cluster_shadow_report.json")
    assert report["sample_count"] == 1
    assert Path("artifacts/canonical_foundation/cluster_shadow_report.json").exists()


def test_apex_behavioural_matrix():
    artifact = export_apex_behaviour_matrix_artifact("artifacts/canonical_foundation/apex_behaviour_matrix.json")
    assert artifact["total_apex_strategies"] == 10

    matrix_by_id = {p.strategy_id: p for p in APEX_BEHAVIOURAL_MATRIX}

    # C1/P1 Loose Prime-independent
    assert matrix_by_id["ARGUS_APEX_C1_SIMPLE"].actual_prime_dependency == "Prime-independent"
    assert matrix_by_id["ARGUS_APEX_C1_SIMPLE"].candidate_discovered is True

    # C4 Escape acceleration path
    assert matrix_by_id["ARGUS_APEX_C4_BIG_MOVE_ESCAPE"].escape_acceleration_path_proven is True

    # C5 Reversal absorption path
    assert matrix_by_id["ARGUS_APEX_C5_WALL_REVERSAL"].reversal_absorption_path_proven is True

    assert Path("artifacts/canonical_foundation/apex_behaviour_matrix.json").exists()
