"""
Unit & Integration Tests for Major Leap Authenticated Dhan Production Integration & Five-Engine Runtime Closure.
"""

import json
import pytest
from pathlib import Path

from src.broker.config_contract import get_runtime_configuration, export_runtime_configuration_contract_artifact
from src.broker.dhan_resolver import DhanDynamicResolver
from src.broker.dhan_client import DhanClient
from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
from src.canonical_features.six_contracts import get_runtime_six_contracts_status, export_six_contract_runtime_matrix_artifact
from src.canonical_features.probes import SingleFactorProbeEngine
from src.strategy_lab.evaluator import GenericStrategyEvaluator
from src.premium_intelligence.performance import export_performance_artifact
from src.canonical_features.adversarial_audit import export_live_adversarial_findings_artifact, export_self_check_matrix_artifact, export_runtime_proof_artifact


def test_runtime_configuration_contract():
    cfg = get_runtime_configuration()
    assert cfg["dhan_access_token_present"] is True
    assert cfg["dhan_access_token_fingerprint"] == "b5337a2c"
    assert cfg["execution_influence"] == "ZERO"


def test_dhan_dynamic_resolver_expiry_list():
    resolver = DhanDynamicResolver()
    client = DhanClient()
    selected_expiry, expiries = resolver.select_active_expiry(client=client)
    assert len(expiries) > 0
    assert selected_expiry >= "2026-08-04"


def test_generic_44_strategy_evaluator():
    evaluator = GenericStrategyEvaluator()
    evals = evaluator.evaluate_all()
    assert len(evals) == 44
    call_evals = [e for e in evals if e["side"] == "CALL"]
    put_evals = [e for e in evals if e["side"] == "PUT"]
    assert len(call_evals) == 22
    assert len(put_evals) == 22


def test_major_leap_artifacts_exist():
    export_runtime_configuration_contract_artifact()
    resolver = DhanDynamicResolver()
    resolver.export_source_resolution_artifact()
    resolver.export_redacted_schema_artifact()

    svc = UnifiedPremiumIntelligenceService.get_instance()
    svc.export_v3_capture_truth_artifact()
    svc.export_natural_boundary_truth_artifact()
    svc.export_five_engine_runtime_matrix_artifact()

    export_six_contract_runtime_matrix_artifact()
    probes = SingleFactorProbeEngine()
    probes.export_probe_observation_and_maturity_artifact()

    evaluator = GenericStrategyEvaluator()
    evaluator.export_strategy_44_runtime_matrix_artifact()
    evaluator.export_apex_runtime_proofs_artifact()
    evaluator.export_call_put_vertical_traces_artifact()

    export_self_check_matrix_artifact()
    export_live_adversarial_findings_artifact(output_path="artifacts/major_leap/adversarial_findings.json")
    export_performance_artifact(output_path="artifacts/major_leap/performance.json")
    export_runtime_proof_artifact()

    expected_files = [
        "artifacts/major_leap/pre_edit_truth.json",
        "artifacts/major_leap/runtime_configuration_contract.json",
        "artifacts/major_leap/dhan_source_resolution.json",
        "artifacts/major_leap/dhan_redacted_schema.json",
        "artifacts/major_leap/v3_capture_truth.json",
        "artifacts/major_leap/natural_boundary_truth.json",
        "artifacts/major_leap/five_engine_runtime_matrix.json",
        "artifacts/major_leap/six_contract_runtime_matrix.json",
        "artifacts/major_leap/probe_observation_and_maturity.json",
        "artifacts/major_leap/strategy_44_runtime_matrix.json",
        "artifacts/major_leap/apex_runtime_proofs.json",
        "artifacts/major_leap/call_put_vertical_traces.json",
        "artifacts/major_leap/self_check_matrix.json",
        "artifacts/major_leap/adversarial_findings.json",
        "artifacts/major_leap/performance.json",
        "artifacts/major_leap/runtime_proof.json",
    ]

    for fpath in expected_files:
        assert Path(fpath).exists(), f"Missing expected artifact {fpath}"
