"""Tests for Detection and Lifecycle Transition State Machines."""

import pytest
from src.eye.contracts import DetectionState, LifecycleState, EyeContractError
from src.eye.validation import validate_detection_transition, validate_lifecycle_transition, EventFamily


def test_detection_state_transitions():
    # Valid transitions
    assert validate_detection_transition(DetectionState.PROVISIONAL_INTRABAR, DetectionState.PENDING_CONFIRMATION)
    assert validate_detection_transition(DetectionState.PENDING_CONFIRMATION, DetectionState.CONFIRMED_CLOSED_BAR)
    assert validate_detection_transition(DetectionState.PROVISIONAL_INTRABAR, DetectionState.REJECTED)
    assert validate_detection_transition(DetectionState.CONFIRMED_CLOSED_BAR, DetectionState.INVALIDATED)

    # Invalid transitions fail!
    with pytest.raises(EyeContractError, match="Invalid detection transition"):
        validate_detection_transition(DetectionState.REJECTED, DetectionState.CONFIRMED_CLOSED_BAR)

    with pytest.raises(EyeContractError, match="Invalid detection transition"):
        validate_detection_transition(DetectionState.INVALIDATED, DetectionState.PROVISIONAL_INTRABAR)


def test_zone_lifecycle_transitions():
    family = EventFamily.ZONE

    # Valid transitions for Zone (FVG / OB)
    assert validate_lifecycle_transition(family, LifecycleState.CREATED, LifecycleState.ACTIVE)
    assert validate_lifecycle_transition(family, LifecycleState.ACTIVE, LifecycleState.TESTED)
    assert validate_lifecycle_transition(family, LifecycleState.TESTED, LifecycleState.PARTIALLY_MITIGATED)
    assert validate_lifecycle_transition(family, LifecycleState.PARTIALLY_MITIGATED, LifecycleState.MITIGATED)

    # Invalid transition for Zone
    with pytest.raises(EyeContractError, match="Invalid lifecycle transition"):
        validate_lifecycle_transition(family, LifecycleState.MITIGATED, LifecycleState.CREATED)
