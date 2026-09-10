"""Partial Match State Machine & Memory Bounding for Eye Engine E3."""

from typing import Dict, List, Optional
from src.eye.composer.contracts import PartialMatch, PartialMatchStatus, SetupDefinition


class PartialMatchTracker:
    def __init__(self, definition: SetupDefinition, max_history: Optional[int] = None):
        self.definition = definition
        self.max_history = max_history
        self.active_matches: Dict[str, PartialMatch] = {}
        self.audit_archive: List[PartialMatch] = []
        self.completed_matches: List[PartialMatch] = []
        self.expired_matches: List[PartialMatch] = []
        self.cancelled_matches: List[PartialMatch] = []

    def add_match(self, match: PartialMatch) -> bool:
        if len(self.active_matches) >= self.definition.max_active_matches:
            # Enforce hard upper bound on active matches
            return False
        self.active_matches[match.partial_match_id] = match
        return True

    def update_match(self, match: PartialMatch):
        if match.status == PartialMatchStatus.COMPLETED:
            self.active_matches.pop(match.partial_match_id, None)
            self.completed_matches.append(match)
            self.audit_archive.append(match)
        elif match.status in (PartialMatchStatus.EXPIRED, PartialMatchStatus.CANCELLED, PartialMatchStatus.REJECTED):
            self.active_matches.pop(match.partial_match_id, None)
            if match.status == PartialMatchStatus.EXPIRED:
                self.expired_matches.append(match)
            else:
                self.cancelled_matches.append(match)
            self.audit_archive.append(match)
        else:
            self.active_matches[match.partial_match_id] = match

    def prune_expired(self, current_time):
        to_prune = [pm_id for pm_id, pm in self.active_matches.items() if pm.expires_at < current_time]
        for pm_id in to_prune:
            pm = self.active_matches.pop(pm_id)
            updated = PartialMatch(
                partial_match_id=pm.partial_match_id, setup_id=pm.setup_id, setup_version=pm.setup_version,
                partition_key=pm.partition_key, current_step_index=pm.current_step_index,
                bound_event_keys=pm.bound_event_keys, bound_record_ids=pm.bound_record_ids,
                started_at=pm.started_at, last_advanced_at=pm.last_advanced_at, expires_at=pm.expires_at,
                direction=pm.direction, status=PartialMatchStatus.EXPIRED, failure_reason="SETUP_WINDOW_EXPIRED",
                revision=pm.revision + 1, previous_revision_id=pm.partial_match_id,
            )
            self.expired_matches.append(updated)
            self.audit_archive.append(updated)
