"""Pattern Step & Setup Definition Builders for Eye Engine E3."""

from typing import Optional, Sequence, Tuple
from src.eye.contracts import EventFamily, EventType, EventDirection, DetectionState, LifecycleState, AuthorityType
from src.eye.composer.contracts import PatternStep, SetupDefinition, ContiguityPolicy, MatchSkipPolicy, EventReusePolicy, OverlapPolicy


def create_pattern_step(
    step_id: str,
    accepted_families: Sequence[EventFamily],
    accepted_types: Sequence[EventType],
    direction_constraint: Optional[EventDirection] = None,
    timeframe_constraint: Optional[str] = None,
    required_detection_state: DetectionState = DetectionState.CONFIRMED_CLOSED_BAR,
    required_lifecycle_state: Optional[LifecycleState] = None,
    contiguity: ContiguityPolicy = ContiguityPolicy.RELAXED_NEXT,
    max_bars_from_prev: int = 20,
    max_elapsed_minutes: float = 120.0,
    optional_step: bool = False,
) -> PatternStep:
    return PatternStep(
        step_id=step_id,
        accepted_families=tuple(accepted_families),
        accepted_types=tuple(accepted_types),
        direction_constraint=direction_constraint,
        timeframe_constraint=timeframe_constraint,
        required_detection_state=required_detection_state,
        required_lifecycle_state=required_lifecycle_state,
        contiguity=contiguity,
        max_bars_from_prev=max_bars_from_prev,
        max_elapsed_minutes=max_elapsed_minutes,
        optional_step=optional_step,
    )
