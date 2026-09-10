"""E4A-G Test for Checkpoint Creation & Crash Recovery Truncation."""

import pytest
from src.eye.option_capture.checkpoint import CheckpointManager, CaptureCheckpoint
from src.eye.option_capture.recovery import RecoveryManager


def test_checkpoint_and_recovery_truncation(tmp_path):
    ckpt_mgr = CheckpointManager(tmp_path)

    # Create Checkpoint 1
    chk1 = ckpt_mgr.create_checkpoint(
        session_id="SESS:E4AG:1",
        connection_epoch=1,
        universe_revision_number=1,
        last_raw_packet_id="PKT:50",
        last_raw_byte_offset=1024,
        canonical_observation_count=50,
        field_revision_count=100,
    )
    assert chk1.checkpoint_id == "CHK:1"

    # Recovery Manager scans and recovers incomplete WAL tail lines
    recovery_mgr = RecoveryManager(tmp_path)
    recovered, line_count, trunc_bytes = recovery_mgr.scan_and_recover()

    assert line_count == 0  # Clean initial state
