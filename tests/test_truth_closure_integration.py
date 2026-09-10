"""
Unit & Integration Tests for Autonomous Truth-First Runtime Closure Major Leap Sprint.
"""

import json
import pytest
from pathlib import Path

from src.broker.config_contract import get_runtime_configuration
from src.broker.dhan_resolver import DhanDynamicResolver
from src.broker.dhan_client import DhanClient
from src.premium_intelligence.worker import DhanSessionCaptureWorker, export_worker_runtime_truth_artifact
from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
from src.canonical_features.six_contracts import export_six_contract_truth_artifact
from src.canonical_features.probes import SingleFactorProbeEngine
from src.strategy_lab.evaluator import GenericStrategyEvaluator
from src.premium_intelligence.performance import export_performance_artifact
from src.canonical_features.adversarial_audit import export_live_adversarial_findings_artifact, export_self_check_matrix_artifact, export_runtime_proof_artifact, export_independent_verification_artifact


def test_truth_closure_worker_lock(tmp_path):
    lock_file = tmp_path / "truth_worker.lock"
    worker = DhanSessionCaptureWorker(lock_file_path=str(lock_file))
    assert worker.acquire_lock() is True
    status = worker.get_status()
    assert status["worker_locked"] is True
    worker.release_lock()


def test_truth_closure_artifacts_exist():
    resolver = DhanDynamicResolver()
    resolver.export_dhan_source_truth_artifact()

    export_worker_runtime_truth_artifact()

    svc = UnifiedPremiumIntelligenceService.get_instance()
    svc.export_v3_capture_summary_artifact(output_path="artifacts/truth_closure/v3_capture_truth.json")
    svc.export_natural_boundary_summary_artifact(output_path="artifacts/truth_closure/natural_boundary_truth.json")
    svc.export_five_engine_truth_artifact()

    export_six_contract_truth_artifact()

    probes = SingleFactorProbeEngine()
    probes.export_probe_truth_artifact()

    evaluator = GenericStrategyEvaluator()
    evaluator.export_strategy_44_truth_artifact()
    evaluator.export_apex_runtime_truth_artifact()
    evaluator.export_call_put_trace_artifact()

    export_independent_verification_artifact()
    export_live_adversarial_findings_artifact(output_path="artifacts/truth_closure/adversarial_findings.json")
    export_performance_artifact(output_path="artifacts/truth_closure/performance.json")
    export_runtime_proof_artifact(output_path="artifacts/truth_closure/runtime_proof.json")

    expected_files = [
        "artifacts/truth_closure/pre_edit_truth_ledger.json",
        "artifacts/truth_closure/dhan_source_truth.json",
        "artifacts/truth_closure/worker_runtime_truth.json",
        "artifacts/truth_closure/v3_capture_truth.json",
        "artifacts/truth_closure/natural_boundary_truth.json",
        "artifacts/truth_closure/five_engine_truth.json",
        "artifacts/truth_closure/six_contract_truth.json",
        "artifacts/truth_closure/probe_truth.json",
        "artifacts/truth_closure/strategy_44_truth.json",
        "artifacts/truth_closure/apex_runtime_truth.json",
        "artifacts/truth_closure/call_put_trace.json",
        "artifacts/truth_closure/independent_verification.json",
        "artifacts/truth_closure/adversarial_findings.json",
        "artifacts/truth_closure/performance.json",
        "artifacts/truth_closure/runtime_proof.json",
    ]

    for fpath in expected_files:
        assert Path(fpath).exists(), f"Missing expected artifact {fpath}"
