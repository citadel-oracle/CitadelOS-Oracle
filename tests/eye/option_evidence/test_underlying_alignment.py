"""E4A Underlying Alignment Diagnostic Tests."""

import pytest
from src.eye.option_evidence.alignment import evaluate_option_underlying_alignment, AlignmentState


def test_option_underlying_alignment_evaluations():
    # Bearish setup: Underlying falls 24500 -> 24450 (-50 pts). Put option rises 100 -> 125 (+25 pts).
    diag_put = evaluate_option_underlying_alignment(
        underlying_start_price=24500.0,
        underlying_end_price=24450.0,
        option_start_price=100.0,
        option_end_price=125.0,
        option_type="PE",
        delta=-0.45,
        setup_direction="BEARISH",
    )
    assert diag_put.alignment_state == AlignmentState.ALIGNED

    # Call option when underlying falls: premium falls 150 -> 130 (-20 pts).
    diag_call = evaluate_option_underlying_alignment(
        underlying_start_price=24500.0,
        underlying_end_price=24450.0,
        option_start_price=150.0,
        option_end_price=130.0,
        option_type="CE",
        delta=0.50,
        setup_direction="BEARISH",
    )
    assert diag_call.alignment_state == AlignmentState.ALIGNED
