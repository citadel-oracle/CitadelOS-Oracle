"""E4A-E Test for Checkpoint Creation & Abrupt Termination Recovery."""

import pytest
from pathlib import Path
from src.eye.option_capture.checkpoint import CheckpointManager
from src.eye.option_capture.recovery import RecoveryManager


def test_checkpoint_and_tail_recovery(tmp_path):
    chk_mgr = CheckpointManager(tmp_path)
    chk = chk_mgr.create_checkpoint("SESS:1", connection_epoch=1, universe_revision_number=1, last_raw_packet_id="PKT:10", last_raw_byte_offset=500, canonical_observation_count=10, field_revision_count=15)

    assert chk.checkpoint_id == "CHK:1"

    # Simulate un-flushed corrupt tail bytes in raw_journal.jsonl
    journal_file = tmp_path / "raw_packets" / "raw_journal.jsonl"
    journal_file.parent.mkdir(parents=True, exist_ok=True)
    journal_file.write_bytes(b'{"packet_id": "PKT:1", "session_id": "SESS:1"}\n{"packet_id": "PKT:2"') # Incomplete line

    rec_mgr = RecoveryManager(tmp_path)
    recovered, valid_cnt, truncated_bytes = rec_mgr.scan_and_recover()

    assert recovered is True
    assert valid_cnt == 1
    assert truncated_bytes > 0
