"""E4A-E Test for Duplicate Packet Idempotency."""

import pytest
from src.eye.option_capture.raw_journal import RawJournalWriter
from src.eye.option_capture.contracts import RawPacketType


def test_duplicate_packet_writing(tmp_path):
    writer = RawJournalWriter(tmp_path)
    payload = b'{"seq": 100, "price": 150.0}'

    rec1 = writer.write_packet("SESS:1", RawPacketType.WEBSOCKET_BINARY, "wss://api-feed.dhan.co", payload, sequence_number=100)
    rec2 = writer.write_packet("SESS:1", RawPacketType.WEBSOCKET_BINARY, "wss://api-feed.dhan.co", payload, sequence_number=100)

    assert rec1.payload_sha256 == rec2.payload_sha256
    assert writer.packet_count == 2
