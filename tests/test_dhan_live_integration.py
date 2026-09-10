"""
Unit and Integration Tests for Dhan Live Option-Chain Integration & Engine Evidence.
"""

import json
import pytest
from pathlib import Path

from src.broker.dhan_parser import DhanOptionChainParser
from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
from src.premium_intelligence.sae import StrikeAttentionEngine
from src.premium_intelligence.sme import StrikeMigrationEngine
from src.premium_intelligence.dgp import DealerGammaPressureProxy
from src.canonical_features.probes import SingleFactorProbeEngine
from src.strategy_command.edge_lab import export_call_put_runtime_evaluation_artifact
from src.premium_intelligence.performance import export_performance_artifact
from src.canonical_features.adversarial_audit import export_live_adversarial_findings_artifact


def test_dhan_parser_payload():
    parser = DhanOptionChainParser()
    raw = {
        "status": "SUCCESS",
        "data": {
            "underlying_spot": 24500.0,
            "expiry_date": "2026-08-06",
            "source_timestamp": "2026-08-01T13:30:00Z",
            "oc": {
                "24500": {
                    "ce": {"last_price": 105.0, "top_bid_price": 104.5, "top_ask_price": 105.5, "volume": 10000, "oi": 20000, "iv": 14.5},
                    "pe": {"last_price": 95.0, "top_bid_price": 94.5, "top_ask_price": 95.5, "volume": 10000, "oi": 20000, "iv": 15.0},
                }
            },
        },
    }
    rec, blockers = parser.parse_payload(raw)
    assert rec is not None
    assert rec.schema_version == "V3"
    assert len(blockers) == 0
    assert rec.nifty_spot == 24500.0
    assert "24500" in rec.strike_ladder


def test_dhan_parser_unauthenticated():
    parser = DhanOptionChainParser()
    raw = {"status": "FAILED", "remarks": "DHAN_UNAUTHENTICATED"}
    rec, blockers = parser.parse_payload(raw)
    assert rec is None
    assert "DHAN_UNAUTHENTICATED" in blockers


def test_dhan_source_contract_artifact():
    parser = DhanOptionChainParser()
    art = parser.export_source_contract_artifact()
    assert art["exchange_segment"] == "NSE_FNO"
    assert Path("artifacts/dhan_live_evidence/source_contract.json").exists()


def test_dhan_redacted_raw_response_artifact():
    parser = DhanOptionChainParser()
    art = parser.export_redacted_raw_response_artifact()
    assert art["status"] == "SUCCESS"
    assert Path("artifacts/dhan_live_evidence/redacted_raw_response.json").exists()


def test_v3_capture_summary_artifact():
    svc = UnifiedPremiumIntelligenceService.get_instance()
    art = svc.export_v3_capture_summary_artifact()
    assert art["store_schema_version"] == "V3"
    assert Path("artifacts/dhan_live_evidence/v3_capture_summary.json").exists()


def test_natural_boundary_summary_artifact():
    svc = UnifiedPremiumIntelligenceService.get_instance()
    art = svc.export_natural_boundary_summary_artifact()
    assert art["natural_boundary_timeframe"] == "5m"
    assert Path("artifacts/dhan_live_evidence/natural_boundary_summary.json").exists()


def test_pre_pli_natural_evidence_artifact():
    svc = UnifiedPremiumIntelligenceService.get_instance()
    art = svc.export_pre_pli_natural_evidence_artifact()
    assert "pre_regime_classification" in art
    assert Path("artifacts/dhan_live_evidence/pre_pli_natural_evidence.json").exists()


def test_sae_real_rankings_artifact():
    engine = StrikeAttentionEngine()
    art = engine.export_sae_real_rankings_artifact()
    assert art["real_ladder_ranking_active"] is True
    assert Path("artifacts/dhan_live_evidence/sae_real_rankings.json").exists()


def test_sme_real_migration_artifact():
    engine = StrikeMigrationEngine()
    art = engine.export_sme_real_migration_artifact()
    assert art["time_series_migration_active"] is True
    assert Path("artifacts/dhan_live_evidence/sme_real_migration.json").exists()


def test_dgp_source_coverage_artifact():
    engine = DealerGammaPressureProxy()
    art = engine.export_dgp_source_coverage_artifact()
    assert art["valid_source_pct"] == 85.0
    assert Path("artifacts/dhan_live_evidence/dgp_source_coverage.json").exists()


def test_probe_maturity_counts_artifact():
    engine = SingleFactorProbeEngine()
    art = engine.export_probe_maturity_counts_artifact()
    assert len(art["matured_labels_by_horizon"]) == 6
    assert Path("artifacts/dhan_live_evidence/probe_maturity_counts.json").exists()


def test_call_put_runtime_evaluation_artifact():
    art = export_call_put_runtime_evaluation_artifact()
    assert len(art["vertical_slices"]) == 2
    assert Path("artifacts/dhan_live_evidence/call_put_runtime_evaluation.json").exists()


def test_performance_artifact():
    art = export_performance_artifact()
    assert art["latency_metrics_ms"]["capture_p50"] > 0
    assert Path("artifacts/dhan_live_evidence/performance.json").exists()


def test_dhan_adversarial_findings_artifact():
    art = export_live_adversarial_findings_artifact(output_path="artifacts/dhan_live_evidence/adversarial_findings.json")
    assert art["defects_found"] == 0
    assert Path("artifacts/dhan_live_evidence/adversarial_findings.json").exists()
