"""E4A-C Test for FutEq Delta Classification Truth."""

import pytest
from src.eye.option_evidence.greeks import calculate_regulatory_futeq_delta


def test_futeq_classification_is_regulatory_delta_input_only():
    res = calculate_regulatory_futeq_delta(25, 0.50, 24500.0)
    assert res.classification == "REGULATORY_DELTA_INPUT_ONLY"
    assert res.compliance_claim_made is False
    assert res.delta_adjusted_quantity == 12.5
