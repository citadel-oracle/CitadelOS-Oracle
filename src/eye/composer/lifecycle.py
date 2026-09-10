"""Setup Candidate Lifecycle & Monotonic Revision Manager for Eye Engine E3."""

from datetime import datetime, timezone
from typing import Optional
from src.eye.contracts import compute_sha256
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus


def advance_candidate_status(
    candidate: SetupCandidateRecord,
    new_status: CandidateStatus,
    update_time: datetime,
    invalidation_source: Optional[str] = None,
) -> SetupCandidateRecord:
    """Create a new immutable revision of a SetupCandidateRecord with updated status."""
    new_revision = candidate.setup_revision + 1
    new_record_id = compute_sha256(f"{candidate.setup_key}:{new_revision}:{new_status.value}")[:16]

    inv_at = update_time if new_status in (CandidateStatus.INVALIDATED, CandidateStatus.EXPIRED, CandidateStatus.REJECTED) else candidate.invalidated_at
    conf_at = update_time if new_status == CandidateStatus.CONFIRMED else candidate.confirmed_at

    return SetupCandidateRecord(
        schema_version=candidate.schema_version,
        setup_key=candidate.setup_key,
        record_id=new_record_id,
        setup_revision=new_revision,
        setup_id=candidate.setup_id,
        setup_version=candidate.setup_version,
        setup_family=candidate.setup_family,
        instrument=candidate.instrument,
        direction=candidate.direction,
        status=new_status,
        started_at=candidate.started_at,
        confirmed_at=conf_at,
        invalidated_at=inv_at,
        evaluation_as_of=update_time,
        atomic_event_keys=candidate.atomic_event_keys,
        atomic_record_ids=candidate.atomic_record_ids,
        ordered_step_bindings=candidate.ordered_step_bindings,
        primary_level=candidate.primary_level,
        setup_definition_fingerprint=candidate.setup_definition_fingerprint,
        composer_version=candidate.composer_version,
        authority=candidate.authority,
        probability_status=candidate.probability_status,
        previous_record_id=candidate.record_id,
    )
