"""Detection and Lifecycle State Machine Validation for Eye Engine."""

from typing import Dict, Set, Tuple
from src.eye.contracts import DetectionState, LifecycleState, EventFamily, EyeContractError


# Detection state valid transition graph: (from_state -> set of valid to_states)
DETECTION_TRANSITIONS: Dict[DetectionState, Set[DetectionState]] = {
    DetectionState.PROVISIONAL_INTRABAR: {DetectionState.PENDING_CONFIRMATION, DetectionState.CONFIRMED_CLOSED_BAR, DetectionState.REJECTED},
    DetectionState.PENDING_CONFIRMATION: {DetectionState.CONFIRMED_CLOSED_BAR, DetectionState.REJECTED},
    DetectionState.CONFIRMED_CLOSED_BAR: {DetectionState.INVALIDATED},
    DetectionState.REJECTED: set(),
    DetectionState.INVALIDATED: set(),
}

# Lifecycle state valid transition graph by EventFamily
LIFECYCLE_TRANSITIONS: Dict[EventFamily, Dict[LifecycleState, Set[LifecycleState]]] = {
    EventFamily.ZONE: {
        LifecycleState.CREATED: {LifecycleState.ACTIVE},
        LifecycleState.ACTIVE: {LifecycleState.TESTED, LifecycleState.BROKEN, LifecycleState.EXPIRED},
        LifecycleState.TESTED: {LifecycleState.PARTIALLY_MITIGATED, LifecycleState.MITIGATED, LifecycleState.BROKEN},
        LifecycleState.PARTIALLY_MITIGATED: {LifecycleState.MITIGATED, LifecycleState.BROKEN},
        LifecycleState.MITIGATED: set(),
        LifecycleState.BROKEN: set(),
        LifecycleState.EXPIRED: set(),
    },
    EventFamily.STRUCTURE: {
        LifecycleState.CREATED: {LifecycleState.ACTIVE},
        LifecycleState.ACTIVE: {LifecycleState.INVALIDATED, LifecycleState.EXPIRED},
        LifecycleState.INVALIDATED: set(),
        LifecycleState.EXPIRED: set(),
    },
}


def validate_detection_transition(from_state: DetectionState, to_state: DetectionState) -> bool:
    allowed = DETECTION_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise EyeContractError(f"Invalid detection transition from {from_state.value} to {to_state.value}")
    return True


def validate_lifecycle_transition(family: EventFamily, from_state: LifecycleState, to_state: LifecycleState) -> bool:
    family_graph = LIFECYCLE_TRANSITIONS.get(family)
    if not family_graph:
        # Default policy: CREATED -> ACTIVE -> INVALIDATED
        if from_state == LifecycleState.CREATED and to_state == LifecycleState.ACTIVE:
            return True
        if from_state == LifecycleState.ACTIVE and to_state in (LifecycleState.INVALIDATED, LifecycleState.EXPIRED):
            return True
        raise EyeContractError(f"Invalid lifecycle transition for family {family.value} from {from_state.value} to {to_state.value}")

    allowed = family_graph.get(from_state, set())
    if to_state not in allowed:
        raise EyeContractError(f"Invalid lifecycle transition for family {family.value} from {from_state.value} to {to_state.value}")
    return True
