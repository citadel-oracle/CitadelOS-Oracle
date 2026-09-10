"""
Unit & Integration Tests for Forensic Truth Matrix & Strategy-Specific Evaluator.
"""

import pytest
from src.strategy_lab.evaluator import GenericStrategyEvaluator
from src.strategy_lab.truth_matrix import calculate_truth_progress, export_forensic_truth_matrix_artifact


def test_44_strategy_distinct_logic_evaluator():
    evaluator = GenericStrategyEvaluator()
    evals = evaluator.evaluate_all()
    assert len(evals) == 44

    call_evals = [e for e in evals if e["side"] == "CALL"]
    put_evals = [e for e in evals if e["side"] == "PUT"]
    assert len(call_evals) == 22
    assert len(put_evals) == 22

    for e in evals:
        assert e["implementation_status"] == "LOGIC_IMPLEMENTED"
        assert "execution_influence" in e
        assert e["execution_influence"] == "ZERO"


def test_truth_progress_calculation():
    progress = calculate_truth_progress()
    assert progress["overall_progress"] == 59.76
    assert progress["max_score"] == 100
    assert "breakdown" in progress


def test_forensic_truth_matrix_artifact():
    art = export_forensic_truth_matrix_artifact()
    assert art["progress"]["overall_progress"] == 59.76
