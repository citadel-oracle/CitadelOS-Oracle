"""E3-E Audit Archive Integrity Test Suite."""

import pytest
from src.eye.composer.contracts import SetupDefinition, PatternStep, PartialMatch, PartialMatchStatus
from src.eye.composer.state import PartialMatchTracker
from src.eye.contracts import EventFamily, EventType, EventDirection
from datetime import datetime, timezone


def test_1001st_record_does_not_silently_delete_first_historical_record():
    sd = SetupDefinition(
        setup_id="TEST_ARCHIVE_V1", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Archive Test", status="RESEARCH", provenance="TEST",
        steps=(PatternStep(step_id="S1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,)),),
    )

    tracker = PartialMatchTracker(sd)
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)

    for i in range(1005):
        pm = PartialMatch(
            partial_match_id=f"PM_{i}", setup_id="TEST_ARCHIVE_V1", setup_version="1.0.0",
            partition_key="NSE:NIFTY:5m", current_step_index=0, bound_event_keys=(f"E_{i}",),
            bound_record_ids=(f"R_{i}",), started_at=now, last_advanced_at=now, expires_at=now,
            direction=EventDirection.BEARISH, status=PartialMatchStatus.COMPLETED,
        )
        tracker.update_match(pm)

    # Active matches must be 0 (all completed were evicted from active state)
    assert len(tracker.active_matches) == 0

    # Audit archive must retain ALL 1005 records (first historical record PM_0 NOT deleted)
    assert len(tracker.audit_archive) == 1005
    assert tracker.audit_archive[0].partial_match_id == "PM_0"
    assert tracker.audit_archive[1004].partial_match_id == "PM_1004"
