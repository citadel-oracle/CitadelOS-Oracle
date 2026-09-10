"""Typed Event Predicates for CITADEL Eye Engine E3."""

from typing import Optional
from src.eye.contracts import EyeEventRecord, EventFamily, EventType, EventDirection, DetectionState, LifecycleState
from src.eye.composer.contracts import PatternStep


def match_event_predicate(event: EyeEventRecord, step: PatternStep) -> bool:
    """Evaluate whether an EyeEventRecord satisfies a PatternStep predicate."""
    if step.accepted_families and event.family not in step.accepted_families:
        return False
    if step.accepted_types and event.event_type not in step.accepted_types:
        return False
    if step.direction_constraint and event.direction != step.direction_constraint:
        return False
    if step.timeframe_constraint and event.timeframe != step.timeframe_constraint:
        return False
    if step.required_detection_state and event.detection_state != step.required_detection_state:
        return False
    if step.required_lifecycle_state and event.lifecycle_state != step.required_lifecycle_state:
        return False
    return True
