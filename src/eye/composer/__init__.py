"""CITADEL Eye Engine Phase E3 Setup Composer Package."""

from src.eye.composer.contracts import (
    SetupDefinition,
    PatternStep,
    SetupCandidateRecord,
    PartialMatch,
    ContiguityPolicy,
    MatchSkipPolicy,
    EventReusePolicy,
    OverlapPolicy,
    CandidateStatus,
    PartialMatchStatus,
)
from src.eye.composer.setup_registry import get_e3_setup_definitions, get_setup_definition_by_id
from src.eye.composer.matcher import SetupComposer
from src.eye.composer.replay import OfflineSetupReplayHarness

__all__ = [
    "SetupDefinition",
    "PatternStep",
    "SetupCandidateRecord",
    "PartialMatch",
    "ContiguityPolicy",
    "MatchSkipPolicy",
    "EventReusePolicy",
    "OverlapPolicy",
    "CandidateStatus",
    "PartialMatchStatus",
    "get_e3_setup_definitions",
    "get_setup_definition_by_id",
    "SetupComposer",
    "OfflineSetupReplayHarness",
]
