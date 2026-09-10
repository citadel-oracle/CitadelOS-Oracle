"""
Unit & Integration Tests for ALL-44 Real Runtime Activation & Research Lab Closure Sprint.
"""

import pytest
from pathlib import Path
from src.strategy_lab.evaluator import GenericStrategyEvaluator
from src.strategy_lab.truth_matrix import calculate_truth_progress


def test_all44_runtime_evaluator():
    evaluator = GenericStrategyEvaluator()
    evals = evaluator.evaluate_all()
    assert len(evals) == 44

    call_evals = [e for e in evals if e["side"] == "CALL"]
    put_evals = [e for e in evals if e["side"] == "PUT"]
    assert len(call_evals) == 22
    assert len(put_evals) == 22

    for e in evals:
        assert e["evaluated"] is True
        assert e["execution_influence"] == "ZERO"


def test_all44_runtime_artifacts_exist():
    evaluator = GenericStrategyEvaluator()
    evaluator.export_pre_edit_matrix_artifact()
    evaluator.export_runtime_registration_matrix_artifact()
    evaluator.export_material_distinctness_matrix_artifact()
    evaluator.export_persistence_summary_artifact()
    evaluator.export_replay_availability_matrix_artifact()
    evaluator.export_direct_runtime_cycle_artifact()
    evaluator.export_independent_verification_all44_artifact()

    expected_files = [
        "artifacts/all44_runtime/pre_edit_matrix.json",
        "artifacts/all44_runtime/runtime_registration_matrix.json",
        "artifacts/all44_runtime/material_distinctness_matrix.json",
        "artifacts/all44_runtime/persistence_summary.json",
        "artifacts/all44_runtime/replay_availability_matrix.json",
        "artifacts/all44_runtime/direct_runtime_cycle.json",
        "artifacts/all44_runtime/independent_verification.json",
        "artifacts/all44_runtime/progress_calculation.json",
    ]

    for fpath in expected_files:
        assert Path(fpath).exists(), f"Missing expected artifact {fpath}"


def test_all44_truth_progress_calculation():
    progress = calculate_truth_progress()
    assert progress["overall_progress"] == 59.76
    assert progress["max_score"] == 100
