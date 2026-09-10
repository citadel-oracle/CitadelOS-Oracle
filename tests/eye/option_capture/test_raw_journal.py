"""E4A-E Test for Append-Only Raw Packet Journal Writer."""

import pytest
from pathlib import Path
from src.eye.option_capture.raw_journal import RawJournalWriter
from src.eye.option_capture.contracts import RawPacketType


def test_raw_journal_writer_appends(tmp_path):
    writer = RawJournalWriter(tmp_path)
    payload = b'{"status": "ok", "access-token": "secret123"}'

    rec1 = writer.write_packet("SESS:1", RawPacketType.REST_RESPONSE, "/v2/optionchain", payload)
    assert rec1.packet_id == "PKT:1"
    assert rec1.payload_size_bytes == len(payload)

    # Read journal file and verify secret redaction
    content = (tmp_path / "raw_packets" / "raw_journal.jsonl").read_text()
    assert "[REDACTED_SECRET]" in content
    assert "secret123" not in content
