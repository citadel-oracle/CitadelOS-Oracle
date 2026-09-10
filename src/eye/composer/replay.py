"""Offline Setup Replay Harness for Eye Engine E3."""

from typing import List, Sequence
from src.eye.contracts import EyeEventRecord
from src.eye.composer.contracts import SetupDefinition, SetupCandidateRecord
from src.eye.composer.ordering import sort_events_canonically
from src.eye.composer.matcher import SetupComposer


class OfflineSetupReplayHarness:
    def __init__(self, definitions: Sequence[SetupDefinition]):
        self.definitions = list(definitions)

    def replay_incremental(self, events: Sequence[EyeEventRecord]) -> List[SetupCandidateRecord]:
        sorted_events = sort_events_canonically(events)
        composer = SetupComposer(self.definitions)
        all_candidates = []
        for e in sorted_events:
            cands = composer.process_event(e)
            all_candidates.extend(cands)
        return all_candidates

    def replay_batch(self, events: Sequence[EyeEventRecord]) -> List[SetupCandidateRecord]:
        return self.replay_incremental(events)
