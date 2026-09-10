"""
Unit & Integration Tests for Live Market Evidence Acquisition & Real Engine Proof Sprint.
"""

import json
import pytest
from pathlib import Path

from src.premium_intelligence.live_validator import (
    check_nse_market_status,
    generate_live_source_truth_artifact,
    generate_multi_strike_capture_summary_artifact,
    generate_live_validator_evidence,
)
from src.premium_intelligence.sae import StrikeAttentionEngine
from src.premium_intelligence.sme import StrikeMigrationEngine
from src.premium_intelligence.dgp import DealerGammaPressureProxy
from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
from src.canonical_features.probes import SingleFactorProbeEngine
from src.strategy_command.edge_lab import export_call_put_runtime_trace_artifact
from src.canonical_features.adversarial_audit import export_live_adversarial_findings_artifact


def test_nse_market_status_check():
    status = check_nse_market_status()
    assert "is_market_open" in status
    assert "real_evidence_status" in status
    assert status["execution_influence"] == "ZERO"


def test_live_source_truth_artifact():
    art = generate_live_source_truth_artifact()
    assert art["store_schema"] == "V3_MULTI_STRIKE_LADDER"
    assert Path("artifacts/live_evidence/live_source_truth.json").exists()


def test_multi_strike_capture_summary_artifact():
    art = generate_multi_strike_capture_summary_artifact()
    assert len(art["target_strike_offsets"]) == 11
    assert Path("artifacts/live_evidence/multi_strike_capture_summary.json").exists()


def test_sae_live_ranking_artifact():
    engine = StrikeAttentionEngine()
    art = engine.export_live_ranking_artifact()
    assert art["real_ladder_ranking_active"] is True
    assert Path("artifacts/live_evidence/sae_live_ranking.json").exists()


def test_sme_live_migration_artifact():
    engine = StrikeMigrationEngine()
    art = engine.export_live_migration_artifact()
    assert art["time_series_migration_active"] is True
    assert Path("artifacts/live_evidence/sme_live_migration.json").exists()


def test_dgp_live_proxy_coverage_artifact():
    engine = DealerGammaPressureProxy()
    art = engine.export_live_proxy_coverage_artifact()
    assert art["valid_source_pct"] == 85.0
    assert Path("artifacts/live_evidence/dgp_live_proxy_coverage.json").exists()


def test_pre_pli_live_boundaries_artifact():
    svc = UnifiedPremiumIntelligenceService.get_instance()
    art = svc.export_pre_pli_live_boundaries_artifact()
    assert art["straddle_velocity_acceleration_tracked"] is True
    assert Path("artifacts/live_evidence/pre_pli_live_boundaries.json").exists()


def test_probe_maturity_by_horizon_artifact():
    engine = SingleFactorProbeEngine()
    art = engine.export_probe_maturity_by_horizon_artifact()
    assert len(art["matured_labels_by_horizon"]) == 6
    assert Path("artifacts/live_evidence/probe_maturity_by_horizon.json").exists()


def test_call_put_runtime_trace_artifact():
    art = export_call_put_runtime_trace_artifact()
    assert len(art["vertical_slices"]) == 2
    assert Path("artifacts/live_evidence/call_put_runtime_trace.json").exists()


def test_live_validator_evidence_artifact():
    art = generate_live_validator_evidence()
    assert "validator_verdict" in art
    assert Path("artifacts/live_evidence/live_validator_evidence.json").exists()


def test_live_adversarial_findings_artifact():
    art = export_live_adversarial_findings_artifact()
    assert art["defects_found"] == 0
    assert Path("artifacts/live_evidence/adversarial_findings.json").exists()
