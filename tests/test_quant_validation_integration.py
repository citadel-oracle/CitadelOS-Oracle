"""
Unit & Integration Tests for Phase-13 Quant Validation Suite & Vertical Slice.
"""

import pytest
from pathlib import Path
from src.quant_validation.trial_registry import TrialRegistry, TrialRecord
from src.quant_validation.walk_forward import ChronologicalWalkForwardSplitter
from src.quant_validation.cost_model import CostAwareOutcomeEngine
from src.quant_validation.multiple_testing import MultipleTestingEvaluator
from src.quant_validation.vertical_slice import QuantValidationVerticalSlice
from src.strategy_lab.truth_matrix import calculate_truth_progress


def test_trial_registry_and_walk_forward():
    registry = TrialRegistry(registry_file="logs/quant_validation/test_registry.jsonl")
    rec = TrialRecord(
        trial_id="TEST_01",
        strategy_id="ARGUS_APEX_C1_SIMPLE",
        code_commit="4db6b56bf84ee69bede55587bba9a8d941599be7",
        feature_version="1.0.0",
        parameter_hash="hash123",
        dataset_hash="dhan_v3",
        instrument="NIFTY",
        date_range="2026-07-01..2026-08-01",
        fold="Fold_1",
        cost_model="CostAware_10bps",
        result_state="VALIDATION_READY",
        trades_count=10,
        profit_factor=1.5,
        sharpe_ratio=1.8,
        max_drawdown=0.05,
        timestamp="2026-08-01T14:00:00Z",
    )
    registry.register_trial(rec)
    trials = registry.list_trials("ARGUS_APEX_C1_SIMPLE")
    assert len(trials) >= 1

    splitter = ChronologicalWalkForwardSplitter()
    folds = splitter.generate_folds()
    assert len(folds) == 3


def test_cost_model_and_multiple_testing():
    cost_engine = CostAwareOutcomeEngine()
    cost_res = cost_engine.apply_cost_to_trade(100.0, 120.0, side="BUY", quantity=50)
    assert cost_res["net_pnl"] < cost_res["gross_pnl"]

    dsr = MultipleTestingEvaluator.calculate_dsr(sharpe_ratio=1.8, num_trials=44, sample_size=30)
    assert dsr["status"] == "COMPUTED"

    pbo = MultipleTestingEvaluator.calculate_pbo([0.1, 0.2, -0.05, 0.15, -0.02])
    assert pbo["status"] == "COMPUTED"


def test_vertical_slice_and_artifacts_exist():
    slice_runner = QuantValidationVerticalSlice()
    res = slice_runner.run_vertical_slice()
    assert res["total_vertical_slice_strategies"] == 4

    expected_files = [
        "artifacts/runtime_quant_leap/pre_edit_claim_ledger.json",
        "artifacts/runtime_quant_leap/authoritative_runtime_matrix.json",
        "artifacts/runtime_quant_leap/material_distinctness_report.json",
        "artifacts/runtime_quant_leap/raw_persistence_proof.json",
        "artifacts/runtime_quant_leap/replay_availability_matrix.json",
        "artifacts/runtime_quant_leap/trial_registry_summary.json",
        "artifacts/runtime_quant_leap/walk_forward_integrity.json",
        "artifacts/runtime_quant_leap/validation_vertical_slice.json",
        "artifacts/runtime_quant_leap/independent_verification.json",
        "artifacts/runtime_quant_leap/adversarial_quant_findings.json",
        "artifacts/runtime_quant_leap/progress_calculation.json",
    ]

    for fpath in expected_files:
        assert Path(fpath).exists(), f"Missing expected artifact {fpath}"


def test_quant_validation_truth_progress_calculation():
    progress = calculate_truth_progress()
    assert progress["overall_progress"] == 59.76
    assert progress["max_score"] == 100
