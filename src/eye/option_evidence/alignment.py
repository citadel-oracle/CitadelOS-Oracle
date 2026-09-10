"""Pre-Setup Price Response Alignment Diagnostics for Eye Engine Phase E4A."""

from dataclasses import dataclass
from typing import Optional
from src.eye.option_evidence.contracts import AlignmentState


@dataclass(frozen=True)
class AlignmentDiagnostics:
    alignment_state: AlignmentState
    underlying_change_points: float
    option_change_points: float
    expected_delta_change_points: Optional[float]
    observed_minus_delta_component: Optional[float]
    explanation: str


def evaluate_option_underlying_alignment(
    underlying_start_price: float,
    underlying_end_price: float,
    option_start_price: float,
    option_end_price: float,
    option_type: str,
    delta: Optional[float] = None,
    setup_direction: str = "BEARISH",
) -> AlignmentDiagnostics:
    """Evaluate pre-setup price response alignment between underlying and option premium."""
    u_change = underlying_end_price - underlying_start_price
    o_change = option_end_price - option_start_price

    exp_delta_change = round(u_change * delta, 4) if delta is not None else None
    diff_comp = round(o_change - exp_delta_change, 4) if exp_delta_change is not None else None

    opt_type = option_type.upper()

    # Determine expected premium movement direction
    # Call option benefits from positive underlying change (+u_change)
    # Put option benefits from negative underlying change (-u_change)
    if opt_type == "CE":
        expected_positive = u_change > 0
    else:
        expected_positive = u_change < 0

    if abs(u_change) < 1.0 or abs(o_change) < 0.25:
        a_state = AlignmentState.INDETERMINATE
        expl = "Underlying or option movement below minimum diagnostic threshold."
    elif (expected_positive and o_change > 0) or (not expected_positive and o_change < 0):
        a_state = AlignmentState.ALIGNED
        expl = f"Option premium change ({o_change:+.2f}) aligned with underlying movement ({u_change:+.2f})."
    else:
        a_state = AlignmentState.DIVERGENT
        expl = f"Option premium change ({o_change:+.2f}) diverged from underlying movement ({u_change:+.2f})."

    return AlignmentDiagnostics(
        alignment_state=a_state,
        underlying_change_points=round(u_change, 2),
        option_change_points=round(o_change, 2),
        expected_delta_change_points=exp_delta_change,
        observed_minus_delta_component=diff_comp,
        explanation=expl,
    )
