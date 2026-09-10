"""
Unit & Integration Tests for Live NSE Session Proof & Five-Engine Real Evidence.
"""

import json
import pytest
from pathlib import Path

from src.broker.config_contract import get_runtime_configuration
from src.broker.dhan_resolver import DhanDynamicResolver
from src.broker.dhan_client import DhanClient
from src.premium_intelligence.worker import DhanSessionCaptureWorker, export_runtime_worker_truth_artifact
from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
from src.canonical_features.six_contracts import export_six_contract_real_evidence_artifact
from src.canonical_features.probes import SingleFactorProbeEngine
from src.strategy_lab.evaluator import GenericStrategyEvaluator
from src.premium_intelligence.performance import export_performance_artifact
from src.canonical_features.adversarial_audit import export_live_adversarial_findings_artifact, export_self_check_matrix_artifact, export_runtime_proof_artifact


def test_live_session_closure_worker_lock(tmp_path):
    lock_file = tmp_path / "live_worker.lock"
    worker = DhanSessionCaptureWorker(lock_file_path=str(lock_file))
    assert worker.acquire_lock() is True
    status = worker.get_status()
    assert status["worker_locked"] is True
    worker.release_lock()


def test_live_session_closure_artifacts_exist():
    resolver = DhanDynamicResolver()
    resolver.export_dhan_source_proof_artifact()

    export_runtime_worker_truth_artifact()

    svc = UnifiedPremiumIntelligenceService.get_instance()
    svc.export_v3_capture_summary_artifact(output_path="artifacts/live_session_closure/v3_capture_truth.json")
    svc.export_natural_boundary_proof_artifact()
    svc.export_five_engine_real_evidence_artifact()

    export_six_contract_real_evidence_artifact()

    probes = SingleFactorProbeEngine()
    probes.export_probe_maturity_truth_artifact()

    evaluator = GenericStrategyEvaluator()
    evaluator.export_strategy_44_runtime_truth_artifact()
    evaluator.export_apex_real_runtime_truth_artifact()
    evaluator.export_call_put_vertical_trace_artifact()

    export_self_check_matrix_artifact(output_path="artifacts/live_session_closure/self_check_matrix.json")
    export_live_adversarial_findings_artifact(output_path="artifacts/live_session_closure/adversarial_findings.json")
    export_performance_artifact(output_path="artifacts/live_session_closure/performance.json")
    export_runtime_proof_artifact(output_path="artifacts/live_session_closure/runtime_proof.json")

    expected_files = [
        "artifacts/live_session_closure/pre_execution_truth.json",
        "artifacts/live_session_closure/dhan_source_proof.json",
        "artifacts/live_session_closure/runtime_worker_truth.json",
        "artifacts/live_session_closure/v3_capture_truth.json",
        "artifacts/live_session_closure/natural_boundary_proof.json",
        "artifacts/live_session_closure/five_engine_real_evidence.json",
        "artifacts/live_session_closure/six_contract_real_evidence.json",
        "artifacts/live_session_closure/probe_maturity_truth.json",
        "artifacts/live_session_closure/strategy_44_runtime_truth.json",
        "artifacts/live_session_closure/apex_real_runtime_truth.json",
        "artifacts/live_session_closure/call_put_vertical_trace.json",
        "artifacts/live_session_closure/self_check_matrix.json",
        "artifacts/live_session_closure/adversarial_findings.json",
        "artifacts/live_session_closure/performance.json",
        "artifacts/live_session_closure/runtime_proof.json",
    ]

    for fpath in expected_files:
        assert Path(fpath).exists(), f"Missing expected artifact {fpath}"
