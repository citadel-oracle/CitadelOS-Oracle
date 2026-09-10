"""Deduplication & Overlap Suppression for Eye Engine E3."""

from typing import List, Optional, Sequence
from src.eye.contracts import compute_sha256, canonical_json
from src.eye.composer.contracts import SetupCandidateRecord, OverlapPolicy


def generate_setup_key(setup_id: str, instrument_key: str, direction: str, atomic_event_keys: Sequence[str], primary_level: Optional[str] = None) -> str:
    """Generate stable semantic setup key (identity)."""
    raw = {
        "setup_id": setup_id,
        "instrument_key": instrument_key,
        "direction": str(direction),
        "atomic_event_keys": list(atomic_event_keys),
    }
    if primary_level:
        raw["primary_level"] = str(primary_level)
    return f"SETUP:{setup_id}:{compute_sha256(canonical_json(raw))[:16]}"


def generate_record_id(setup_key: str, setup_revision: int, status: str, atomic_record_ids: Sequence[str], previous_record_id: Optional[str] = None) -> str:
    """Generate unique immutable lifecycle-record identity."""
    raw = {
        "setup_key": setup_key,
        "setup_revision": setup_revision,
        "status": str(status),
        "atomic_record_ids": list(atomic_record_ids),
        "previous_record_id": previous_record_id,
    }
    return f"REC:{compute_sha256(canonical_json(raw))[:16]}"


def filter_overlapping_candidates(candidates: Sequence[SetupCandidateRecord], policy: OverlapPolicy) -> List[SetupCandidateRecord]:
    """Filter candidate records based on OverlapPolicy."""
    if policy == OverlapPolicy.RETAIN_ALL:
        return list(candidates)

    seen_keys = set()
    filtered = []
    for c in candidates:
        if policy == OverlapPolicy.SUPPRESS_IDENTICAL:
            if c.setup_key in seen_keys:
                continue
            seen_keys.add(c.setup_key)
            filtered.append(c)
        elif policy == OverlapPolicy.KEEP_EARLIEST_COMPLETION:
            if c.setup_key not in seen_keys:
                seen_keys.add(c.setup_key)
                filtered.append(c)
        else:
            filtered.append(c)
    return filtered
