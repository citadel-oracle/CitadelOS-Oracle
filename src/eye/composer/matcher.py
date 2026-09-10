"""Deterministic Setup Composer State Machine for Eye Engine E3."""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Sequence, Set
from src.eye.contracts import EyeEventRecord, EventDirection, AuthorityType, ProbabilityStatus, LifecycleState, DetectionState
from src.eye.composer.contracts import (
    SetupDefinition,
    PartialMatch,
    PartialMatchStatus,
    SetupCandidateRecord,
    CandidateStatus,
    ContiguityPolicy,
    MatchSkipPolicy,
    EventReusePolicy,
    OverlapPolicy,
)
from src.eye.composer.predicates import match_event_predicate
from src.eye.composer.ordering import get_event_knowledge_time
from src.eye.composer.state import PartialMatchTracker
from src.eye.composer.deduplication import generate_setup_key, generate_record_id, filter_overlapping_candidates


class SetupComposer:
    def __init__(self, definitions: Sequence[SetupDefinition]):
        self.definitions = list(definitions)
        self.trackers: Dict[str, PartialMatchTracker] = {
            d.setup_id: PartialMatchTracker(d) for d in self.definitions
        }
        self.candidates: List[SetupCandidateRecord] = []
        self.audit_archive: List[SetupCandidateRecord] = []
        self.processed_record_ids: Set[str] = set()
        self.latest_event_revisions: Dict[str, int] = {}
        self.consumed_event_keys: Set[str] = set()
        self.last_watermark: Optional[tuple] = None

    def process_event(self, event: EyeEventRecord) -> List[SetupCandidateRecord]:
        """Ingest a single canonical EyeEventRecord into the composer."""
        ktime = get_event_knowledge_time(event)
        if self.last_watermark and ktime < self.last_watermark:
            # Reject out-of-order events before watermark
            return []
        self.last_watermark = ktime

        # 1. Exact record_id replay idempotency check
        if event.record_id in self.processed_record_ids:
            return []
        self.processed_record_ids.add(event.record_id)

        # 2. Check event revision monotonicity
        prev_rev = self.latest_event_revisions.get(event.event_key)
        if prev_rev is not None and event.event_revision <= prev_rev:
            # Out-of-order or duplicate revision with lower/equal revision number
            return []
        self.latest_event_revisions[event.event_key] = event.event_revision

        newly_confirmed: List[SetupCandidateRecord] = []

        # 3. Check Parent Invalidation Propagation
        if event.lifecycle_state in (LifecycleState.INVALIDATED, LifecycleState.MITIGATED, LifecycleState.BROKEN) or event.detection_state == DetectionState.INVALIDATED:
            inv_revisions: List[SetupCandidateRecord] = []
            for cand in list(self.candidates):
                if cand.status == CandidateStatus.CONFIRMED and event.event_key in cand.atomic_event_keys:
                    new_rev = cand.setup_revision + 1
                    rec_id = generate_record_id(cand.setup_key, new_rev, CandidateStatus.INVALIDATED.value, cand.atomic_record_ids + (event.record_id,), cand.record_id)
                    inv_cand = SetupCandidateRecord(
                        schema_version=cand.schema_version,
                        setup_key=cand.setup_key,
                        record_id=rec_id,
                        setup_revision=new_rev,
                        setup_id=cand.setup_id,
                        setup_version=cand.setup_version,
                        setup_family=cand.setup_family,
                        instrument=cand.instrument,
                        direction=cand.direction,
                        status=CandidateStatus.INVALIDATED,
                        started_at=cand.started_at,
                        confirmed_at=cand.confirmed_at,
                        invalidated_at=event.evaluation_context.as_of,
                        evaluation_as_of=event.evaluation_context.as_of,
                        atomic_event_keys=cand.atomic_event_keys,
                        atomic_record_ids=cand.atomic_record_ids + (event.record_id,),
                        ordered_step_bindings=cand.ordered_step_bindings,
                        primary_level=cand.primary_level,
                        setup_definition_fingerprint=cand.setup_definition_fingerprint,
                        authority=cand.authority,
                        probability_status=cand.probability_status,
                        previous_record_id=cand.record_id,
                    )
                    inv_revisions.append(inv_cand)
                    self.candidates.append(inv_cand)
                    self.audit_archive.append(inv_cand)
            return inv_revisions

        for d in self.definitions:
            if d.status == "UNRESOLVED":
                # Unresolved setup definitions do NOT process events or emit candidates
                continue

            tracker = self.trackers[d.setup_id]
            tracker.prune_expired(event.evaluation_context.as_of)

            # Check EventReusePolicy
            if d.event_reuse_policy == EventReusePolicy.FORBID_ACROSS_MATCHES and event.event_key in self.consumed_event_keys:
                continue

            # 1. Evaluate existing active matches to advance step
            active_list = list(tracker.active_matches.values())
            for pm in active_list:
                next_step_idx = pm.current_step_index + 1
                if next_step_idx < len(d.steps):
                    step = d.steps[next_step_idx]
                    if match_event_predicate(event, step):
                        # Advance step
                        new_bound_keys = pm.bound_event_keys + (event.event_key,)
                        new_bound_ids = pm.bound_record_ids + (event.record_id,)

                        if next_step_idx == len(d.steps) - 1:
                            # Completed!
                            completed_pm = PartialMatch(
                                partial_match_id=pm.partial_match_id, setup_id=pm.setup_id, setup_version=pm.setup_version,
                                partition_key=pm.partition_key, current_step_index=next_step_idx,
                                bound_event_keys=new_bound_keys, bound_record_ids=new_bound_ids,
                                started_at=pm.started_at, last_advanced_at=event.evaluation_context.as_of,
                                expires_at=event.evaluation_context.as_of + timedelta(minutes=step.max_elapsed_minutes),
                                direction=pm.direction, status=PartialMatchStatus.COMPLETED,
                                revision=pm.revision + 1, previous_revision_id=pm.partial_match_id,
                            )
                            tracker.update_match(completed_pm)

                            # Record consumed event keys under FORBID_ACROSS_MATCHES
                            if d.event_reuse_policy == EventReusePolicy.FORBID_ACROSS_MATCHES:
                                self.consumed_event_keys.update(new_bound_keys)

                            # Emit Candidate with 2-Identity Model
                            s_key = generate_setup_key(
                                d.setup_id, event.instrument.instrument_key, event.direction.value, new_bound_keys,
                                str(event.payload.primary_level) if hasattr(event.payload, "primary_level") else None
                            )
                            rec_id = generate_record_id(s_key, 1, CandidateStatus.CONFIRMED.value, new_bound_ids, None)

                            cand = SetupCandidateRecord(
                                schema_version="1.0.0", setup_key=s_key, record_id=rec_id,
                                setup_revision=1, setup_id=d.setup_id, setup_version=d.setup_version,
                                setup_family=d.setup_family, instrument=event.instrument, direction=event.direction,
                                status=CandidateStatus.CONFIRMED, started_at=pm.started_at, confirmed_at=event.evaluation_context.as_of,
                                invalidated_at=None, evaluation_as_of=event.evaluation_context.as_of,
                                atomic_event_keys=new_bound_keys, atomic_record_ids=new_bound_ids,
                                ordered_step_bindings=tuple({"step_id": d.steps[i].step_id, "event_key": k} for i, k in enumerate(new_bound_keys)),
                                primary_level=event.payload.primary_level if hasattr(event.payload, "primary_level") else None,
                                setup_definition_fingerprint=d.fingerprint, authority=AuthorityType.OBSERVATION_ONLY,
                                probability_status=ProbabilityStatus.NOT_ESTABLISHED, previous_record_id=None,
                            )
                            newly_confirmed.append(cand)

                            # Apply SKIP_PAST_LAST_EVENT
                            if d.match_skip_policy == MatchSkipPolicy.SKIP_PAST_LAST_EVENT:
                                tracker.active_matches.clear()
                        else:
                            advancing_pm = PartialMatch(
                                partial_match_id=pm.partial_match_id, setup_id=pm.setup_id, setup_version=pm.setup_version,
                                partition_key=pm.partition_key, current_step_index=next_step_idx,
                                bound_event_keys=new_bound_keys, bound_record_ids=new_bound_ids,
                                started_at=pm.started_at, last_advanced_at=event.evaluation_context.as_of,
                                expires_at=event.evaluation_context.as_of + timedelta(minutes=step.max_elapsed_minutes),
                                direction=pm.direction, status=PartialMatchStatus.ADVANCING,
                                revision=pm.revision + 1, previous_revision_id=pm.partial_match_id,
                            )
                            tracker.update_match(advancing_pm)
                    else:
                        # Under STRICT_NEXT, non-matching intervening event cancels active match
                        if step.contiguity == ContiguityPolicy.STRICT_NEXT or d.contiguity_policy == ContiguityPolicy.STRICT_NEXT:
                            cancelled_pm = PartialMatch(
                                partial_match_id=pm.partial_match_id, setup_id=pm.setup_id, setup_version=pm.setup_version,
                                partition_key=pm.partition_key, current_step_index=pm.current_step_index,
                                bound_event_keys=pm.bound_event_keys, bound_record_ids=pm.bound_record_ids,
                                started_at=pm.started_at, last_advanced_at=event.evaluation_context.as_of,
                                expires_at=pm.expires_at, direction=pm.direction, status=PartialMatchStatus.CANCELLED,
                                failure_reason="STRICT_CONTIGUITY_BREACH", revision=pm.revision + 1, previous_revision_id=pm.partial_match_id,
                            )
                            tracker.update_match(cancelled_pm)

            # 2. Check if event can start a new partial match at Step 0
            if d.steps and match_event_predicate(event, d.steps[0]):
                pm_id = f"PM:{d.setup_id}:{event.event_key}"
                exp_at = event.evaluation_context.as_of + timedelta(minutes=d.steps[0].max_elapsed_minutes)
                new_pm = PartialMatch(
                    partial_match_id=pm_id, setup_id=d.setup_id, setup_version=d.setup_version,
                    partition_key=f"{event.instrument.instrument_key}:{event.timeframe}",
                    current_step_index=0, bound_event_keys=(event.event_key,), bound_record_ids=(event.record_id,),
                    started_at=event.evaluation_context.as_of, last_advanced_at=event.evaluation_context.as_of,
                    expires_at=exp_at, direction=event.direction, status=PartialMatchStatus.STARTED,
                )
                tracker.add_match(new_pm)

        filtered = filter_overlapping_candidates(newly_confirmed, OverlapPolicy.KEEP_EARLIEST_COMPLETION)
        self.candidates.extend(filtered)
        self.audit_archive.extend(filtered)
        return filtered
