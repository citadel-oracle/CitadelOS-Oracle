"""
Unit & Integration Tests for Dhan Authentication Closure & Autonomous Session Evidence Capture.
"""

import json
import pytest
from pathlib import Path

from src.broker.auth_audit import audit_dhan_authentication, export_authentication_and_source_proof_artifact
from src.broker.dhan_client import DhanClient
from src.broker.dhan_parser import DhanOptionChainParser
from src.premium_intelligence.worker import DhanSessionCaptureWorker, export_v3_real_capture_summary_artifact, export_natural_boundary_evidence_artifact
from src.premium_intelligence.sae import StrikeAttentionEngine
from src.premium_intelligence.sme import StrikeMigrationEngine
from src.premium_intelligence.dgp import DealerGammaPressureProxy
from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
from src.canonical_features.probes import SingleFactorProbeEngine
from src.strategy_command.edge_lab import export_call_put_real_runtime_trace_artifact
from src.premium_intelligence.performance import export_performance_artifact
from src.canonical_features.adversarial_audit import export_live_adversarial_findings_artifact


def test_auth_audit_dhan_credentials():
    audit_res = audit_dhan_authentication()
    assert "auth_state" in audit_res
    assert audit_res["auth_state"] in ("DHAN_TOKEN_REJECTED", "DHAN_AUTHENTICATED", "DHAN_CREDENTIALS_MISSING")
    assert audit_res["execution_influence"] == "ZERO"


def test_dhan_client_dotenv_auto_load():
    client = DhanClient()
    assert client.access_token is not None
    assert len(client.access_token) > 0


def test_dhan_session_worker_single_instance_lock(tmp_path):
    lock_file = tmp_path / "test_worker.lock"
    worker1 = DhanSessionCaptureWorker(lock_file_path=str(lock_file))
    worker2 = DhanSessionCaptureWorker(lock_file_path=str(lock_file))

    assert worker1.acquire_lock() is True
    assert worker2.acquire_lock() is False
    worker1.release_lock()
    assert worker2.acquire_lock() is True
    worker2.release_lock()


def test_authentication_and_source_proof_artifact():
    art = export_authentication_and_source_proof_artifact()
    assert "auth_state" in art
    assert Path("artifacts/dhan_session/authentication_and_source_proof.json").exists()


def test_real_response_parser_audit_artifact():
    parser = DhanOptionChainParser()
    art = parser.export_source_contract_artifact(output_path="artifacts/dhan_session/real_response_parser_audit.json")
    assert art["exchange_segment"] == "NSE_FNO"
    assert Path("artifacts/dhan_session/real_response_parser_audit.json").exists()


def test_v3_real_capture_summary_artifact():
    art = export_v3_real_capture_summary_artifact()
    assert art["store_schema_version"] == "V3"
    assert Path("artifacts/dhan_session/v3_real_capture_summary.json").exists()


def test_natural_boundary_evidence_artifact():
    art = export_natural_boundary_evidence_artifact()
    assert art["natural_boundary_timeframe"] == "5m"
    assert Path("artifacts/dhan_session/natural_boundary_evidence.json").exists()


def test_sae_real_session_evidence_artifact():
    sae = StrikeAttentionEngine()
    art = sae.export_sae_real_session_evidence_artifact()
    assert art["real_ladder_ranking_active"] is True
    assert Path("artifacts/dhan_session/sae_real_session_evidence.json").exists()


def test_sme_real_session_evidence_artifact():
    sme = StrikeMigrationEngine()
    art = sme.export_sme_real_session_evidence_artifact()
    assert art["time_series_migration_active"] is True
    assert Path("artifacts/dhan_session/sme_real_session_evidence.json").exists()


def test_dgp_real_source_coverage_artifact():
    dgp = DealerGammaPressureProxy()
    art = dgp.export_dgp_real_source_coverage_artifact()
    assert art["valid_source_pct"] == 85.0
    assert Path("artifacts/dhan_session/dgp_real_source_coverage.json").exists()


def test_pre_pli_real_session_evidence_artifact():
    svc = UnifiedPremiumIntelligenceService.get_instance()
    art = svc.export_pre_pli_real_session_evidence_artifact()
    assert "pre_regime_classification" in art
    assert Path("artifacts/dhan_session/pre_pli_real_session_evidence.json").exists()


def test_probe_real_maturity_counts_artifact():
    probes = SingleFactorProbeEngine()
    art = probes.export_probe_real_maturity_counts_artifact()
    assert len(art["matured_labels_by_horizon"]) == 6
    assert Path("artifacts/dhan_session/probe_real_maturity_counts.json").exists()


def test_call_put_real_runtime_trace_artifact():
    art = export_call_put_real_runtime_trace_artifact()
    assert len(art["vertical_slices"]) == 2
    assert Path("artifacts/dhan_session/call_put_real_runtime_trace.json").exists()


def test_performance_dhan_session_artifact():
    art = export_performance_artifact(output_path="artifacts/dhan_session/performance.json")
    assert art["latency_metrics_ms"]["capture_p50"] > 0
    assert Path("artifacts/dhan_session/performance.json").exists()


def test_adversarial_findings_dhan_session_artifact():
    art = export_live_adversarial_findings_artifact(output_path="artifacts/dhan_session/adversarial_findings.json")
    assert art["defects_found"] == 0
    assert Path("artifacts/dhan_session/adversarial_findings.json").exists()
